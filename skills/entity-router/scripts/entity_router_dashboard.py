#!/usr/bin/env python3
"""Project dashboard: readiness board, run ledger and derived next steps.

Read-only presentation over controller-local Case facts.  The board answers
"where is the project", the deriver answers "what is next"; both are computed
from stored facts and never stored themselves.  Local probes are limited to
the project checkout (git revision, PGen confirmation records).  This module
is standard-library only and Python 3.6 compatible.
"""

from __future__ import print_function

import json
import os

from entity_router_common import sha256_file
from entity_router_facts import _git_revision


BOARD_ORDER = ["source", "pgen", "build", "run", "data", "analysis"]


def _find_identity(items, identity_id):
    for item in items:
        if item.get("id") == identity_id:
            return item
    return None


def _pgen_cell(project_root):
    """PGen readiness from local confirmation records: a TOML input counts as
    confirmed only when its ``.decisions.json`` still matches the file bytes."""
    if not os.path.isdir(project_root):
        return {"state": "unknown", "detail": "project root 不在本机"}
    confirmed = []
    unconfirmed = []
    for name in sorted(os.listdir(project_root)):
        if not name.endswith(".toml"):
            continue
        record = None
        digest = None
        try:
            with open(os.path.join(project_root, name + ".decisions.json"), "r") as handle:
                record = json.load(handle)
            digest = sha256_file(os.path.join(project_root, name))
        except (IOError, OSError, ValueError):
            pass
        if (isinstance(record, dict)
                and record.get("kind") == "entity-pgen.simulation-confirmation"
                and digest is not None
                and record.get("input_sha256") == digest):
            confirmed.append(name)
        else:
            unconfirmed.append(name)
    if confirmed and not unconfirmed:
        return {"state": "confirmed", "detail": ", ".join(confirmed)}
    if confirmed:
        return {"state": "partial",
                "detail": "已确认 %s；未确认 %s" % (", ".join(confirmed),
                                                   ", ".join(unconfirmed))}
    if unconfirmed:
        return {"state": "unconfirmed", "detail": ", ".join(unconfirmed)}
    return {"state": "unknown", "detail": "项目根下没有 TOML 输入"}


def _source_cell(case, project_root, alerts):
    source = case.get("source", {})
    authority = source.get("authority") or {}
    if not authority:
        return {"state": "missing", "detail": "尚未物化 source"}
    revision = source.get("revision") or {}
    label = ""
    if revision.get("kind") == "git":
        label = (revision.get("commit") or "")[:8] + " @ "
    detail = "%s%s:%s" % (label, authority.get("site_id", "?"),
                          authority.get("path", "?"))
    if revision.get("kind") == "git" and os.path.isdir(project_root):
        current = _git_revision(project_root)
        if current.get("kind") == "git":
            if current.get("commit") != revision.get("commit"):
                alerts.append(
                    "source 记录为 %s，当前 HEAD 为 %s——build/run 可能 stale"
                    % ((revision.get("commit") or "")[:8],
                       (current.get("commit") or "")[:8]))
                detail += "（HEAD 已变化）"
            elif current.get("dirty") and not revision.get("dirty"):
                detail += "（工作区有未提交修改）"
    return {"state": "established", "detail": detail}


def _build_cell(case, current):
    build_id = current.get("build_id", "")
    payload = _find_identity(
        case.get("identities", {}).get("build", {}).get("items", []), build_id)
    if not build_id or payload is None:
        return {"state": "missing", "detail": "—"}
    outputs = payload.get("outputs", [])
    locator = outputs[0].get("locator", {}) if outputs else {}
    name = os.path.basename(locator.get("path", "")) or build_id
    return {"state": payload.get("status", "verified"),
            "detail": "%s @ %s" % (name, locator.get("site_id", "?"))}


def _scheduler_brief(payload):
    scheduler = payload.get("scheduler", {})
    if scheduler.get("job_id"):
        return "job %s" % scheduler["job_id"]
    if scheduler.get("pid"):
        return "pid %s" % scheduler["pid"]
    return ""


def _run_cell(case, current, live):
    run_id = current.get("run_id", "")
    payload = _find_identity(
        case.get("identities", {}).get("run", {}).get("items", []), run_id)
    if not run_id or payload is None:
        return {"state": "none", "detail": "—"}
    state = payload.get("status", "unknown")
    brief = _scheduler_brief(payload)
    detail = "%s @ %s" % (run_id, payload.get("site_id", "?"))
    if brief:
        detail += "（%s）" % brief
    if payload.get("exit_code") is not None:
        detail += "；exit %s" % payload["exit_code"]
    if live:
        live_state = live.get("state", "")
        if live_state == "EXITED":
            state = "exited"
            detail += "；exit %s" % live.get("exit_code", "?")
        elif live_state == "RUNNING":
            state = "running"
        elif live_state == "NOT_FOUND":
            state = "gone"
        elif live_state in {"UNKNOWN", ""} and live.get("warning"):
            detail += "；实时探测不可用"
        elif live_state:
            detail += "；%s" % live_state
    return {"state": state, "detail": detail}


def _data_cell(case, current):
    data_id = current.get("data_id", "")
    payload = _find_identity(
        case.get("identities", {}).get("data", {}).get("items", []), data_id)
    if not data_id or payload is None:
        return {"state": "missing", "detail": "—"}
    return {"state": payload.get("status", "inventoried"),
            "detail": "%s 个文件" % payload.get("files", "?")}


