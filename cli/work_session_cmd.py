# -*- coding: utf-8 -*-
"""TP-Spec-Coding work 命令组（M2）。

包含：
- work plan / step / show / start / update / end

核心保证：
- work start：单事务插入 WORK_SESSION_STARTED 事件
- work end：单事务插入 WORK_SESSION_ENDED 事件，reason 受控
- reason=blocked 不自动转 BLOCKED（状态流转必须显式 task transition）
- actor_role 默认回退到 task.owner_role；actor_agent 可显式记录，缺省沿用 task.owner_agent
- 新事件用 session_id 关联 START/UPDATE/END；已采用计划的任务按角色/执行者/步骤/Work 区分参与
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from typing import Optional

from . import db as dbmod
from . import event_contract

DEFAULT_ROLE = "tp-software-lifecycle"


# work end reason 受控集合（与 handoff.json/work-session 规范一致）
_REASON_CODES = (
    "completed",
    "paused",
    "waiting_human",
    "waiting_agent",
    "blocked",
    "handed_off",
    "interrupted",
    "cancelled",
)


def _event_detail(row) -> Optional[dict]:
    """Missing legacy metadata is valid; malformed metadata must not become legacy."""
    try:
        value = json.loads(dict(row).get("detail_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("session_id", ""), str):
        return None
    return value


def _session_time(value) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.utcoffset() is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def pair_work_sessions(rows) -> dict:
    """Match recorded identities, never infer liveness or repair ambiguous history."""
    opened = {}
    pairs, unmatched_ends, invalid_events = [], [], []
    for raw in rows:
        row = dict(raw)
        kind = row.get("event_type")
        if kind not in {"WORK_SESSION_STARTED", "WORK_SESSION_ENDED"}:
            continue
        detail = _event_detail(row)
        if kind == "WORK_SESSION_STARTED":
            opened[row["id"]] = row
            if detail is None:
                invalid_events.append(row)
            continue
        if detail is None:
            invalid_events.append(row)
            unmatched_ends.append(row)
            continue
        sid = detail.get("session_id", "")
        candidates = []
        for start in opened.values():
            source = _event_detail(start)
            if source is None or start.get("task_id", "") != row.get("task_id", ""):
                continue
            if source.get("session_id", "") != sid:
                continue
            if not sid and start.get("actor_role", "") != row.get("actor_role", ""):
                continue
            if "start_event_id" in detail and (type(detail["start_event_id"]) is not int
                                               or detail["start_event_id"] != start["id"]):
                continue
            candidates.append(start)
        if len(candidates) != 1:
            unmatched_ends.append(row)
            continue
        start = candidates[0]
        if any((start.get(key) or "") != (row.get(key) or "")
               for key in ("actor_role", "actor_agent", "work_item_id")):
            unmatched_ends.append(row)
            continue
        opened.pop(start["id"])
        start_time, end_time = _session_time(start.get("created_at")), _session_time(row.get("created_at"))
        duration = None
        if start_time is not None and end_time is not None and end_time >= start_time:
            duration = (end_time - start_time).total_seconds()
        pairs.append({
            "session_id": sid, "role": str(start.get("actor_role") or "(unknown)"),
            "start": start_time, "end": end_time, "duration": duration,
            "reason": str(detail.get("reason") or ""),
            "start_event_id": start["id"], "end_event_id": row["id"],
        })
    return {"pairs": pairs, "unmatched_starts": list(opened.values()),
            "unmatched_ends": unmatched_ends, "invalid_events": invalid_events}


def summarize_work_sessions(rows) -> dict:
    """Compact read-only observations; START/END do not observe an agent process."""
    rows = [dict(row) for row in rows
            if row["event_type"] in {"WORK_SESSION_STARTED", "WORK_SESSION_UPDATED", "WORK_SESSION_ENDED"}]
    paired = pair_work_sessions(rows)
    opened = [{key: row.get(key) or "" for key in
               ("id", "actor_role", "actor_agent", "model_used", "work_item_id", "created_at")}
              for row in paired["unmatched_starts"]]
    latest = rows[-1] if rows else {}
    detail = _event_detail(latest) or {}
    unknown_durations = sum(p["duration"] is None for p in paired["pairs"])
    summary = (f"运行状态未知；未闭合 START {len(opened)} 条；"
               f"最后工作段记录：{latest.get('created_at') or '未记录'}。"
               "角色和 START/END 不证明进程存活、独立执行或任务完成。")
    if paired["invalid_events"] or paired["unmatched_ends"] or unknown_durations:
        summary += (f" 待核对：损坏记录 {len(paired['invalid_events'])}，"
                    f"未配对 END {len(paired['unmatched_ends'])}，无法计时 {unknown_durations}。")
    return {
        "source": "task_event.work_session", "runtime_status": "UNKNOWN",
        "last_recorded_at": latest.get("created_at") or "",
        "last_event_id": latest.get("id"), "last_event_type": latest.get("event_type") or "",
        "last_end_reason": detail.get("reason", "") if latest.get("event_type") == "WORK_SESSION_ENDED" else "",
        "open_count": len(opened), "paired_count": len(paired["pairs"]),
        "unmatched_end_count": len(paired["unmatched_ends"]),
        "invalid_event_count": len(paired["invalid_events"]),
        "unknown_duration_count": unknown_durations,
        "open_sessions": opened, "summary": summary,
    }


def _open_sessions(conn, task_id: str):
    rows = conn.execute("SELECT * FROM task_event WHERE task_id=? "
                        "AND event_type IN ('WORK_SESSION_STARTED','WORK_SESSION_ENDED') ORDER BY id",
                        (task_id,)).fetchall()
    return pair_work_sessions(rows)["unmatched_starts"]


def _open_session_for_role(conn, task_id: str, actor_role: str):
    # Kept for legacy callers. Multiple explicit participations must be selected by ID.
    opened = [row for row in _open_sessions(conn, task_id) if row.get("actor_role") == actor_role]
    if len(opened) > 1 or any(_event_detail(row) is None for row in opened):
        raise ValueError("WORK_SESSION_AMBIGUOUS: select --session; history was not changed")
    return ((_event_detail(opened[0]).get("session_id", ""), opened[0]) if opened else None)


def _selected_start(conn, task, args):
    opened = _open_sessions(conn, task["task_id"])
    sid = getattr(args, "session", None)
    if sid:
        candidates = [row for row in opened if (_event_detail(row) or {}).get("session_id") == sid]
    else:
        actor = args.role or task["owner_role"] or DEFAULT_ROLE
        agent = args.agent if args.agent is not None else (task["owner_agent"] or "")
        candidates = [row for row in opened if row.get("actor_role") == actor and (row.get("actor_agent") or "") == agent]
    if len(candidates) != 1 or _event_detail(candidates[0]) is None:
        raise ValueError("WORK_SESSION_AMBIGUOUS_OR_MISSING: use the exact open --session ID from work show/START")
    row = candidates[0]
    if ((args.role is not None and args.role != row.get("actor_role"))
            or (args.agent is not None and args.agent != (row.get("actor_agent") or ""))):
        raise ValueError("WORK_SESSION_OWNER_MISMATCH: actor must match the recorded START")
    return row


def _outcome(args, conn, task_id):
    from .execution_cmd import validate_refs, _strings
    return {"result": getattr(args, "result", "") or "",
            "findings": _strings(getattr(args, "finding", []) or [], "findings"),
            "decisions": _strings(getattr(args, "decision", []) or [], "decisions"),
            "evidence_refs": validate_refs(conn, task_id, getattr(args, "evidence", []) or [])}


def _session_event(conn, task, kind, *, actor, agent, summary, detail, item=None, model=None,
                   tokens_in=None, tokens_out=None, now=None, transaction_id=None):
    from . import execution
    from .execution_cmd import append_event
    statuses = {"completed": "COMPLETED", "handed_off": "COMPLETED", "cancelled": "CANCELLED", "blocked": "BLOCKED"}
    status = ("STARTED" if kind == "WORK_SESSION_STARTED" or detail.get("action") == "resume" else
              "PENDING" if kind == "WORK_SESSION_UPDATED" else statuses.get(detail.get("reason"), "PENDING"))
    operation = "START" if kind == "WORK_SESSION_STARTED" else "END" if kind == "WORK_SESSION_ENDED" else "RECORD"
    if detail.get("execution_schema") == execution.SCHEMA:
        event_id = append_event(conn, task, kind, actor=actor, agent=agent, summary=summary, payload=detail,
                                item=item, producer="work_session", operation=operation, result_status=status,
                                now=now, transaction_id=transaction_id)
        conn.execute("UPDATE task_event SET model_used=?,tokens_input=?,tokens_output=? WHERE id=?",
                     (model or "", tokens_in, tokens_out, event_id))
    else:
        # Existing unscoped sessions keep their legacy representation and pairing semantics.
        now = now or dbmod.now_iso()
        data = event_contract.add_event_semantics(detail, event_type=kind, operation=operation,
                                                 result_status=status, producer="work_session")
        event_id = conn.execute("INSERT INTO task_event (task_id,event_type,actor_role,actor_agent,model_used,tokens_input,tokens_output,work_item_id,detail_json,summary,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
             (task["task_id"], kind, actor, agent, model or "", tokens_in, tokens_out, item,
              json.dumps(data, ensure_ascii=False), summary, now)).lastrowid
        conn.execute("UPDATE task SET updated_at=? WHERE task_id=?", (now, task["task_id"]))
    return event_id


def cmd_work_start(args) -> int:
    from . import execution
    from .execution_cmd import _write_command, record_step, _text
    def write(conn, task, facts):
        actor = args.role or task["owner_role"] or DEFAULT_ROLE
        agent = args.agent if args.agent is not None else (task["owner_agent"] or "")
        item = getattr(args, "item", None)
        if item:
            row = conn.execute("SELECT status FROM work_item WHERE task_id=? AND item_id=?", (args.task, item)).fetchone()
            if row is None or row["status"] == "COMPLETED":
                raise ValueError("WORK_ITEM_UNAVAILABLE: item must belong to this task and not be completed")
        from . import security_authority as authority
        if item:
            authority.check_work(conn, args.task, item)
        elif facts["plan"] is None:
            authority.check_effect(conn, args.task, authority.context_from_args(args))
        sid = f"WORK-{uuid.uuid4().hex}"
        payload = {"session_id": sid, "producer": "work_session"}
        if facts["plan"] is None and not item:
            payload["security_context"] = authority.context_from_args(args)
        now, transaction_id = dbmod.now_iso(), uuid.uuid4().hex
        step_id = getattr(args, "step", None)
        if facts["plan"] is not None:
            if getattr(args, "plan_version", None) != facts["plan_version"]:
                raise ValueError("PLAN_VERSION_CHANGED: pass --plan-version from work show")
            if not step_id:
                step_id = (facts["current_step"] or {}).get("id")
            step = next((s for s in facts["steps"] if s["id"] == step_id), None)
            if step is None:
                raise ValueError("STEP_REQUIRED: select an explicit --step from the plan")
            from .work_units import read as read_units, checked_item, require_dependencies
            unit = read_units(conn, args.task)["units"].get(item) if item else None
            linked = bool(unit and unit["waiting_step_id"] == step_id)
            fix = linked and unit["spec"]["kind"] == "FIX"
            if linked:
                row = checked_item(conn, args.task, item)
                if row["status"] != "ACTIVE":
                    raise ValueError("WORK_NOT_CLAIMED: claim before starting a scoped Work participation")
                require_dependencies(conn, args.task, row)
            if not fix:
                authority.check_step(conn, args.task, step)
            if actor not in (unit["spec"]["roles"] if linked else step["roles"]):
                raise ValueError("PARTICIPATION_ROLE_MISMATCH: role must belong to this step or scoped Fix")
            if item and item not in step["work_item_ids"] and not linked:
                raise ValueError("WORK_ITEM_STEP_MISMATCH: explicitly associate this WorkItem")
            summary = _text(args.summary, "session summary")
            scope = _text(getattr(args, "scope", None) or step["scope"], "participation scope")
            if step["status"] == "PLANNED":
                record_step(conn, task, facts, step_id=step_id, plan_version=facts["plan_version"], action="start",
                            actor=actor, summary=summary, now=now, transaction_id=transaction_id)
            elif step["status"] != "ACTIVE" and not (fix and step["status"] == "WAITING"):
                raise ValueError("STEP_NOT_ACTIVE: only scoped Fix participants run while the parent waits")
            if task["current_state"] == "BLOCKED":
                raise ValueError("TASK_BLOCKED: resolve the existing Task wait first")
            payload.update(execution_schema=execution.SCHEMA, plan_version=facts["plan_version"], step_id=step_id,
                           scope=scope, effect_scope="record_only")
        elif step_id or getattr(args, "plan_version", None) is not None:
            raise ValueError("EXECUTION_PLAN_REQUIRED: record work plan first")
        for opened in _open_sessions(conn, args.task):
            if opened.get("actor_role") != actor:
                continue
            detail = _event_detail(opened)
            if detail is None:
                raise ValueError("WORK_SESSION_AMBIGUOUS: inspect damaged START metadata")
            if (facts["plan"] is None or not detail.get("step_id") or
                    (detail.get("step_id") == step_id and opened.get("work_item_id") == item
                     and (opened.get("actor_agent") or "") == agent)):
                raise ValueError("WORK_SESSION_ALREADY_OPEN: end or resume the existing participation")
        event_id = _session_event(conn, task, "WORK_SESSION_STARTED", actor=actor, agent=agent, item=item,
                    summary=args.summary, detail=payload, model=args.model, now=now, transaction_id=transaction_id)
        if facts["plan"] is None:
            return f"Work session started: {event_id} (session_id={sid})"
        return {"event_id": event_id, "session_id": sid, "participation_id": sid if step_id else None,
                "plan_version": facts["plan_version"] or None, "step_id": step_id, "runtime_status": "UNKNOWN"}
    return _write_command(args, write, allow_legacy=True)


def cmd_work_update(args) -> int:
    from . import execution
    from .execution_cmd import _write_command, _text
    def write(conn, task, facts):
        start = _selected_start(conn, task, args)
        detail = _event_detail(start)
        if detail.get("execution_schema") != execution.SCHEMA:
            raise ValueError("LEGACY_SESSION: finish it explicitly; do not invent a past step binding")
        participation = next((p for p in facts["participations"] if p["participation_id"] == detail["session_id"]), None)
        if participation is None:
            raise ValueError("PARTICIPATION_UNAVAILABLE")
        target = {"wait": "ACTIVE", "resume": "WAITING"}[args.action]
        if participation["status"] != target:
            raise ValueError(f"PARTICIPATION_TRANSITION_INVALID: {participation['status']} -> {args.action}")
        step = next(s for s in facts["steps"] if s["id"] == detail["step_id"])
        from .work_units import read as read_units
        unit = read_units(conn, args.task)["units"].get(start.get("work_item_id"))
        fix = bool(unit and unit["spec"]["kind"] == "FIX" and unit["waiting_step_id"] == step["id"])
        if args.action == "resume" and ((step["status"] != "ACTIVE" and not (fix and step["status"] == "WAITING")) or task["current_state"] == "BLOCKED"):
            raise ValueError("STEP_NOT_ACTIVE: resolve the Task/step wait before resuming a participation")
        if args.action == "resume":
            from . import security_authority as authority
            if start.get("work_item_id"):
                authority.check_work(conn, args.task, start["work_item_id"])
            else:
                authority.check_step(conn, args.task, step)
        summary = _text(args.summary, "session summary")
        wait_reason = _text(args.wait_reason, "wait_reason", required=args.action == "wait")
        expected = _text(args.expected_next, "expected_next_actor", required=args.action == "wait")
        if args.action == "resume" and (wait_reason or expected):
            raise ValueError("wait fields only apply to action=wait")
        payload = {key: detail[key] for key in ("execution_schema", "session_id", "step_id", "plan_version")}
        payload.update(start_event_id=start["id"], action=args.action, wait_reason=wait_reason,
                       expected_next_actor=expected, **_outcome(args, conn, args.task))
        event_id = _session_event(conn, task, "WORK_SESSION_UPDATED", actor=start["actor_role"],
                    agent=start.get("actor_agent") or "", item=start.get("work_item_id"), summary=summary, detail=payload)
        return {"event_id": event_id, "participation_id": detail["session_id"], "action": args.action}
    return _write_command(args, write)


def cmd_work_end(args) -> int:
    from . import execution
    from .execution_cmd import _write_command, _text
    cleanup_binding = {}
    def write(conn, task, facts):
        if args.reason not in _REASON_CODES:
            raise ValueError("invalid work end reason")
        start = _selected_start(conn, task, args)
        source = _event_detail(start)
        sid = source.get("session_id", "")
        payload = {"session_id": sid, "start_event_id": start["id"], "reason": args.reason,
                   "wait_reason": args.wait_reason or "", "expected_next_actor": args.expected_next or "",
                   "producer": "work_session", **_outcome(args, conn, args.task)}
        if source.get("execution_schema") == execution.SCHEMA:
            if facts["terminal"]:
                raise ValueError("TASK_NOT_CURRENT: explicit-plan terminal participation is historical")
            _text(args.summary, "session end summary")
            if args.reason in {"waiting_human", "waiting_agent", "blocked"}:
                _text(payload["wait_reason"], "wait_reason")
            if args.reason in {"waiting_human", "waiting_agent", "blocked", "handed_off"}:
                _text(payload["expected_next_actor"], "expected_next_actor")
            payload.update({key: source[key] for key in ("execution_schema", "step_id", "plan_version")})
            payload["result"] = payload["result"] or args.summary
        from . import security_authority as authority
        ctx = source.get("security_context")
        if start.get("work_item_id"):
            _, ctx = authority.work_context(conn, args.task, start["work_item_id"])
        elif source.get("step_id") and facts.get("plan"):
            step = next(s for s in facts["steps"] if s["id"] == source["step_id"])
            ctx = authority.step_context(step)
        if ctx:
            refs = [ref for ref in payload.get("evidence_refs", []) if ref.startswith("evidence/")]
            authority.classify_evidence(conn, args.task, authority.task_directory(conn, args.task), ctx, refs, actor=start["actor_role"])
        event_id = _session_event(conn, task, "WORK_SESSION_ENDED", actor=start["actor_role"],
            agent=start.get("actor_agent") or "", item=start.get("work_item_id"), summary=args.summary,
            detail=payload, model=args.model, tokens_in=args.tokens_in, tokens_out=args.tokens_out)
        cleanup_binding.update(project_id=str(task["project_id"] or ""), task_id=args.task, run_id=sid)
        if source.get("execution_schema") != execution.SCHEMA:
            return f"Work session ended: {event_id} (reason={args.reason})"
        return {"event_id": event_id, "session_id": sid, "reason": args.reason}
    # Preserve the existing owned legacy-END recovery, without reopening a terminal Task.
    code = _write_command(args, write, allow_legacy=True, allow_legacy_end=True)
    # Cleanup remains after the committed END, and cannot falsify/roll back that observation.
    if code == 0 and cleanup_binding.get("run_id"):
        from . import temp_artifacts
        try:
            cleanup = temp_artifacts.cleanup_run_if_registered(**cleanup_binding)
            if cleanup.get("status") == temp_artifacts.STATUS_CLEANUP_PENDING:
                print(f"TEMP_CLEANUP_PENDING: {cleanup.get('error') or 'cleanup failed'}", file=sys.stderr)
        except Exception as exc:
            print(f"TEMP_CLEANUP_PENDING: {type(exc).__name__}: {exc}", file=sys.stderr)
    return code


def _outcome_arguments(parser):
    parser.add_argument("--result", default="", help="actual result, not a formal Verification/Review PASS")
    parser.add_argument("--finding", action="append", default=[])
    parser.add_argument("--decision", action="append", default=[], help="decision notes; not human approval")
    parser.add_argument("--evidence", action="append", default=[], help="recorded reference; event:ID must belong to this Task")


def add_work_subparsers(work_parser) -> None:
    sub = work_parser.add_subparsers(dest="subcommand", required=True)
    from .execution_cmd import add_execution_subparsers
    add_execution_subparsers(sub)
    start = sub.add_parser("start", help="Start a distinct work participation (does not observe agent liveness)")
    start.add_argument("--item", default=None)
    start.add_argument("--step", default=None)
    start.add_argument("--plan-version", type=int, default=None)
    start.add_argument("--scope", default=None)
    start.add_argument("--model", default=None)
    start.add_argument("--summary", default="")
    from .security_authority import add_context_args
    add_context_args(start, investigation=True)
    end = sub.add_parser("end", help="End one explicit work participation; does not complete its step or Task")
    end.add_argument("--session", default=None, help="required when actor has several open participations")
    end.add_argument("--reason", required=True, choices=list(_REASON_CODES))
    end.add_argument("--wait-reason", default=None)
    end.add_argument("--expected-next", default=None)
    end.add_argument("--model", default=None)
    end.add_argument("--tokens-in", type=int, default=None)
    end.add_argument("--tokens-out", type=int, default=None)
    end.add_argument("--summary", default="")
    update = sub.add_parser("update", help="Record waiting/resumption within an existing participation")
    update.add_argument("--session", required=True)
    update.add_argument("--action", required=True, choices=["wait", "resume"])
    update.add_argument("--summary", required=True)
    update.add_argument("--wait-reason", default="")
    update.add_argument("--expected-next", default="")
    for parser in (end, update):
        _outcome_arguments(parser)
    for parser, command in ((start, cmd_work_start), (end, cmd_work_end), (update, cmd_work_update)):
        parser.add_argument("--task", required=True)
        parser.add_argument("--role", default=None, help="actor role; named --session defaults to its recorded role")
        parser.add_argument("--agent", default=None, help="actor agent; named --session defaults to its recorded agent")
        parser.add_argument("--db", default=None)
        parser.set_defaults(func=command)
