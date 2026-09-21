# -*- coding: utf-8 -*-
"""Scoped Work commands using existing work_item rows and governed task events.

New plans bind scope, attempts, results, coordinator receipt and real integration
candidates. Legacy rows remain readable without invented result obligations.
No command merges code, launches an agent or closes the parent Task.
"""

from __future__ import annotations

import json
import sys
from typing import List, Optional

from . import db as dbmod


def _split_csv(s: Optional[str]) -> List[str]:
    """解析逗号分隔字符串为列表。"""
    if not s:
        return []
    return [item.strip() for item in s.split(",") if item.strip()]


def summarize_work_items(conn, task, *, rows=None, retired: bool = False) -> dict:
    """Read existing milestones; never derive Task/project completion or repair rows."""
    task = dict(task)
    if rows is None:
        rows = conn.execute("SELECT * FROM work_item WHERE task_id=? ORDER BY created_at,item_id",
                            (task["task_id"],)).fetchall()
    items = [dict(row) for row in rows]
    by_id = {row["item_id"]: row for row in items}
    counts = {"PENDING": 0, "ACTIVE": 0, "COMPLETED": 0}
    issues = []
    current = not retired and task.get("current_state") not in {"COMPLETED", "CANCELLED"}
    for item in items:
        state = item.get("status")
        if state in counts:
            counts[state] += 1
        else:
            issues.append(f"{item['item_id']}: UNKNOWN_STATUS")
        try:
            depends = json.loads(item.get("depends_on_json") or "[]")
            if not isinstance(depends, list) or any(not isinstance(d, str) or not d.strip() for d in depends):
                raise ValueError("invalid dependency list")
        except (ValueError, TypeError):
            depends = []
            issues.append(f"{item['item_id']}: INVALID_DEPENDENCIES")
        unresolved = [d for d in depends if d not in by_id or by_id[d]["status"] != "COMPLETED"]
        if any(d not in by_id or d == item["item_id"] for d in depends):
            issues.append(f"{item['item_id']}: DEPENDENCY_UNRESOLVED")
        if state == "COMPLETED" and unresolved:
            issues.append(f"{item['item_id']}: COMPLETED_WITH_PENDING_DEPENDENCY")
        item["depends_on"] = depends
        item["unresolved_dependencies"] = unresolved
        item["current"] = current
    if task.get("current_state") == "COMPLETED" and counts["PENDING"] + counts["ACTIVE"]:
        issues.append("TERMINAL_TASK_OPEN_ITEMS")
    elif not current and counts["ACTIVE"]:
        issues.append("HISTORICAL_ACTIVE_ITEM")
    from . import work_units
    scoped = work_units.read(conn, task["task_id"])
    issues.extend(scoped["issues"])
    for item in items:
        pending_receipts = [wid for wid in item["depends_on"] if wid in scoped["units"] and not scoped["units"][wid]["receipt"]]
        item["unresolved_dependencies"] = sorted(set(item["unresolved_dependencies"]) | set(pending_receipts))
        if item["status"] == "COMPLETED" and pending_receipts:
            issues.append(f"{item['item_id']}: COMPLETED_WITH_UNRECEIVED_DEPENDENCY")
        unit = scoped["units"].get(item["item_id"])
        if unit:
            item["work_unit"] = unit
            if item["status"] != unit["recorded_state"]:
                issues.append(f"{item['item_id']}: WORK_ROW_FACT_MISMATCH")
            if current and item["status"] == "COMPLETED" and not unit["receipt"]:
                issues.append(f"{item['item_id']}: WORK_RESULT_NOT_RECEIVED")
    consistency = "NEEDS_RECONCILIATION" if issues else ("RECORDED" if items else "NOT_RECORDED")
    summary = (f"WorkItem 登记：待处理 {counts['PENDING']} / 已认领 {counts['ACTIVE']} / 已完成 {counts['COMPLETED']}；"
               f"{consistency}。只代表该任务里程碑记录，不是整任务/项目验收或进程存活。")
    if issues:
        summary += " 待核对：" + "; ".join(issues)
    return {"source": "work_item", "completion_scope": "task_work_items_only", "current": current,
            "counts": counts, "consistency": consistency, "issues": issues,
            "items": [{key: item.get(key) for key in ("item_id", "title", "status", "owner_role",
                       "owner_agent", "depends_on", "unresolved_dependencies", "current", "updated_at", "work_unit")}
                      for item in items], "summary": summary,
            "integration": {"status": "RECORDED" if scoped["candidates"] else "MISSING" if scoped["units"] else "NOT_REQUIRED",
                "candidate": scoped["candidates"][-1] if scoped["candidates"] else None,
                "note": "recorded snapshot; use complete --check for current evidence applicability"}}