def derive_next_steps(board, pending, run_id):
    """The deriver: map (board, intent facts) to suggested next steps.  These
    rules replace a stored state machine — they are computed on every read and
    can never drift from the recorded facts."""
    steps = []
    run_state = board["run"]["state"]
    if run_state in {"exited", "completed"} and board["data"]["state"] == "missing":
        steps.append("run %s 已到终态；用 entityctl record data 盘点输出" % run_id)
    elif run_state == "failed":
        steps.append("run %s 失败；检查 run_root 日志定位原因，修复后重跑" % run_id)
    elif run_state in {"submitted", "running"}:
        steps.append("run %s 运行中；用 status --live 或 record run-exit 跟踪终态"
                     % run_id)
    elif run_state == "prepared":
        steps.append("run %s 已准备好；用 entityctl record run-launch 提交" % run_id)
    elif run_state == "gone":
        steps.append("run %s 的记录与后端不符（job_gone）；检查带外变更" % run_id)
    if board["pgen"]["state"] in {"unconfirmed", "partial"}:
        steps.append("确认模拟参数：pgen_preflight.py confirm <input> --by <actor>")
    if board["build"]["state"] == "missing" and board["source"]["state"] != "missing":
        steps.append("构建：用 entity-env-build 编译后 entityctl record build 登记")
    if board["data"]["state"] == "inventoried":
        steps.append("数据已盘点；用 entity-nt2py 分析")
    if not steps:
        steps.append("无阻塞项；按研究目标推进（改 PGen、换参数再跑、或分析数据）")
    return steps[:4]


def build_dashboard(store, project_root, status=None):
    """Assemble the dashboard from controller-local facts.  ``status`` is an
    optional status_for_project result supplying live probes and divergences."""
    case = store.resolve_project(project_root)
    current = case.get("current", {})
    live = (status or {}).get("live")
    alerts = []
    for item in (status or {}).get("divergences", []):
        alerts.append("带外变更 %s：%s" % (item.get("kind", "?"),
                                          item.get("detail", "")))
    board = {
        "source": _source_cell(case, case.get("project_root") or project_root, alerts),
        "pgen": _pgen_cell(case.get("project_root") or project_root),
        "build": _build_cell(case, current),
        "run": _run_cell(case, current, live),
        "data": _data_cell(case, current),
        "analysis": {"state": "none" if not current.get("analysis_id") else "ready",
                     "detail": current.get("analysis_id") or "—"},
    }
    ledger = []
    for item in case.get("identities", {}).get("run", {}).get("items", []):
        ledger.append({
            "run_id": item.get("id", ""),
            "site_id": item.get("site_id", ""),
            "status": item.get("status", "unknown"),
            "scheduler": _scheduler_brief(item),
        })
    # 意图是唯一存下来的指针（不可推导）：由 entityctl record intent 显式
    # 写入 current["intent"]，未写入时显示"未记录"
    intent_record = current.get("intent") or {}
    intent = intent_record.get("text") or "未记录"
    if intent_record.get("recorded_at") and intent_record.get("text"):
        intent += "（记录于 %s）" % intent_record["recorded_at"]
    pending = list(alerts)
    if board["pgen"]["state"] in {"unconfirmed", "partial"}:
        pending.append("模拟参数未确认：%s" % board["pgen"]["detail"])
    return {
        "schema_version": 1, "kind": "entity-router.dashboard",
        "state_mutated": False,
        "remote_calls": (status or {}).get("remote_calls", 0),
        "case_uid": case["case_uid"], "case_id": case.get("case_id", ""),
        "project_root": case.get("project_root") or project_root,
        "updated_at": case.get("updated_at", ""),
        "intent": intent, "board": board, "runs": ledger,
        "pending": pending,
        "next_steps": derive_next_steps(
            board, pending, current.get("run_id", "")),
        "live": live,
    }


def render_text(dashboard):
    """Compact human-readable rendering; normal output stays well under 4 KiB."""
    lines = [
        "Case %s（%s）  更新于 %s" % (dashboard["case_id"],
                                      dashboard["case_uid"],
                                      dashboard["updated_at"] or "?"),
        "项目  %s" % dashboard["project_root"],
        "目标  %s" % dashboard["intent"],
        "",
        "就绪板",
    ]
    for name in BOARD_ORDER:
        cell = dashboard["board"][name]
        lines.append("  %-9s %-12s %s" % (name, cell["state"], cell["detail"]))
    if dashboard["runs"]:
        lines += ["", "Run 台账"]
        for item in dashboard["runs"][-5:]:
            brief = ("  %s" % item["scheduler"]) if item["scheduler"] else ""
            lines.append("  %-22s %-10s %s%s" % (
                item["run_id"], item["status"], item["site_id"], brief))
    if dashboard["pending"]:
        lines += ["", "待决"]
        for item in dashboard["pending"]:
            lines.append("  - %s" % item)
    lines += ["", "建议下一步"]
    for index, step in enumerate(dashboard["next_steps"], 1):
        lines.append("  %d. %s" % (index, step))
    live = dashboard.get("live")
    if live:
        lines += ["", "实时探测：%s（%s，%d 次远端调用）" % (
            live.get("state", "?"), live.get("observed_at", "?"),
            dashboard["remote_calls"])]
    return "\n".join(lines)
