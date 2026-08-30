from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from . import __version__
from .analysis import record_analysis
from .build import prepare_build, run_build, show_build_site
from .check import check_workspace
from .errors import EntityError
from .migrate import migrate_legacy
from .objects import (
    add_build,
    add_pgen,
    add_run,
    add_source,
    load_build,
    load_pgen,
    load_run,
    load_source,
)
from .paths import Workspace, init_project
from .records import load_json
from .run import attempt_status, data_summary, prepare_attempt, submit_attempt
from .site import SiteOps, add_deps, add_site, init_site, load_deps, load_site


def _json_value(value: str | None, *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not value:
        return dict(default or {})
    if value.startswith("@"):
        return load_json(Path(value[1:]).expanduser().resolve())
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise EntityError(f"invalid JSON argument: {exc}", code="invalid_json") from exc
    if not isinstance(parsed, dict):
        raise EntityError("JSON argument must be an object", code="invalid_json")
    return parsed


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))


def _workspace(args: argparse.Namespace) -> Workspace:
    return Workspace.discover(args.workspace)


def _list_records(root: Path, filename: str) -> list[dict[str, Any]]:
    return [load_json(path) for path in sorted(root.glob(f"*/{filename}"))]


def cmd_workspace_init(args: argparse.Namespace) -> dict[str, Any]:
    workspace = Workspace.init(Path(args.path), args.id)
    return {"ok": True, "workspace": str(workspace.root), "record": workspace.metadata()}


def cmd_workspace_show(args: argparse.Namespace) -> dict[str, Any]:
    workspace = _workspace(args)
    return {"ok": True, "workspace": str(workspace.root), "record": workspace.metadata()}


def cmd_project_init(args: argparse.Namespace) -> dict[str, Any]:
    path = init_project(_workspace(args), args.project)
    return {"ok": True, "project": args.project, "path": str(path)}


def cmd_project_show(args: argparse.Namespace) -> dict[str, Any]:
    workspace = _workspace(args)
    root = workspace.require_project(args.project)
    return {
        "ok": True,
        "record": load_json(root / "project.json"),
        "sources": len(list((root / "sources").glob("*/source.json"))),
        "pgens": len(list((root / "pgens").glob("*/pgen.json"))),
        "builds": len(list((root / "builds").glob("*/build.json"))),
        "runs": len(list((root / "builds").glob("*/runs/*/run.json"))),
    }


def cmd_site_add(args: argparse.Namespace) -> dict[str, Any]:
    return {"ok": True, "record": add_site(_workspace(args), load_json(Path(args.config).resolve()))}


def cmd_site_init(args: argparse.Namespace) -> dict[str, Any]:
    return {"ok": True, "record": init_site(_workspace(args), args.site)}


def cmd_site_show(args: argparse.Namespace) -> dict[str, Any]:
    return {"ok": True, "record": load_site(_workspace(args), args.site)}


def cmd_site_list(args: argparse.Namespace) -> dict[str, Any]:
    workspace = _workspace(args)
    return {"ok": True, "items": [load_json(path) for path in sorted((workspace.root / "sites").glob("*.json"))]}


def cmd_source_add(args: argparse.Namespace) -> dict[str, Any]:
    checkout = Path(args.checkout) if args.checkout else None
    record = add_source(_workspace(args), args.project, args.id, args.repository, args.commit, checkout)
    return {"ok": True, "record": record}


def cmd_source_show(args: argparse.Namespace) -> dict[str, Any]:
    return {"ok": True, "record": load_source(_workspace(args), args.project, args.id)}


def cmd_source_list(args: argparse.Namespace) -> dict[str, Any]:
    workspace = _workspace(args)
    return {"ok": True, "items": _list_records(workspace.require_project(args.project) / "sources", "source.json")}


def cmd_pgen_add(args: argparse.Namespace) -> dict[str, Any]:
    record = add_pgen(_workspace(args), args.project, args.id, Path(args.from_dir), args.entry, args.name)
    return {"ok": True, "record": record}


