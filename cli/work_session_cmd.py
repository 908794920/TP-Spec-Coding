# -*- coding: utf-8 -*-
"""TP-Spec-Coding V5.3.2 work 命令组（M2）。

包含：
- work start / end

核心保证：
- work start：单事务插入 WORK_SESSION_STARTED 事件
- work end：单事务插入 WORK_SESSION_ENDED 事件，reason 受控
- reason=blocked 不自动转 BLOCKED（状态流转必须显式 task transition）
- actor_role 默认回退到 task.owner_role；actor_agent 可显式记录，缺省沿用 task.owner_agent
- 新事件用 detail_json.session_id 关联 START/END；同一 task+role 只允许一个未结束会话
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
               for key in ("actor_role", "actor_agent")):
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
            if row["event_type"] in {"WORK_SESSION_STARTED", "WORK_SESSION_ENDED"}]
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


def _open_session_for_role(conn, task_id: str, actor_role: str):
    rows = conn.execute(
        "SELECT * FROM task_event WHERE task_id=? "
        "AND event_type IN ('WORK_SESSION_STARTED','WORK_SESSION_ENDED') ORDER BY id",
        (task_id,),
    ).fetchall()
    paired = pair_work_sessions(rows)
    opened = [row for row in paired["unmatched_starts"] if row.get("actor_role") == actor_role]
    if len(opened) > 1 or any(_event_detail(row) is None for row in opened):
        raise ValueError("WORK_SESSION_AMBIGUOUS: inspect original START/END records; history was not changed")
    if not opened:
        return None
    return (_event_detail(opened[0]).get("session_id", ""), opened[0])


def cmd_work_start(args) -> int:
    task_id = args.task
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        with dbmod.transactional(conn):
            task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
            if task is None:
                print(f"ERROR: task not found: {task_id}", file=sys.stderr)
                return 4
            from .event_policies import is_task_retired
            if task["current_state"] in {"COMPLETED", "CANCELLED"} or is_task_retired(conn, task_id):
                print("ERROR: TASK_NOT_CURRENT: cannot start work on terminal/retired task", file=sys.stderr)
                return 5
            if args.item:
                item = conn.execute("SELECT status FROM work_item WHERE task_id=? AND item_id=?",
                                    (task_id, args.item)).fetchone()
                if item is None or item["status"] == "COMPLETED":
                    print("ERROR: WORK_ITEM_UNAVAILABLE: item must belong to this task and not be completed", file=sys.stderr)
                    return 5
            actor_role = args.role or task["owner_role"] or DEFAULT_ROLE
            actor_agent = args.agent if args.agent is not None else (task["owner_agent"] or "")
            open_session = _open_session_for_role(conn, task_id, actor_role)
            if open_session is not None:
                sid, row = open_session
                label = sid or f"legacy-event-{row['id']}"
                print(
                    f"ERROR: open work session already exists for {actor_role}: {label}; "
                    "end it explicitly before starting another",
                    file=sys.stderr,
                )
                return 5
            session_id = f"WORK-{uuid.uuid4().hex}"
            detail = event_contract.add_event_semantics({"session_id": session_id, "producer": "work_session"}, event_type="WORK_SESSION_STARTED", operation="START", result_status="STARTED", producer="work_session")
            now = dbmod.now_iso()
            cur = conn.execute(
                """
                INSERT INTO task_event
                  (task_id, event_type, actor_role, actor_agent, model_used,
                   work_item_id, detail_json, summary, created_at)
                VALUES (?, 'WORK_SESSION_STARTED', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id, actor_role, actor_agent, args.model or "", args.item,
                    json.dumps(detail, ensure_ascii=False), args.summary, now,
                ),
            )
            event_id = cur.lastrowid
        print(f"Work session started: {event_id} (session_id={session_id})")
        return 0
    finally:
        conn.close()