def _json_file(path):
    from pathlib import Path
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _write(args, operation):
    from .execution_cmd import _write_command
    return _write_command(args, operation, allow_legacy=True)


def cmd_workitem_create(args) -> int:
    def write(conn, task, facts):
        from . import work_units as units, security_authority as authority
        item_id = authority.identifier(args.id, "work item id")
        if getattr(args, "file", None):
            if args.depends or args.paths or args.acceptance or args.effect_scope or args.security_change:
                raise ValueError("WORK_SPEC_CONFLICT: include scope/security_context in one JSON spec, not CLI overrides")
            spec = units.normalize_spec(conn, task, facts, _json_file(args.file), item_id=item_id)
            return units.create(conn, task, facts, item_id=item_id, title=args.title or spec["scope"],
                spec=spec, actor=args.role, agent=args.agent)
        if facts["plan"]:
            raise ValueError("WORK_SPEC_REQUIRED: explicit-plan Work needs --file with scope and result ownership")
        depends = units.dependencies(conn, args.task, _split_csv(args.depends), self_id=item_id)
        paths = units.paths(_split_csv(args.paths))
        acs = _split_csv(args.acceptance)
        if conn.execute("SELECT 1 FROM work_item WHERE item_id=?", (item_id,)).fetchone():
            raise ValueError("WORK_ID_EXISTS: work_item IDs are globally unique")
        ctx = authority.context_from_args(args)
        ctx.update(paths=paths, ac_refs=acs)
        state = authority.read(conn, args.task)
        authority.check(state, ctx)
        now = dbmod.now_iso()
        conn.execute("INSERT INTO work_item (item_id,task_id,title,status,depends_on_json,allowed_paths_json,acceptance_refs_json,created_at,updated_at) VALUES (?,?,?,'PENDING',?,?,?,?,?)",
            (item_id, args.task, args.title or "", json.dumps(depends), json.dumps(paths), json.dumps(acs), now, now))
        if state["proposals"] or ctx["security_changes"] or ctx["effect_scope"] != "implementation":
            authority.append(conn, args.task, authority.WORK, {"work_item_id": item_id, "context": ctx},
                actor="tp-spec-coding", summary="Work authority context (not a grant)", item_id=item_id)
        return f"Work item created: {item_id} (PENDING)"
    return _write(args, write)


def cmd_workitem_claim(args) -> int:
    def write(conn, task, facts):
        from . import work_units as units
        item = units.checked_item(conn, args.task, args.id)
        unit = units.read(conn, args.task)["units"].get(args.id)
        units.claim_guard(conn, task, item, unit, args.role, args.agent)
        if item["status"] == "ACTIVE":
            if (item["owner_role"], item["owner_agent"]) != (args.role, args.agent):
                raise ValueError("WORK_ALREADY_CLAIMED: no silent takeover; current owner must release")
            return {"item_id": args.id, "status": "ACTIVE", "replayed": True}
        if item["status"] != "PENDING":
            raise ValueError("WORK_NOT_PENDING: retry the same failed Work explicitly")
        event_id = None
        if unit:
            event_id = units.append(conn, task, "claim", {"attempt": unit["attempt"] + 1},
                actor=args.role, agent=args.agent, item=args.id)
        conn.execute("UPDATE work_item SET status='ACTIVE',owner_role=?,owner_agent=?,updated_at=? WHERE task_id=? AND item_id=?",
            (args.role, args.agent, dbmod.now_iso(), args.task, args.id))
        return {"item_id": args.id, "status": "ACTIVE", "event_id": event_id, "replayed": False}
    return _write(args, write)


