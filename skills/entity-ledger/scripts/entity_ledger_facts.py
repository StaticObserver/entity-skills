#!/usr/bin/env python3
"""Fact derivation shared by the planner and the primitive commands.

Pure derivation helpers: confirmation gates, site policy defaults, and
identity/path derivation.  This module must never import the planner;
the dependency direction is planner -> facts."""

from __future__ import print_function

import getpass
import json
import os
import re
import subprocess

from entity_ledger_common import (
    LedgerError,
    absolute,
    load_simulation_confirmation,
    run_on_site,
    site_file_sha256,
    source_manifest,
    valid_gres,
)
from entity_ledger_store import CaseResolutionError, canonical_hash


class PlanError(LedgerError):
    def __init__(self, message, status="invalid_request", decisions=None):
        LedgerError.__init__(self, message)
        self.status = status
        self.decisions = decisions or []


def _git_revision(path):
    process = subprocess.Popen(
        ["git", "-C", path, "rev-parse", "HEAD", "HEAD^{tree}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )
    stdout, unused = process.communicate()
    if process.returncode != 0:
        return {"kind": "path", "root": path}
    values = [line.strip() for line in stdout.splitlines() if line.strip()]
    dirty = subprocess.Popen(
        ["git", "-C", path, "status", "--porcelain"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )
    dirty_out, unused = dirty.communicate()
    return {"kind": "git", "commit": values[0], "tree": values[1],
            "dirty": dirty.returncode != 0 or bool(dirty_out.strip())}


def _sites(store):
    connection = store._connect()
    try:
        return [json.loads(row[0]) for row in connection.execute(
            "SELECT profile_json FROM sites ORDER BY site_id"
        )]
    finally:
        connection.close()


def _source_site(store, project_root):
    matches = []
    for profile in _sites(store):
        if profile.get("transport", {}).get("kind") != "local":
            continue
        root = profile.get("roots", {}).get("source_root")
        if not root:
            continue
        try:
            if os.path.commonpath([project_root, absolute(root)]) == absolute(root):
                matches.append((len(absolute(root)), profile["site_id"]))
        except ValueError:
            pass
    if not matches:
        raise PlanError(
            "no local Site source_root covers the project",
            "needs_decision",
            [{"field": "site",
              "question": "register a local source Site for the project: add a "
                          "site archive (sites/<site>.yaml) with transport "
                          "{\"kind\": \"local\"} and roots.source_root covering "
                          "the project directory — a good value is the "
                          "workspace root, not your whole home — then run "
                          "`entityctl site sync` and retry"}],
        )
    matches.sort(reverse=True)
    return matches[0][1]


def _resolve_input(project_root, value):
    path = absolute(value if os.path.isabs(value) else os.path.join(project_root, value))
    try:
        inside = os.path.commonpath([path, project_root]) == project_root
    except ValueError:
        inside = False
    if not inside:
        raise PlanError("input is outside the project root")
    if not os.path.isfile(path):
        raise PlanError("input does not exist: %s" % path)
    return path


def _remote_file(profile, path):
    if profile.get("transport", {}).get("kind") == "local":
        return os.path.isfile(path)
    code, unused, unused_err = run_on_site(profile, ["test", "-f", path])
    return code == 0


def _current_build_executable(case, profile, explicit):
    if explicit:
        build_root = profile.get("roots", {}).get("build_root")
        if not build_root:
            raise PlanError("execution Site is missing build_root")
        path = explicit if os.path.isabs(explicit) else os.path.join(build_root, explicit)
        path = os.path.normpath(path)
        try:
            inside = os.path.commonpath([path, os.path.normpath(build_root)]) == os.path.normpath(build_root)
        except ValueError:
            inside = False
        if not inside:
            raise PlanError("explicit executable is outside the Site build_root")
        if not _remote_file(profile, path):
            raise PlanError("executable does not exist on execution Site: %s" % path)
        return path, ""
    current_id = case.get("current", {}).get("build_id", "")
    identities = case.get("identities", {}).get("build", {}).get("items", [])
    current = None
    for item in identities:
        if item.get("id") == current_id or item.get("identity_id") == current_id:
            current = item
            break
    if current is None:
        raise PlanError(
            "no verified current build executable is available",
            "needs_decision",
            [{"field": "executable", "question": "provide or build an executable"}],
        )
    candidates = []
    for output in current.get("outputs", current.get("evidence", [])):
        locator = output.get("locator", {}) if isinstance(output, dict) else {}
        path = locator.get("path", "")
        if locator.get("site_id") == profile["site_id"] and path:
            name = os.path.basename(path)
            if name == "entity.xc" or name.endswith(".xc"):
                candidates.append(path)
    if not candidates:
        raise PlanError(
            "current build identity has no executable evidence",
            "needs_decision",
            [{"field": "executable", "question": "select the verified executable"}],
        )
    candidates = sorted(set(candidates), key=lambda item: (os.path.basename(item) != "entity.xc", item))
    if not _remote_file(profile, candidates[0]):
        raise PlanError("current build executable is no longer present: %s" % candidates[0])
    return candidates[0], current_id


LAUNCHERS = {"", "srun", "mpirun", "mpiexec"}


def _slurm_site_policy(profile, compute):
    policy = profile.get("policy", {})
    normalized = dict(compute)
    normalized.setdefault("nodes", 1)
    normalized.setdefault("tasks", int(normalized["gpus"]))
    normalized.setdefault("cpus_per_task", int(policy.get("default_cpus_per_gpu", 1)))
    normalized.setdefault("partition", policy.get("default_partition", ""))
    normalized.setdefault("qos", policy.get("default_qos", ""))
    if normalized.get("launcher", "") not in LAUNCHERS:
        raise PlanError(
            "compute.launcher must be one of %s (got %r)"
            % (", ".join(sorted(LAUNCHERS)), normalized.get("launcher")),
            "needs_decision",
            [{"field": "policy.mpi_launcher",
              "question": "configure a valid mpi_launcher (srun, mpirun or "
                          "mpiexec) in the Site policy"}],
        )
    if "submit_user" not in normalized:
        if policy.get("default_submit_user"):
            normalized["submit_user"] = policy["default_submit_user"]
        elif profile.get("transport", {}).get("kind") == "local":
            normalized["submit_user"] = getpass.getuser()
        else:
            raise PlanError(
                "SSH Slurm Site has no default_submit_user",
                "needs_decision",
                [{"field": "compute.submit_user",
                  "question": "confirm the scheduler user for Site %s" % profile["site_id"]}],
            )
    if (profile.get("scheduler", {}).get("kind") == "slurm"
            and not normalized.get("partition")):
        raise PlanError(
            "Slurm Site has no default_partition",
            "needs_decision",
            [{"field": "compute.partition",
              "question": "select a Slurm partition for Site %s" % profile["site_id"]}],
        )
    # gres resolution order: explicit CLI --gres > policy default_gres >
    # generic "gpu:<gpus>".  The resolved string is what the sbatch renders
    # and what the run identity records.
    gres = str(normalized.get("gres") or "")
    if not gres:
        gres = str(policy.get("default_gres") or "")
    if not gres:
        gres = "gpu:%s" % normalized["gpus"]
    if not valid_gres(gres):
        raise PlanError(
            "compute.gres must match gpu[:type]:count (got %r)" % gres,
            "needs_decision",
            [{"field": "compute.gres",
              "question": "provide a valid gres such as gpu:1 or gpu:V100:1"}],
        )
    normalized["gres"] = gres
    maximum = policy.get("max_cpu_per_gpu")
    if maximum is not None and normalized["cpus_per_task"] > int(maximum):
        raise PlanError(
            "compute.cpus_per_task exceeds Site max_cpu_per_gpu=%s" % maximum,
            "needs_decision",
            [{"field": "compute.cpus_per_task",
              "question": "choose no more than %s CPUs per GPU" % maximum}],
        )
    for field in ["partition", "qos", "submit_user"]:
        if (not isinstance(normalized[field], str)
                or not re.match(r"^[A-Za-z0-9_.@+-]*$", normalized[field])):
            raise PlanError("Site policy produced invalid compute.%s" % field)
    return normalized


def _direct_site_policy(profile, compute):
    """Policy for scheduler-less Sites: no partition/QoS/scheduler account
    exists, so those fields normalize to empty strings and the submit user
    defaults to the current user without a needs_decision round-trip.  gres
    is Slurm-only: the direct backend ignores it and normalizes it to ""."""
    policy = profile.get("policy", {})
    normalized = dict(compute)
    if normalized.get("launcher", "") not in LAUNCHERS - {"srun"}:
        raise PlanError(
            "compute.launcher on a scheduler-less Site must be mpirun, "
            "mpiexec or empty (got %r)" % normalized.get("launcher"),
            "needs_decision",
            [{"field": "policy.mpi_launcher",
              "question": "srun needs a Slurm allocation — configure mpirun "
                          "or mpiexec as the Site mpi_launcher"}],
        )
    normalized.setdefault("nodes", 1)
    # MPI runs need one rank per GPU; a bare (non-MPI) run is a single
    # process no matter how many GPUs were requested.
    mpi = normalized.get("launcher") in {"mpirun", "mpiexec"}
    normalized.setdefault("tasks", int(normalized["gpus"]) if mpi else 1)
    normalized.setdefault("cpus_per_task", int(policy.get("default_cpus_per_gpu", 1)))
    normalized.setdefault("partition", "")
    normalized.setdefault("qos", "")
    normalized["gres"] = ""
    if "submit_user" not in normalized:
        if policy.get("default_submit_user"):
            normalized["submit_user"] = policy["default_submit_user"]
        else:
            normalized["submit_user"] = getpass.getuser()
    maximum = policy.get("max_cpu_per_gpu")
    if maximum is not None and normalized["cpus_per_task"] > int(maximum):
        raise PlanError(
            "compute.cpus_per_task exceeds Site max_cpu_per_gpu=%s" % maximum,
            "needs_decision",
            [{"field": "compute.cpus_per_task",
              "question": "choose no more than %s CPUs per GPU" % maximum}],
        )
    for field in ["partition", "qos", "submit_user"]:
        if (not isinstance(normalized[field], str)
                or not re.match(r"^[A-Za-z0-9_.@+-]*$", normalized[field])):
            raise PlanError("Site policy produced invalid compute.%s" % field)
    return normalized


RUN_BACKENDS = {
    "slurm": {"scheduler": "slurm", "validate_policy": _slurm_site_policy},
    "none": {"scheduler": "direct", "validate_policy": _direct_site_policy},
}


def _run_backend(profile):
    kind = profile.get("scheduler", {}).get("kind")
    backend = RUN_BACKENDS.get(kind)
    if backend is None:
        raise PlanError(
            "run Goal currently supports scheduler kinds: %s (got '%s')"
            % (", ".join(sorted(RUN_BACKENDS)), kind)
        )
    return kind, backend


def _site_policy(profile, compute):
    unused_kind, backend = _run_backend(profile)
    return backend["validate_policy"](profile, compute)


def _content_sha256(profile, path):
    """Fingerprint an executable on its execution Site, locally or over SSH."""
    digest = site_file_sha256(profile, path)
    if not digest:
        raise PlanError("cannot fingerprint executable on execution Site: %s" % path)
    return digest


def _operation_id(seed):
    return "op-" + canonical_hash(seed).split(":", 1)[1][:16]


def execution_roots(store, profile, case):
    """Execution roots for build/run/staging/analysis derivation.

    Profiles declaring ``site_root`` use the Computation Site tree
    ``<site_root>/projects/<project-slug>/{builds,runs,staging,analysis}``
    and are marked ``site-tree``; legacy profiles (no site_root) keep their
    independent roots and are marked ``legacy-roots``.  Returns
    ``(roots, layout)``; every value may be None for the caller's missing-
    root check.  Old Locators recorded under either layout stay readable —
    this only decides where *new* resources land."""
    site_root = profile.get("site_root", "")
    if site_root:
        slug = ""
        if case.get("project_uid"):
            try:
                slug = store.get_project(case["project_uid"])["slug"]
            except StoreError:
                slug = ""
        if not slug:
            slug = os.path.basename(case.get("project_root") or "") \
                or case["case_uid"]
        base = os.path.join(site_root, "projects", slug)
        return ({
            "build_root": os.path.join(base, "builds"),
            "run_root": os.path.join(base, "runs"),
            "staging_root": os.path.join(base, "staging"),
            "analysis_root": os.path.join(base, "analysis"),
        }, "site-tree")
    roots = profile.get("roots", {})
    return ({
        "build_root": roots.get("build_root"),
        "run_root": roots.get("run_root"),
        "staging_root": roots.get("staging_root"),
        "analysis_root": roots.get("analysis_root"),
    }, "legacy-roots")


def merged_execution_profile(store, profile, case):
    """A profile copy whose roots are filled from ``execution_roots`` so all
    downstream derivation (build_root checks, ExecutorClient staging,
    inventory staging) works unchanged under either layout."""
    roots, layout = execution_roots(store, profile, case)
    merged = dict(profile.get("roots", {}))
    for key, value in roots.items():
        if value:
            merged[key] = value
    profile = dict(profile)
    profile["roots"] = merged
    return profile, layout


def case_path_segment(layout, case):
    """Path segment below runs/staging: the human-readable case slug in the
    site tree, the stable case_uid under legacy roots."""
    return case["case_id"] if layout == "site-tree" else case["case_uid"]


def derive_run_paths(case_uid, site_id, roots, scheduler_kind, source_id,
                     input_sha256, executable, build_id, compute,
                     case_segment=None):
    """Derive the content-addressed run identity and every path a run
    Operation touches from the run seed and the Site roots."""
    seed = {
        "case_uid": case_uid, "source_id": source_id,
        "input_sha256": input_sha256,
        "site_id": site_id, "executable": executable, "build_id": build_id,
        "compute": compute,
    }
    run_id = "run-" + canonical_hash(seed).split(":", 1)[1][:16]
    operation_id = _operation_id(seed)
    segment = case_segment or case_uid
    run_root = os.path.join(roots["run_root"], segment, run_id)
    staging_root = os.path.join(roots["staging_root"], segment, operation_id)
    return {
        "seed": seed,
        "run_id": run_id,
        "operation_id": operation_id,
        "run_root": run_root,
        "staging_root": staging_root,
        "manifest": os.path.join(run_root, "run-manifest.json"),
        "submit_script": os.path.join(
            run_root, "run.sbatch" if scheduler_kind == "slurm" else "run.sh"),
        "staged_input": os.path.join(staging_root, "payloads", "input.toml"),
        "prepare_receipt": os.path.join(staging_root, "receipts", "run-prepare.json"),
    }


def _source_identity(source_root, controller_artifacts=None):
    source_root = absolute(source_root)
    manifest = source_manifest(source_root)
    ignored = set()
    for path in controller_artifacts or []:
        path = absolute(path)
        try:
            if os.path.commonpath([path, source_root]) == source_root:
                ignored.add(os.path.relpath(path, source_root))
        except ValueError:
            pass
    files = [item for item in manifest.get("files", []) if item.get("path") not in ignored]
    identity = {"base_revision": manifest.get("base_revision", {}), "files": files}
    return {
        "snapshot_id": canonical_hash(identity).split(":", 1)[1],
        "base_revision": identity["base_revision"],
        "files": len(files),
    }, sorted(ignored)


def _simulation_confirmation(input_path):
    """Hard gate: the simulation parameter confirmation recorded by
    pgen_preflight.py confirm must exist and match the current input bytes."""
    question = (
        "show the parameter card to the user and record confirmation with "
        "pgen_preflight.py confirm %s --by <actor>" % input_path
    )
    record, matches = load_simulation_confirmation(input_path)
    if record is None:
        raise PlanError(
            "simulation parameters have not been confirmed",
            "needs_decision",
            [{"field": "input", "question": question}],
        )
    if not matches:
        raise PlanError(
            "simulation parameters changed since they were confirmed",
            "needs_decision",
            [{"field": "input", "question": question}],
        )
    return record


def case_resolution_plan_error(exc):
    """Uniform needs_decision mapping for Case-resolution failures shared by
    facts._resolve_case and record._require_case."""
    question = ("select the case with --case <%s>" % "|".join(exc.cases)
                if exc.cases
                else "create the case with entityctl case init")
    return PlanError(
        str(exc), "needs_decision",
        [{"field": "case", "question": question}],
    )


def _resolve_case(store, project_root, goal, case_slug=None):
    try:
        return store.resolve_project(project_root, case_slug), False
    except CaseResolutionError as exc:
        # Only a missing Project (or a Project without any case) auto-creates
        # on first run; an ambiguous or unknown --case selection is a user
        # decision, never a silent new Case.
        if exc.reason not in ("no_project", "no_cases"):
            raise case_resolution_plan_error(exc)
        source_site = _source_site(store, project_root)
        case_uid = "case-" + canonical_hash({"project_root": project_root}).split(":", 1)[1][:16]
        case = {
            "case_uid": case_uid,
            "case_id": goal.get("case_id") or os.path.basename(project_root),
            "project_root": project_root,
            "source": {
                "authority": {"site_id": source_site, "path": project_root},
                "transfer_policy": goal.get("source_mode", "snapshot"),
                "revision": _git_revision(project_root),
            },
            "current": {"source_id": "", "build_id": "", "run_id": "",
                        "active_run": None, "data_id": "", "analysis_id": ""},
            "identities": {}, "legacy": {},
        }
        return case, True


def require_verified_checkpoint(checkpoint):
    """Hard gate: a build Goal only registers checkpoints that env-build has
    verified (compatibility pass) and whose parameters were confirmed."""
    compatibility = checkpoint.get("compatibility", {})
    if not isinstance(compatibility, dict) or compatibility.get("status") != "pass":
        raise PlanError(
            "build checkpoint compatibility is not pass",
            "needs_decision",
            [{"field": "checkpoint",
              "question": "run entity_compat.py and resolve the failures"}],
        )
    parameters = checkpoint.get("decisions", {}).get("parameters", {})
    if not isinstance(parameters, dict) or not parameters.get("digest"):
        raise PlanError(
            "build parameters have not been confirmed",
            "needs_decision",
            [{"field": "checkpoint",
              "question": "record build parameter confirmation with "
                          "entity_checkpoint.py confirm"}],
        )