def cmd_pgen_show(args: argparse.Namespace) -> dict[str, Any]:
    return {"ok": True, "record": load_pgen(_workspace(args), args.project, args.id)}


def cmd_pgen_list(args: argparse.Namespace) -> dict[str, Any]:
    workspace = _workspace(args)
    return {"ok": True, "items": _list_records(workspace.require_project(args.project) / "pgens", "pgen.json")}


def cmd_deps_add(args: argparse.Namespace) -> dict[str, Any]:
    config = _json_value(args.config)
    env_text = Path(args.env).read_text(encoding="utf-8") if args.env else "#!/usr/bin/env bash\n"
    return {"ok": True, "record": add_deps(_workspace(args), args.site, args.id, config, env_text)}


def cmd_deps_show(args: argparse.Namespace) -> dict[str, Any]:
    site = SiteOps.from_workspace(_workspace(args), args.site)
    return {"ok": True, "record": load_deps(site, args.id)}


def cmd_deps_list(args: argparse.Namespace) -> dict[str, Any]:
    site = SiteOps.from_workspace(_workspace(args), args.site)
    root = site.path("deps")
    if site.kind != "local":
        result = site.run(["find", str(root), "-mindepth", "2", "-maxdepth", "2", "-name", "deps.json", "-print"])
        paths = [line for line in result.stdout.splitlines() if line]
        items = [site.read_json(PurePosixPath(path)) for path in paths]
    else:
        items = [load_json(path) for path in sorted(Path(root).glob("*/deps.json"))]
    return {"ok": True, "items": items}


def cmd_build_create(args: argparse.Namespace) -> dict[str, Any]:
    record = add_build(
        _workspace(args),
        args.project,
        args.id,
        args.source,
        args.pgen,
        args.site,
        args.deps,
        _json_value(args.options),
        _json_value(args.runtime, default={"mpi": False, "gpu": False}),
    )
    return {"ok": True, "record": record}


def cmd_build_prepare(args: argparse.Namespace) -> dict[str, Any]:
    return {"ok": True, "record": prepare_build(_workspace(args), args.project, args.id)}


def cmd_build_run(args: argparse.Namespace) -> dict[str, Any]:
    return {"ok": True, "record": run_build(_workspace(args), args.project, args.id)}


def cmd_build_show(args: argparse.Namespace) -> dict[str, Any]:
    return {"ok": True, **show_build_site(_workspace(args), args.project, args.id)}


def cmd_build_list(args: argparse.Namespace) -> dict[str, Any]:
    workspace = _workspace(args)
    return {"ok": True, "items": _list_records(workspace.require_project(args.project) / "builds", "build.json")}


def cmd_run_create(args: argparse.Namespace) -> dict[str, Any]:
    record = add_run(
        _workspace(args),
        args.project,
        args.id,
        args.build,
        Path(args.toml),
        _json_value(args.resources),
        {str(key): str(value) for key, value in _json_value(args.environment).items()},
    )
    return {"ok": True, "record": record}


def cmd_run_prepare(args: argparse.Namespace) -> dict[str, Any]:
    record = prepare_attempt(
        _workspace(args),
        args.project,
        args.id,
        build_id=args.build,
        attempt_id=args.attempt,
        resource_override=_json_value(args.resources),
        environment_override={str(key): str(value) for key, value in _json_value(args.environment).items()},
    )
    return {"ok": True, "record": record}


def cmd_run_submit(args: argparse.Namespace) -> dict[str, Any]:
    record = submit_attempt(
        _workspace(args), args.project, args.id, args.attempt, build_id=args.build
    )
    return {"ok": True, "record": record}


def cmd_run_status(args: argparse.Namespace) -> dict[str, Any]:
    record = attempt_status(
        _workspace(args), args.project, args.id, args.attempt, build_id=args.build
    )
    return {"ok": True, "record": record}


def cmd_run_show(args: argparse.Namespace) -> dict[str, Any]:
    build, root, record = load_run(_workspace(args), args.project, args.id, args.build)
    return {"ok": True, "build": build, "path": str(root), "record": record}