def _owner(item, args):
    if (item["owner_role"], item["owner_agent"]) != (args.role, args.agent):
        raise ValueError("WORK_OWNER_MISMATCH: use the actual recorded role/executor; strings are not authentication")


def cmd_workitem_complete(args) -> int:
    def write(conn, task, facts):
        from . import work_units as units
        from .security_authority import check_work
        item = units.checked_item(conn, args.task, args.id)
        unit = units.read(conn, args.task)["units"].get(args.id)
        units.require_dependencies(conn, args.task, item)
        check_work(conn, args.task, args.id)
        event_id = None
        if unit:
            _owner(item, args)
            if not args.result:
                raise ValueError("WORK_RESULT_REQUIRED: complete --result <JSON> binds real outputs/evidence")
            body = units.prepare_result(conn, task, item, unit, _json_file(args.result))
            if item["status"] == "COMPLETED" and unit["result"] and unit["result"]["result"] == body:
                return {"item_id": args.id, "event_id": unit["result"]["event_id"], "replayed": True}
            if item["status"] != "ACTIVE":
                raise ValueError("WORK_NOT_ACTIVE: claim or explicitly retry before reporting a result")
            units.require_closed_sessions(conn, task, args.id)
            event_id = units.append(conn, task, "result", {"summary": body["summary"], "result": body, "attempt": unit["attempt"]},
                actor=args.role, agent=args.agent, item=args.id)
        elif item["status"] != "ACTIVE":
            raise ValueError("WORK_NOT_ACTIVE: claim before completion")
        conn.execute("UPDATE work_item SET status='COMPLETED',updated_at=? WHERE task_id=? AND item_id=?",
            (dbmod.now_iso(), args.task, args.id))
        return {"item_id": args.id, "event_id": event_id, "status": "COMPLETED", "received": False if unit else None,
                "note": "Work result only; parent step/Task is not completed", "replayed": False}
    return _write(args, write)


def cmd_workitem_release(args) -> int:
    def write(conn, task, facts):
        from . import work_units as units
        item = units.checked_item(conn, args.task, args.id)
        unit = units.read(conn, args.task)["units"].get(args.id)
        if item["status"] != "ACTIVE":
            raise ValueError("WORK_NOT_ACTIVE: only a claimed Work can be released")
        if unit:
            _owner(item, args)
            units.require_closed_sessions(conn, task, args.id)
            units.append(conn, task, "release", {"summary": units._text(args.reason, "reason"),
                "recovery_condition": units._text(args.recovery, "recovery"), "attempt": unit["attempt"]},
                actor=args.role, agent=args.agent, item=args.id)
        conn.execute("UPDATE work_item SET status='PENDING',owner_role=NULL,owner_agent=NULL,updated_at=? WHERE task_id=? AND item_id=?",
            (dbmod.now_iso(), args.task, args.id))
        return {"item_id": args.id, "status": "PENDING", "note": "prior attempts preserved; no new Work created"}
    return _write(args, write)


def cmd_workitem_receive(args) -> int:
    def write(conn, task, facts):
        from . import work_units as units
        units.coordinator(facts, args.role, args.agent)
        item = units.checked_item(conn, args.task, args.id)
        unit = units.read(conn, args.task)["units"].get(args.id)
        if not unit or not unit["result"] or item["status"] != "COMPLETED":
            raise ValueError("WORK_RESULT_REQUIRED")
        if args.result_event != unit["result"]["event_id"]:
            raise ValueError("WORK_RESULT_CHANGED: receive the latest exact result event")
        units.require_dependencies(conn, args.task, item)
        units.validate_result(conn, args.task, unit, source_output=True)
        if unit["receipt"]:
            return {"item_id": args.id, "event_id": unit["receipt"]["event_id"], "replayed": True}
        from .security_authority import check_work
        check_work(conn, args.task, args.id)
        eid = units.append(conn, task, "receive", {"result_event_id": args.result_event,
            "summary": units._text(args.summary, "receipt.summary")}, actor=args.role, agent=args.agent, item=args.id)
        return {"item_id": args.id, "event_id": eid, "replayed": False, "note": "received, not integrated or parent-validated"}
    return _write(args, write)


