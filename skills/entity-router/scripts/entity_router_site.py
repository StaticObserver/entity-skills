#!/usr/bin/env python3
"""Manage Entity Router sites, probes, and immutable source materialization."""

from __future__ import print_function

import argparse
import json
import os
import shlex
import shutil
import sys
import tarfile
import tempfile
import uuid

from entity_router_common import (
    RouterError,
    canonical_locator,
    copy_snapshot_local,
    ensure_home,
    list_site_profiles,
    load_site_profile,
    now_utc,
    parse_locator,
    probe_locator,
    probe_locators_batch,
    router_home,
    run_command,
    run_on_site,
    save_site_profile,
    source_manifest,
    verify_snapshot,
)


def emit(value):
    print(json.dumps(value, indent=2, sort_keys=True))


def command_add(args):
    roots = {}
    for name in ["source", "build", "run", "deps", "staging", "analysis"]:
        value = getattr(args, "%s_root" % name)
        if value:
            roots["%s_root" % name] = (
                os.path.realpath(os.path.abspath(os.path.expanduser(value)))
                if args.transport == "local" else os.path.normpath(value)
            )
    profile = {
        "schema_version": 1,
        "site_id": args.site_id,
        "display_name": args.display_name or args.site_id,
        "transport": {"kind": args.transport, "ssh_alias": args.ssh_alias or ""},
        "scheduler": {"kind": args.scheduler},
        "roots": roots,
        "shared_mappings": [],
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    for raw in args.shared_map:
        if "=" not in raw or "|" not in raw:
            raise RouterError("--shared-map must use PEER_SITE=THIS_ROOT|PEER_ROOT")
        peer, mapping = raw.split("=", 1)
        local_root, peer_root = mapping.split("|", 1)
        if not peer or not local_root.startswith("/") or not peer_root.startswith("/"):
            raise RouterError("shared mapping requires peer site and two absolute roots")
        profile["shared_mappings"].append({
            "peer_site_id": peer,
            "this_root": os.path.normpath(local_root),
            "peer_root": os.path.normpath(peer_root),
        })
    path = save_site_profile(args.router_home, profile)
    return {"ok": True, "path": path, "profile": profile}


def command_list(args):
    return {"ok": True, "sites": list_site_profiles(args.router_home)}


def command_show(args):
    return {"ok": True, "profile": load_site_profile(args.router_home, args.site_id)}


def command_verify(args):
    profile = load_site_profile(args.router_home, args.site_id)
    issues = []
    if profile["transport"]["kind"] == "ssh":
        code, stdout, stderr = run_on_site(profile, ["printf", "site-ok"])
        if code != 0 or stdout != "site-ok":
            issues.append(stderr.strip() or "SSH probe failed")
    for name, path in profile.get("roots", {}).items():
        try:
            evidence = probe_locator(args.router_home, "%s:%s" % (args.site_id, path))
            if evidence["kind"] == "missing":
                issues.append("missing %s: %s" % (name, path))
        except RouterError as exc:
            issues.append(str(exc))
    return {"ok": not issues, "site_id": args.site_id, "issues": issues}


def command_probe(args):
    return {"ok": True, "evidence": probe_locator(args.router_home, args.locator, args.kind)}


def command_probe_batch(args):
    items = [{"locator": value, "kind": args.kind} for value in args.locator]
    return {
        "ok": True,
        "site_id": args.site_id,
        "remote_calls": 0 if load_site_profile(args.router_home, args.site_id)["transport"]["kind"] == "local" else 1,
        "evidence": probe_locators_batch(args.router_home, args.site_id, items),
    }


def command_scheduler_probe(args):
    profile = load_site_profile(args.router_home, args.site_id)
    kind = profile.get("scheduler", {}).get("kind", "none")
    if kind == "slurm":
        code, stdout, stderr = run_on_site(profile, ["squeue", "-h", "-j", args.job_id, "-o", "%T"])
        if code != 0:
            raise RouterError("scheduler probe failed: %s" % (stderr.strip() or stdout.strip()))
        state = stdout.strip().splitlines()[0] if code == 0 and stdout.strip() else "NOT_FOUND"
    elif kind == "pbs":
        code, stdout, stderr = run_on_site(profile, ["qstat", "-f", args.job_id])
        if code != 0:
            raise RouterError("scheduler probe failed: %s" % (stderr.strip() or stdout.strip()))
        state = "NOT_FOUND"
        if code == 0:
            for line in stdout.splitlines():
                if "job_state" in line and "=" in line:
                    state = line.split("=", 1)[1].strip()
                    break
    else:
        raise RouterError("scheduler probe requires a slurm or pbs site profile")
    return {
        "ok": True,
        "evidence": {
            "locator": {"site_id": args.site_id, "path": "/scheduler/jobs/%s" % args.job_id},
            "kind": "scheduler",
            "fingerprint": {"scheduler": kind, "job_id": args.job_id, "state": state},
            "observed_at": now_utc(),
            "observer_site": "controller",
        },
    }


def _shared_mapping_matches(profile, other_site, this_locator, other_locator):
    for mapping in profile.get("shared_mappings", []):
        if mapping.get("peer_site_id") != other_site:
            continue
        try:
            this_rel = os.path.relpath(this_locator["path"], mapping["this_root"])
            other_rel = os.path.relpath(other_locator["path"], mapping["peer_root"])
        except (KeyError, ValueError):
            continue
        if not this_rel.startswith(os.pardir) and this_rel == other_rel:
            return True
    return False


def _git_materialize_local(repository, commit, target):
    if os.path.exists(target):
        code, stdout, unused = run_command(["git", "-C", target, "rev-parse", "HEAD"])
        if code == 0 and stdout.strip() == commit:
            status_code, status, unused = run_command(["git", "-C", target, "status", "--porcelain"])
            if status_code == 0 and not status.strip():
                return
            raise RouterError("git-ref target exists at requested commit but is dirty")
        raise RouterError("git-ref target already exists at another revision")
    parent = os.path.dirname(target)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    code, unused, stderr = run_command(["git", "clone", "--no-checkout", repository, target])
    if code != 0:
        raise RouterError("git clone failed: %s" % stderr.strip())
    code, unused, stderr = run_command(["git", "-C", target, "checkout", "--detach", commit])
    if code != 0:
        shutil.rmtree(target, ignore_errors=True)
        raise RouterError("git checkout failed: %s" % stderr.strip())


def _snapshot_archive(source, manifest):
    handle, archive = tempfile.mkstemp(prefix="entity-snapshot-", suffix=".tar")
    os.close(handle)
    manifest_file = archive + ".json"
    try:
        with open(manifest_file, "w") as output:
            json.dump(manifest, output, indent=2, sort_keys=True)
            output.write("\n")
        with tarfile.open(archive, "w") as bundle:
            for entry in manifest["files"]:
                bundle.add(os.path.join(source, entry["path"]), arcname=entry["path"], recursive=False)
            bundle.add(manifest_file, arcname="snapshot-manifest.json", recursive=False)
        return archive, manifest_file
    except Exception:
        for path in [archive, manifest_file]:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise


def _safe_extract_local(archive, destination):
    with tarfile.open(archive, "r") as bundle:
        for member in bundle.getmembers():
            if os.path.isabs(member.name) or ".." in member.name.split("/"):
                raise RouterError("unsafe snapshot archive path")
        bundle.extractall(destination)


def _remote_source_snapshot(profile, source):
    staging = profile.get("roots", {}).get("staging_root")
    if not staging:
        raise RouterError("remote source snapshot requires source-site staging_root")
    alias = profile["transport"]["ssh_alias"]
    helper_local = os.path.join(os.path.dirname(__file__), "entity_router_remote.py")
    helper_remote = os.path.join(staging, ".entity-router-remote-v3.py")
    remote_archive = os.path.join(staging, ".snapshot-%s.tar" % uuid.uuid4().hex)
    code, unused, stderr = run_on_site(profile, ["mkdir", "-p", staging])
    if code != 0:
        raise RouterError("cannot prepare remote source staging: %s" % stderr.strip())
    code, unused, stderr = run_command([
        "scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        helper_local, "%s:%s" % (alias, shlex.quote(helper_remote))
    ])
    if code != 0:
        raise RouterError("cannot stage remote snapshot helper: %s" % stderr.strip())
    code, stdout, stderr = run_on_site(profile, [
        "python3", helper_remote, "snapshot-archive",
        "--source", source, "--archive", remote_archive,
    ])
    if code != 0:
        raise RouterError("remote source snapshot failed: %s" % (stderr.strip() or stdout.strip()))
    try:
        manifest = json.loads(stdout)
    except ValueError:
        raise RouterError("remote source snapshot returned invalid manifest JSON")
    handle, local_archive = tempfile.mkstemp(prefix="entity-remote-source-", suffix=".tar")
    os.close(handle)
    extracted = tempfile.mkdtemp(prefix="entity-remote-source-")
    try:
        code, unused, stderr = run_command([
            "scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "%s:%s" % (alias, shlex.quote(remote_archive)), local_archive
        ])
        if code != 0:
            raise RouterError("cannot fetch remote source snapshot: %s" % stderr.strip())
        _safe_extract_local(local_archive, extracted)
        verified = verify_snapshot(extracted)
        if verified.get("snapshot_id") != manifest.get("snapshot_id"):
            raise RouterError("fetched remote snapshot ID differs from source manifest")
        return extracted, manifest, local_archive
    except Exception:
        shutil.rmtree(extracted, ignore_errors=True)
        try:
            os.unlink(local_archive)
        except OSError:
            pass
        raise
    finally:
        run_on_site(profile, ["rm", "-f", remote_archive])


def _copy_snapshot_ssh(profile, target_root, source, manifest):
    snapshot_id = manifest["snapshot_id"]
    destination = os.path.join(target_root, snapshot_id)
    alias = profile["transport"]["ssh_alias"]
    archive, manifest_file = _snapshot_archive(source, manifest)
    remote_archive = os.path.join(target_root, ".%s.tar" % snapshot_id)
    verifier = (
        "import hashlib,json,os,shutil,sys,tarfile; "
        "a,r,d,s=sys.argv[1:]; "
        "os.makedirs(r) if not os.path.isdir(r) else None; "
        "tmp=d+'.tmp-'+str(os.getpid()); "
        "\nif os.path.exists(d):\n"
        " m=json.load(open(os.path.join(d,'snapshot-manifest.json')));\n"
        " assert m.get('snapshot_id')==s, 'existing snapshot ID mismatch';\n"
        "else:\n"
        " os.makedirs(tmp);\n"
        " t=tarfile.open(a);\n"
        " members=t.getmembers();\n"
        " assert all(not os.path.isabs(x.name) and '..' not in x.name.split('/') for x in members), 'unsafe archive path';\n"
        " t.extractall(tmp); t.close();\n"
        " m=json.load(open(os.path.join(tmp,'snapshot-manifest.json')));\n"
        " assert m.get('snapshot_id')==s, 'snapshot ID mismatch';\n"
        " [(_ for _ in ()).throw(AssertionError('file hash mismatch: '+e['path'])) for e in m['files'] if hashlib.sha256(open(os.path.join(tmp,e['path']),'rb').read()).hexdigest()!=e['sha256']];\n"
        " os.rename(tmp,d);\n"
        "\nfor e in m['files']:\n"
        " p=os.path.join(d,e['path']); assert os.path.isfile(p), 'missing file: '+e['path']; assert hashlib.sha256(open(p,'rb').read()).hexdigest()==e['sha256'], 'file hash mismatch: '+e['path'];\n"
        "os.unlink(a) if os.path.exists(a) else None; print(json.dumps({'snapshot_id':s,'destination':d}))"
    )
    try:
        code, unused, stderr = run_on_site(profile, ["mkdir", "-p", target_root])
        if code != 0:
            raise RouterError("cannot create remote snapshot root: %s" % stderr.strip())
        code, unused, stderr = run_command([
            "scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            archive, "%s:%s" % (alias, shlex.quote(remote_archive)),
        ])
        if code != 0:
            raise RouterError("cannot transfer snapshot archive: %s" % stderr.strip())
        code, stdout, stderr = run_on_site(profile, [
            "python3", "-c", verifier,
            remote_archive, target_root, destination, snapshot_id,
        ])
        if code != 0:
            raise RouterError("remote snapshot verification failed: %s" % (stderr.strip() or stdout.strip()))
        return destination
    finally:
        cleanup = "rm -f %s; rm -rf %s.tmp-*" % (
            shlex.quote(remote_archive), shlex.quote(destination)
        )
        run_on_site(profile, ["sh", "-c", cleanup])
        for path in [archive, manifest_file]:
            try:
                os.unlink(path)
            except OSError:
                pass


def command_materialize(args):
    source = parse_locator(args.source) if args.source else None
    target = canonical_locator(args.router_home, args.target)
    if source:
        source = canonical_locator(args.router_home, source)
    target_profile = load_site_profile(args.router_home, target["site_id"])
    if args.mode == "snapshot":
        if not source:
            raise RouterError("snapshot mode requires --source")
        source_profile = load_site_profile(args.router_home, source["site_id"])
        cleanup_dir = ""
        cleanup_archive = ""
        if source_profile["transport"]["kind"] == "local":
            snapshot_source = source["path"]
            manifest = source_manifest(snapshot_source)
        else:
            snapshot_source, manifest, cleanup_archive = _remote_source_snapshot(
                source_profile, source["path"]
            )
            cleanup_dir = snapshot_source
        try:
            if target_profile["transport"]["kind"] == "local":
                destination = copy_snapshot_local(snapshot_source, target["path"], manifest)
                verified = verify_snapshot(destination)
            else:
                destination = _copy_snapshot_ssh(target_profile, target["path"], snapshot_source, manifest)
                verified = manifest
        finally:
            if cleanup_dir:
                shutil.rmtree(cleanup_dir, ignore_errors=True)
            if cleanup_archive:
                try:
                    os.unlink(cleanup_archive)
                except OSError:
                    pass
        return {
            "ok": True,
            "mode": "snapshot",
            "snapshot_id": verified["snapshot_id"],
            "materialized": {"site_id": target["site_id"], "path": destination},
            "manifest_sha256": verified["snapshot_id"],
        }
    if args.mode == "git-ref":
        if not args.repository or not args.commit:
            raise RouterError("git-ref mode requires --repository and --commit")
        if target_profile["transport"]["kind"] == "local":
            _git_materialize_local(args.repository, args.commit, target["path"])
        else:
            script = (
                "set -eu; if test -d {target}/.git; then "
                "test \"$(git -C {target} rev-parse HEAD)\" = {commit}; "
                "test -z \"$(git -C {target} status --porcelain)\"; "
                "else test ! -e {target}; mkdir -p {parent}; "
                "git clone --no-checkout {repo} {target}; "
                "git -C {target} checkout --detach {commit}; fi"
            ).format(
                target=shlex.quote(target["path"]),
                parent=shlex.quote(os.path.dirname(target["path"])),
                repo=shlex.quote(args.repository),
                commit=shlex.quote(args.commit),
            )
            code, unused, stderr = run_on_site(target_profile, ["sh", "-c", script])
            if code != 0:
                raise RouterError("remote git materialization failed: %s" % stderr.strip())
        evidence = probe_locator(args.router_home, target, "git")
        if evidence.get("fingerprint", {}).get("commit") != args.commit:
            raise RouterError("materialized git commit does not match requested commit")
        return {"ok": True, "mode": "git-ref", "materialized": target, "evidence": evidence}
    if args.mode in {"shared", "external"}:
        if not source:
            raise RouterError("%s mode requires --source" % args.mode)
        if args.mode == "shared":
            source_profile = load_site_profile(args.router_home, source["site_id"])
            declared = (
                _shared_mapping_matches(source_profile, target["site_id"], source, target)
                or _shared_mapping_matches(target_profile, source["site_id"], target, source)
            )
            if not declared:
                raise RouterError("shared mode requires a declared matching filesystem mapping")
        left = probe_locator(args.router_home, source, "git")
        right = probe_locator(args.router_home, target, "git")
        if left["kind"] == "missing" or right["kind"] == "missing":
            raise RouterError("source or target locator is missing")
        if left.get("fingerprint") != right.get("fingerprint"):
            raise RouterError("source and target revisions differ")
        if left.get("fingerprint", {}).get("dirty"):
            raise RouterError("dirty shared/external replicas require immutable snapshot verification")
        return {"ok": True, "mode": args.mode, "materialized": target, "evidence": right}
    raise RouterError("unsupported materialization mode: %s" % args.mode)


def command_verify_snapshot(args):
    manifest = verify_snapshot(args.path)
    return {"ok": True, "snapshot_id": manifest["snapshot_id"], "files": len(manifest["files"])}


def build_parser():
    parser = argparse.ArgumentParser(description="Entity Router site controller")
    parser.add_argument("--router-home", default=router_home())
    sub = parser.add_subparsers(dest="command")

    add = sub.add_parser("add")
    add.add_argument("--site-id", required=True)
    add.add_argument("--display-name")
    add.add_argument("--transport", choices=["local", "ssh"], required=True)
    add.add_argument("--ssh-alias")
    add.add_argument("--scheduler", choices=["none", "slurm", "pbs", "custom"], default="none")
    for name in ["source", "build", "run", "deps", "staging", "analysis"]:
        add.add_argument("--%s-root" % name)
    add.add_argument("--shared-map", action="append", default=[],
                     help="PEER_SITE=THIS_ROOT|PEER_ROOT")
    add.set_defaults(func=command_add)

    listing = sub.add_parser("list")
    listing.set_defaults(func=command_list)
    show = sub.add_parser("show")
    show.add_argument("--site-id", required=True)
    show.set_defaults(func=command_show)
    verify = sub.add_parser("verify")
    verify.add_argument("--site-id", required=True)
    verify.set_defaults(func=command_verify)
    probe = sub.add_parser("probe")
    probe.add_argument("--locator", required=True)
    probe.add_argument("--kind", choices=["auto", "git"], default="auto")
    probe.set_defaults(func=command_probe)
    batch = sub.add_parser("probe-batch")
    batch.add_argument("--site-id", required=True)
    batch.add_argument("--locator", action="append", required=True)
    batch.add_argument("--kind", choices=["auto", "git"], default="auto")
    batch.set_defaults(func=command_probe_batch)
    scheduler = sub.add_parser("scheduler-probe")
    scheduler.add_argument("--site-id", required=True)
    scheduler.add_argument("--job-id", required=True)
    scheduler.set_defaults(func=command_scheduler_probe)
    materialize = sub.add_parser("materialize")
    materialize.add_argument("--mode", choices=["git-ref", "snapshot", "shared", "external"], required=True)
    materialize.add_argument("--source")
    materialize.add_argument("--target", required=True)
    materialize.add_argument("--repository")
    materialize.add_argument("--commit")
    materialize.set_defaults(func=command_materialize)
    snapshot = sub.add_parser("verify-snapshot")
    snapshot.add_argument("--path", required=True)
    snapshot.set_defaults(func=command_verify_snapshot)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.error("a command is required")
    args.router_home = ensure_home(args.router_home)
    try:
        payload = args.func(args)
        emit(payload)
        return 0 if payload.get("ok", True) else 2
    except (RouterError, OSError, ValueError) as exc:
        emit({"ok": False, "error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