def cmd_run_data(args: argparse.Namespace) -> dict[str, Any]:
    return {"ok": True, "record": data_summary(_workspace(args), args.project, args.id, build_id=args.build)}


def cmd_analysis_record(args: argparse.Namespace) -> dict[str, Any]:
    record = record_analysis(
        _workspace(args), args.project, args.id, args.runs, args.script, _json_value(args.parameters), args.output
    )
    return {"ok": True, "record": record}


def cmd_analysis_show(args: argparse.Namespace) -> dict[str, Any]:
    workspace = _workspace(args)
    project = workspace.require_project(args.project)
    candidates = list(project.glob(f"builds/*/runs/*/analysis/{args.id}/analysis.json"))
    candidates.extend(project.glob(f"analysis/{args.id}/analysis.json"))
    if not candidates:
        raise EntityError(f"analysis not found: {args.id}", code="not_found")
    if len(candidates) > 1:
        raise EntityError(f"analysis id is ambiguous: {args.id}", code="ambiguous")
    return {"ok": True, "path": str(candidates[0].parent), "record": load_json(candidates[0])}


def cmd_check(args: argparse.Namespace) -> dict[str, Any]:
    return check_workspace(_workspace(args))


def cmd_migrate(args: argparse.Namespace) -> dict[str, Any]:
    return {"ok": True, "report": migrate_legacy(Path(args.source), Path(args.destination))}


def _add_project(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True)