def cmd_workitem_retry(args) -> int:
    def write(conn, task, facts):
        from . import work_units as units
        from .execution_cmd import record_step
        units.coordinator(facts, args.role, args.agent)
        item = units.checked_item(conn, args.task, args.id)
        unit = units.read(conn, args.task)["units"].get(args.id)
        if not unit or item["status"] != "COMPLETED":
            raise ValueError("WORK_RETRY_REQUIRES_COMPLETED_RESULT: active failures use release")
        units.require_closed_sessions(conn, task, args.id)
        step = facts["current_step"]
        if not step or step["id"] != args.step:
            raise ValueError("FIX_CURRENT_STEP_REQUIRED")
        if unit["spec"]["kind"] != "FIX" and step["id"] != unit["spec"]["step_id"]:
            raise ValueError("WORK_RETRY_SCOPE_CHANGED: create a scoped Fix, not a rewound parent step")
        summary, recovery = units._text(args.reason, "reason"), units._text(args.recovery, "recovery")
        eid = units.append(conn, task, "retry", {"summary": summary, "recovery_condition": recovery, "step_id": step["id"]},
                           actor=args.role, agent=args.agent, item=args.id)
        conn.execute("UPDATE work_item SET status='PENDING',owner_role=NULL,owner_agent=NULL,updated_at=? WHERE task_id=? AND item_id=?",
                     (dbmod.now_iso(), args.task, args.id))
        if step["status"] == "ACTIVE":
            record_step(conn, task, facts, step_id=step["id"], plan_version=facts["plan_version"], action="wait",
                actor=args.role, summary=summary, wait_reason=recovery, expected_next=unit["spec"]["roles"][0], waiting_items=[args.id])
        return {"item_id": args.id, "event_id": eid, "status": "PENDING", "note": "same issue, previous attempts/receipts remain historical"}
    return _write(args, write)


def cmd_workitem_candidate(args) -> int:
    from .work_units import record_candidate
    return _write(args, lambda conn, task, facts: record_candidate(conn, task, facts, _json_file(args.file),
        actor=args.role, agent=args.agent))


def cmd_workitem_list(args) -> int:
    task_id = args.task
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect_readonly(db_path)
    try:
        conn.execute("BEGIN")
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {task_id}", file=sys.stderr)
            return 4
        from .event_policies import is_task_retired
        facts = summarize_work_items(conn, task, retired=is_task_retired(conn, task_id))
        if getattr(args, "json", False):
            if args.status:
                facts = {**facts, "items": [item for item in facts["items"] if item["status"] == args.status],
                         "filter_status": args.status, "counts_scope": "all_task_work_items"}
            print(json.dumps(facts, ensure_ascii=False, indent=2))
            return 0
        print(facts["summary"])
        rows = [item for item in facts["items"] if not args.status or item["status"] == args.status]
        if not rows:
            print(f"(no work items for {task_id})")
            return 0
        print(f"work items for {task_id} ({len(rows)}):")
        for r in rows:
            print(
                f"  {r['item_id']} [{r['status']}] {r['title'] or ''} "
                f"owner={r['owner_role'] or '-'}/{r['owner_agent'] or '-'} "
                f"depends={','.join(r['depends_on']) or '-'} "
                f"waiting_on={','.join(r['unresolved_dependencies']) or '-'}"
            )
        return 0
    finally:
        conn.close()


