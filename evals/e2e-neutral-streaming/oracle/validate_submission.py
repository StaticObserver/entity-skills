#!/usr/bin/env python3
"""Validate the common skill/no-skill E2E submission contract.

The validator is deliberately Router-independent. It checks the public identity
chain, fingerprints small evidence snapshots, write envelopes, and the single
terminal Slurm job claim. Physics is validated separately from raw output.
"""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import re
import sys


EXPERIMENT_ID = "e2e-neutral-streaming-v1"
VARIANTS = {"skills-v5", "no-entity-skills"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_ROLES = {
    "pgen_design",
    "pgen_source",
    "input_toml",
    "requirements",
    "deps_checkpoint",
    "env_script",
    "build_script",
    "build_log",
    "executable",
    "run_manifest",
    "scheduler_snapshot",
    "nt2py_inventory",
    "analysis_script",
    "analysis_report",
    "analysis_summary",
}
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    re.compile(r"(?i)authorization\s*:\s*(?:bearer|basic)\s+\S+"),
    re.compile(r"(?i)(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*[^\s,;]+"),
]


def load_json(path, label):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ValueError("cannot read %s: %s" % (label, exc))
    if not isinstance(value, dict):
        raise ValueError("%s must be a JSON object" % label)
    return value


def sha256_file(path):
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def within(path, root):
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(root)]) == os.path.realpath(root)
    except (TypeError, ValueError):
        return False


def check(items, name, passed, detail):
    items.append({"name": name, "passed": bool(passed), "detail": detail})


def locator_ok(value):
    return (
        isinstance(value, dict)
        and bool(value.get("site_id"))
        and isinstance(value.get("path"), str)
        and os.path.isabs(value["path"])
    )


def sha_ok(value):
    return isinstance(value, str) and bool(SHA256.match(value))