def _add_run_identity(parser: argparse.ArgumentParser) -> None:
    _add_project(parser)
    parser.add_argument("--id", required=True, help="Run ID")
    parser.add_argument("--build", help="Build ID; optional when Run ID is unique")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="entity", description="File-first Entity workspace")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--workspace", help="Workspace root; otherwise ENTITY_WORKSPACE or parent discovery")
    commands = parser.add_subparsers(dest="command", required=True)

    workspace = commands.add_parser("workspace")
    workspace_sub = workspace.add_subparsers(dest="action", required=True)
    item = workspace_sub.add_parser("init")
    item.add_argument("path")
    item.add_argument("--id")
    item.set_defaults(func=cmd_workspace_init)
    item = workspace_sub.add_parser("show")
    item.set_defaults(func=cmd_workspace_show)

    project = commands.add_parser("project")
    project_sub = project.add_subparsers(dest="action", required=True)
    for name, func in (("init", cmd_project_init), ("show", cmd_project_show)):
        item = project_sub.add_parser(name)
        item.add_argument("--project", required=True)
        item.set_defaults(func=func)

    site = commands.add_parser("site")
    site_sub = site.add_subparsers(dest="action", required=True)
    item = site_sub.add_parser("add")
    item.add_argument("--config", required=True)
    item.set_defaults(func=cmd_site_add)
    for name, func in (("init", cmd_site_init), ("show", cmd_site_show)):
        item = site_sub.add_parser(name)
        item.add_argument("--site", required=True)
        item.set_defaults(func=func)
    item = site_sub.add_parser("list")
    item.set_defaults(func=cmd_site_list)

    source = commands.add_parser("source")
    source_sub = source.add_subparsers(dest="action", required=True)
    item = source_sub.add_parser("add")
    _add_project(item)
    item.add_argument("--id", required=True)
    item.add_argument("--repository", required=True)
    item.add_argument("--commit", required=True)
    item.add_argument("--checkout")
    item.set_defaults(func=cmd_source_add)
    item = source_sub.add_parser("show")
    _add_project(item)
    item.add_argument("--id", required=True)
    item.set_defaults(func=cmd_source_show)
    item = source_sub.add_parser("list")
    _add_project(item)
    item.set_defaults(func=cmd_source_list)

    pgen = commands.add_parser("pgen")
    pgen_sub = pgen.add_subparsers(dest="action", required=True)
    item = pgen_sub.add_parser("add")
    _add_project(item)
    item.add_argument("--id", required=True)
    item.add_argument("--from", dest="from_dir", required=True)
    item.add_argument("--entry", required=True)
    item.add_argument("--name")
    item.set_defaults(func=cmd_pgen_add)
    item = pgen_sub.add_parser("show")
    _add_project(item)
    item.add_argument("--id", required=True)
    item.set_defaults(func=cmd_pgen_show)
    item = pgen_sub.add_parser("list")
    _add_project(item)
    item.set_defaults(func=cmd_pgen_list)

    deps = commands.add_parser("deps")
    deps_sub = deps.add_subparsers(dest="action", required=True)
    item = deps_sub.add_parser("add")
    item.add_argument("--site", required=True)
    item.add_argument("--id", required=True)
    item.add_argument("--config", help="JSON object or @file")
    item.add_argument("--env", help="env.sh source file")
    item.set_defaults(func=cmd_deps_add)
    for name, func in (("show", cmd_deps_show), ("list", cmd_deps_list)):
        item = deps_sub.add_parser(name)
        item.add_argument("--site", required=True)
        if name == "show":
            item.add_argument("--id", required=True)
        item.set_defaults(func=func)

    build = commands.add_parser("build")
    build_sub = build.add_subparsers(dest="action", required=True)
    item = build_sub.add_parser("create")
    _add_project(item)
    for flag in ("id", "source", "pgen", "site", "deps"):
        item.add_argument(f"--{flag}", required=True)
    item.add_argument("--options", help="JSON object or @file")
    item.add_argument("--runtime", help="JSON object or @file")
    item.set_defaults(func=cmd_build_create)
    for name, func in (("prepare", cmd_build_prepare), ("run", cmd_build_run), ("show", cmd_build_show)):
        item = build_sub.add_parser(name)
        _add_project(item)
        item.add_argument("--id", required=True)
        item.set_defaults(func=func)
    item = build_sub.add_parser("list")
    _add_project(item)
    item.set_defaults(func=cmd_build_list)

    run = commands.add_parser("run")
    run_sub = run.add_subparsers(dest="action", required=True)
    item = run_sub.add_parser("create")
    _add_project(item)
    item.add_argument("--id", required=True)
    item.add_argument("--build", required=True)
    item.add_argument("--toml", required=True)
    item.add_argument("--resources", help="JSON object or @file")
    item.add_argument("--environment", help="JSON object or @file")
    item.set_defaults(func=cmd_run_create)
    item = run_sub.add_parser("prepare")
    _add_run_identity(item)
    item.add_argument("--attempt")
    item.add_argument("--resources", help="Attempt resource overrides")
    item.add_argument("--environment", help="Attempt environment overrides")
    item.set_defaults(func=cmd_run_prepare)
    for name, func in (("submit", cmd_run_submit), ("status", cmd_run_status)):
        item = run_sub.add_parser(name)
        _add_run_identity(item)
        item.add_argument("--attempt", required=True)
        item.set_defaults(func=func)
    for name, func in (("show", cmd_run_show), ("data", cmd_run_data)):
        item = run_sub.add_parser(name)
        _add_run_identity(item)
        item.set_defaults(func=func)

    analysis = commands.add_parser("analysis")
    analysis_sub = analysis.add_subparsers(dest="action", required=True)
    item = analysis_sub.add_parser("record")
    _add_project(item)
    item.add_argument("--id", required=True)
    item.add_argument("--runs", nargs="+", required=True, metavar="[BUILD:]RUN")
    item.add_argument("--script", required=True)
    item.add_argument("--parameters", help="JSON object or @file")
    item.add_argument("--output", required=True)
    item.set_defaults(func=cmd_analysis_record)
    item = analysis_sub.add_parser("show")
    _add_project(item)
    item.add_argument("--id", required=True)
    item.set_defaults(func=cmd_analysis_show)

    item = commands.add_parser("check")
    item.set_defaults(func=cmd_check)
    item = commands.add_parser("migrate")
    item.add_argument("--source", required=True, help="Legacy export JSON or ledger.db")
    item.add_argument("--destination", required=True, help="New empty Workspace")
    item.set_defaults(func=cmd_migrate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
        _print(result)
        if args.command == "check" and not result.get("ok"):
            return 1
        return 0
    except EntityError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except (OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "code": "system_error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