def add_workitem_subparsers(workitem_parser) -> None:
    """注册 workitem 命令组的子命令。"""
    sub = workitem_parser.add_subparsers(dest="subcommand", required=True)

    # workitem create
    p_create = sub.add_parser("create", help="Create a work item")
    p_create.add_argument("--task", required=True, help="task id")
    p_create.add_argument("--id", required=True, help="work item id (e.g. WI-01)")
    p_create.add_argument("--title", required=False, default="", help="work item title")
    p_create.add_argument("--depends", required=False, default=None, help="depends on (WI-01,WI-02)")
    p_create.add_argument("--paths", required=False, default=None, help="allowed paths (glob1,glob2)")
    p_create.add_argument("--acceptance", required=False, default=None, help="acceptance refs (AC-01,AC-02)")
    p_create.add_argument("--db", required=False, default=None)
    from .security_authority import add_context_args
    add_context_args(p_create, investigation=True, scope_fields=False, effect=None)
    p_create.add_argument("--file", help="Scoped Work JSON for an explicit plan")
    p_create.add_argument("--role", default="tp-software-lifecycle")
    p_create.add_argument("--agent", default="")
    p_create.set_defaults(func=cmd_workitem_create)

    # workitem claim
    p_claim = sub.add_parser("claim", help="Claim a work item")
    p_claim.add_argument("--task", required=True, help="task id")
    p_claim.add_argument("--id", required=True, help="work item id")
    p_claim.add_argument("--role", required=True, help="owner role")
    p_claim.add_argument("--agent", required=True, help="owner agent")
    p_claim.add_argument("--db", required=False, default=None)
    p_claim.set_defaults(func=cmd_workitem_claim)

    # workitem complete
    p_complete = sub.add_parser("complete", help="Mark work item as completed")
    p_complete.add_argument("--task", required=True, help="task id")
    p_complete.add_argument("--id", required=True, help="work item id")
    p_complete.add_argument("--db", required=False, default=None)
    p_complete.add_argument("--result", help="JSON output/evidence manifest (required for scoped Work)")
    p_complete.add_argument("--role", default=None)
    p_complete.add_argument("--agent", default=None)
    p_complete.set_defaults(func=cmd_workitem_complete)

    # workitem release
    p_release = sub.add_parser("release", help="Release a claimed work item back to PENDING")
    p_release.add_argument("--task", required=True, help="task id")
    p_release.add_argument("--id", required=True, help="work item id")
    p_release.add_argument("--db", required=False, default=None)
    p_release.add_argument("--role", default=None)
    p_release.add_argument("--agent", default=None)
    p_release.add_argument("--reason", default=None)
    p_release.add_argument("--recovery", default=None)
    p_release.set_defaults(func=cmd_workitem_release)

    # workitem list
    p_list = sub.add_parser("list", help="List work items for a task")
    p_list.add_argument("--task", required=True, help="task id")
    p_list.add_argument("--status", required=False, default=None, choices=["PENDING", "ACTIVE", "COMPLETED"])
    p_list.add_argument("--db", required=False, default=None)
    p_list.add_argument("--json", action="store_true", help="Include exact result/receipt IDs and integration facts")
    p_list.set_defaults(func=cmd_workitem_list)

    for name, function in (("receive", cmd_workitem_receive), ("retry", cmd_workitem_retry), ("candidate", cmd_workitem_candidate)):
        parser = sub.add_parser(name, help="Record scoped Work " + name + "; no product operation")
        parser.add_argument("--task", required=True)
        parser.add_argument("--db", default=None)
        parser.add_argument("--role", required=True)
        parser.add_argument("--agent", required=True)
        if name != "candidate":
            parser.add_argument("--id", required=True)
        if name == "receive":
            parser.add_argument("--result-event", required=True, type=int)
            parser.add_argument("--summary", required=True)
        elif name == "retry":
            parser.add_argument("--step", required=True)
            parser.add_argument("--reason", required=True)
            parser.add_argument("--recovery", required=True)
        else:
            parser.add_argument("--file", required=True)
        parser.set_defaults(func=function)