def cmd_work_end(args) -> int:
    task_id = args.task
    if args.reason not in _REASON_CODES:
        print(
            f"ERROR: invalid reason '{args.reason}' (must be one of: {', '.join(_REASON_CODES)})",
            file=sys.stderr,
        )
        return 2
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        with dbmod.transactional(conn):
            task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
            if task is None:
                print(f"ERROR: task not found: {task_id}", file=sys.stderr)
                return 4
            actor_role = args.role or task["owner_role"] or DEFAULT_ROLE
            actor_agent = args.agent if args.agent is not None else (task["owner_agent"] or "")
            open_session = _open_session_for_role(conn, task_id, actor_role)
            if open_session is None:
                print(
                    f"ERROR: no open work session for {actor_role}; run 'tp-spec work start' first",
                    file=sys.stderr,
                )
                return 5
            session_id, start_row = open_session
            if actor_agent != (start_row.get("actor_agent") or ""):
                print("ERROR: WORK_SESSION_OWNER_MISMATCH: END must match the recorded START agent", file=sys.stderr)
                return 5
            # 旧账本可能没有 session_id；新 END 明确记录关联 start_event_id，避免伪造 ID。
            end_status = {
                "blocked": "BLOCKED",
                "cancelled": "CANCELLED",
                "paused": "PENDING",
                "waiting_human": "PENDING",
                "waiting_agent": "PENDING",
                "interrupted": "PENDING",
                "completed": "COMPLETED",
                "handed_off": "COMPLETED",
            }[str(args.reason).lower()]
            detail = event_contract.add_event_semantics({
                "session_id": session_id,
                "start_event_id": start_row["id"],
                "reason": args.reason,
                "wait_reason": args.wait_reason or "",
                "expected_next_actor": args.expected_next or "",
                "producer": "work_session",
            }, event_type="WORK_SESSION_ENDED", operation="END", result_status=end_status, producer="work_session")
            now = dbmod.now_iso()
            cur = conn.execute(
                """
                INSERT INTO task_event
                  (task_id, event_type, actor_role, actor_agent, model_used,
                   tokens_input, tokens_output, work_item_id, detail_json, summary, created_at)
                VALUES (?, 'WORK_SESSION_ENDED', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    actor_role,
                    actor_agent,
                    args.model or "",
                    args.tokens_in,
                    args.tokens_out,
                    start_row.get("work_item_id"),
                    json.dumps(detail, ensure_ascii=False),
                    args.summary,
                    now,
                ),
            )
            event_id = cur.lastrowid
        # reason=blocked 仅记录事件，不自动转 BLOCKED（状态流转必须显式 task transition）
        print(f"Work session ended: {event_id} (reason={args.reason})")

        # Runtime END 已提交后再清理展示/测试临时工件；清理失败不得回滚真实 END 事实。
        if session_id:
            from . import temp_artifacts
            try:
                cleanup = temp_artifacts.cleanup_run_if_registered(
                    project_id=str(task["project_id"] or ""),
                    task_id=task_id,
                    run_id=session_id,
                )
                if cleanup.get("status") == temp_artifacts.STATUS_CLEANUP_PENDING:
                    print(
                        f"TEMP_CLEANUP_PENDING: run_id={session_id}: {cleanup.get('error') or 'cleanup failed'}",
                        file=sys.stderr,
                    )
            except Exception as exc:
                print(
                    f"TEMP_CLEANUP_PENDING: run_id={session_id}: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
        return 0
    finally:
        conn.close()


def add_work_subparsers(work_parser) -> None:
    """注册 work 命令组的子命令。"""
    sub = work_parser.add_subparsers(dest="subcommand", required=True)

    # work start
    p_start = sub.add_parser("start", help="Start a work session")
    p_start.add_argument("--task", required=True, help="task id")
    p_start.add_argument("--role", required=False, default=None, help="actor role (default: task.owner_role; subroles should pass explicitly)")
    p_start.add_argument("--agent", required=False, default=None, help="actor agent (default: task.owner_agent)")
    p_start.add_argument("--item", required=False, default=None, help="work item id")
    p_start.add_argument("--model", required=False, default=None, help="model used")
    p_start.add_argument("--summary", required=False, default="", help="session summary")
    p_start.add_argument("--db", required=False, default=None)
    p_start.set_defaults(func=cmd_work_start)

    # work end
    p_end = sub.add_parser("end", help="End a work session")
    p_end.add_argument("--task", required=True, help="task id")
    p_end.add_argument("--reason", required=True, choices=list(_REASON_CODES), help="end reason")
    p_end.add_argument("--wait-reason", required=False, default=None, help="wait reason code")
    p_end.add_argument("--expected-next", required=False, default=None, help="expected next actor role")
    p_end.add_argument("--model", required=False, default=None, help="model used")
    p_end.add_argument("--tokens-in", required=False, default=None, type=int, help="input tokens")
    p_end.add_argument("--tokens-out", required=False, default=None, type=int, help="output tokens")
    p_end.add_argument("--role", required=False, default=None, help="actor role (default: task.owner_role)")
    p_end.add_argument("--agent", required=False, default=None, help="actor agent (default: task.owner_agent)")
    p_end.add_argument("--summary", required=False, default="", help="session end summary")
    p_end.add_argument("--db", required=False, default=None)
    p_end.set_defaults(func=cmd_work_end)