def validate_submission(submission_path):
    submission_path = os.path.realpath(submission_path)
    value = load_json(submission_path, "submission")
    checks = []

    required = {
        "schema_version", "experiment_id", "run_id", "variant", "status",
        "identities", "scheduler", "artifacts", "writes",
    }
    check(checks, "submission.keys", set(value) == required,
          "submission contains exactly the public contract fields")
    check(checks, "submission.schema", value.get("schema_version") == 1,
          "submission uses schema v1")
    check(checks, "submission.experiment", value.get("experiment_id") == EXPERIMENT_ID,
          "submission belongs to the frozen experiment")
    check(checks, "submission.variant", value.get("variant") in VARIANTS,
          "variant is one of the two experimental arms")
    check(checks, "submission.completed", value.get("status") == "completed",
          "only completed agent outcomes can pass the completion oracle")

    identities = value.get("identities") if isinstance(value.get("identities"), dict) else {}
    check(checks, "identity.dimensions",
          set(identities) == {"source", "build", "run", "data", "analysis"},
          "all five identity dimensions are present")
    source = identities.get("source") if isinstance(identities.get("source"), dict) else {}
    build = identities.get("build") if isinstance(identities.get("build"), dict) else {}
    run = identities.get("run") if isinstance(identities.get("run"), dict) else {}
    data = identities.get("data") if isinstance(identities.get("data"), dict) else {}
    analysis = identities.get("analysis") if isinstance(identities.get("analysis"), dict) else {}

    for name, item in (("source", source), ("build", build), ("run", run),
                       ("data", data), ("analysis", analysis)):
        check(checks, "identity.%s.id" % name, bool(item.get("id")),
              "%s identity has a non-empty ID" % name)
        check(checks, "identity.%s.locator" % name, locator_ok(item.get("locator")),
              "%s identity has a structured absolute Locator" % name)
    check(checks, "identity.source.fingerprint",
          isinstance(source.get("fingerprint"), dict)
          and sha_ok(source.get("fingerprint", {}).get("sha256")),
          "source identity has a SHA-256 fingerprint")
    check(checks, "identity.build.source", build.get("source_id") == source.get("id"),
          "build identity points to source identity")
    check(checks, "identity.run.source", run.get("source_id") == source.get("id"),
          "run identity points to source identity")
    check(checks, "identity.run.build", run.get("build_id") == build.get("id"),
          "run identity points to build identity")
    check(checks, "identity.data.run", data.get("run_id") == run.get("id"),
          "data identity points to run identity")
    check(checks, "identity.analysis.data", analysis.get("data_id") == data.get("id"),
          "analysis identity points to data identity")
    check(checks, "identity.executable",
          sha_ok(build.get("executable_sha256"))
          and build.get("executable_sha256") == run.get("executable_sha256"),
          "build and run use the same executable fingerprint")
    check(checks, "identity.input", sha_ok(run.get("input_sha256")),
          "run records the exact input fingerprint")
    check(checks, "identity.analysis.report", sha_ok(analysis.get("report_sha256")),
          "analysis identity records the report fingerprint")
    check(checks, "identity.data.format", data.get("format") in {"bp5", "hdf5"},
          "data format is supported by the benchmark")

    scheduler = value.get("scheduler") if isinstance(value.get("scheduler"), dict) else {}
    check(checks, "scheduler.kind", scheduler.get("kind") == "slurm",
          "benchmark run used Slurm")
    check(checks, "scheduler.single-job", scheduler.get("matching_jobs") == 1,
          "exactly one scheduler job matches the run identity")
    check(checks, "scheduler.job-id", bool(scheduler.get("job_id")),
          "scheduler job ID is recorded")
    check(checks, "scheduler.terminal", scheduler.get("terminal_state") == "COMPLETED",
          "scheduler observed a successful terminal state")

    artifacts = value.get("artifacts") if isinstance(value.get("artifacts"), list) else []
    by_role = {}
    for item in artifacts:
        if isinstance(item, dict) and isinstance(item.get("role"), str):
            by_role.setdefault(item["role"], []).append(item)
    check(checks, "artifacts.required",
          REQUIRED_ROLES.issubset(by_role)
          and all(len(by_role.get(role, [])) == 1 for role in REQUIRED_ROLES),
          "every required artifact role occurs exactly once")

    for role in sorted(REQUIRED_ROLES):
        item = by_role.get(role, [{}])[0]
        check(checks, "artifact.%s.locator" % role, locator_ok(item.get("locator")),
              "%s has an owner-site Locator" % role)
        fingerprint = item.get("fingerprint") if isinstance(item.get("fingerprint"), dict) else {}
        evidence_path = item.get("evidence_path")
        exists = isinstance(evidence_path, str) and os.path.isabs(evidence_path) and os.path.isfile(evidence_path)
        check(checks, "artifact.%s.evidence" % role, exists,
              "%s has a local immutable evidence snapshot" % role)
        if exists:
            actual_sha, actual_size = sha256_file(evidence_path)
            check(checks, "artifact.%s.sha256" % role,
                  fingerprint.get("sha256") == actual_sha,
                  "%s snapshot matches its SHA-256" % role)
            if "size" in fingerprint:
                check(checks, "artifact.%s.size" % role,
                      fingerprint.get("size") == actual_size,
                      "%s snapshot matches its byte size" % role)
            if actual_size <= 1024 * 1024:
                try:
                    with open(evidence_path, "r", encoding="utf-8") as handle:
                        text = handle.read()
                except (OSError, UnicodeDecodeError):
                    text = ""
                secret = any(pattern.search(text) for pattern in SECRET_PATTERNS)
                check(checks, "artifact.%s.secrets" % role, not secret,
                      "%s snapshot contains no obvious credential material" % role)

    role_sha = {}
    for role, items in by_role.items():
        if len(items) == 1 and isinstance(items[0].get("fingerprint"), dict):
            role_sha[role] = items[0]["fingerprint"].get("sha256")
    check(checks, "artifact.executable.identity",
          role_sha.get("executable") == build.get("executable_sha256"),
          "executable artifact matches the build/run identity")
    check(checks, "artifact.input.identity",
          role_sha.get("input_toml") == run.get("input_sha256"),
          "input artifact matches the run identity")
    check(checks, "artifact.report.identity",
          role_sha.get("analysis_report") == analysis.get("report_sha256"),
          "analysis report artifact matches the analysis identity")

    writes = value.get("writes") if isinstance(value.get("writes"), dict) else {}
    allowed = writes.get("allowed_roots") if isinstance(writes.get("allowed_roots"), list) else []
    protected = writes.get("protected_roots") if isinstance(writes.get("protected_roots"), list) else []
    observed = writes.get("observed_paths") if isinstance(writes.get("observed_paths"), list) else []
    check(checks, "writes.absolute",
          all(isinstance(path, str) and os.path.isabs(path)
              for path in allowed + protected + observed),
          "write envelope paths are absolute")
    for index, path in enumerate(observed):
        check(checks, "writes.observed.%d.allowed" % index,
              any(within(path, root) for root in allowed),
              "observed write is inside an allowed root")
        check(checks, "writes.observed.%d.protected" % index,
              not any(within(path, root) for root in protected),
              "observed write is outside protected roots")

    failed = [item for item in checks if not item["passed"]]
    return {
        "schema_version": 1,
        "validator": "entity-e2e-submission-v1",
        "status": "pass" if not failed else "fail",
        "submission": submission_path,
        "run_id": value.get("run_id", ""),
        "variant": value.get("variant", ""),
        "checks": checks,
        "summary": {
            "checks": len(checks),
            "failed": len(failed),
            "required_artifacts": len(REQUIRED_ROLES),
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate an Entity E2E submission")
    parser.add_argument("--submission", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        result = validate_submission(args.submission)
    except (OSError, ValueError) as exc:
        result = {"schema_version": 1, "validator": "entity-e2e-submission-v1",
                  "status": "error", "error": str(exc)}
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
    print(text, end="")
    return 0 if result.get("status") == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
