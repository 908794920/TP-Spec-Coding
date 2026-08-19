# -*- coding: utf-8 -*-
"""TP-Spec-Coding V5.2.4 work 命令组（M2）。

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
from typing import Optional

from . import db as dbmod

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


def _event_detail(row) -> dict:
    raw = row["detail_json"] if row and "detail_json" in row.keys() else ""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _open_session_for_role(conn, task_id: str, actor_role: str):
    """返回该 task+role 最近的未结束 work session；兼容旧事件无 session_id。"""
    rows = conn.execute(
        "SELECT id,event_type,actor_role,detail_json,created_at FROM task_event "
        "WHERE task_id=? AND event_type IN ('WORK_SESSION_STARTED','WORK_SESSION_ENDED') "
        "AND actor_role=? ORDER BY id",
        (task_id, actor_role),
    ).fetchall()
    open_by_id = {}
    legacy_open = None
    for row in rows:
        detail = _event_detail(row)
        sid = str(detail.get("session_id") or "")
        if row["event_type"] == "WORK_SESSION_STARTED":
            if sid:
                open_by_id[sid] = row
            else:
                legacy_open = row
        else:
            if sid:
                open_by_id.pop(sid, None)
            elif legacy_open is not None:
                legacy_open = None
    if open_by_id:
        return sorted(open_by_id.items(), key=lambda pair: pair[1]["id"])[-1]
    if legacy_open is not None:
        return ("", legacy_open)
    return None


def cmd_work_start(args) -> int:
    task_id = args.task
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {task_id}", file=sys.stderr)
            return 4
        actor_role = args.role or task["owner_role"] or DEFAULT_ROLE
        actor_agent = args.agent or task["owner_agent"] or ""
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
        detail = {"session_id": session_id}
        now = dbmod.now_iso()
        with dbmod.transactional(conn):
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
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {task_id}", file=sys.stderr)
            return 4
        actor_role = args.role or task["owner_role"] or DEFAULT_ROLE
        actor_agent = args.agent or task["owner_agent"] or ""
        open_session = _open_session_for_role(conn, task_id, actor_role)
        if open_session is None:
            print(
                f"ERROR: no open work session for {actor_role}; run 'tp-spec work start' first",
                file=sys.stderr,
            )
            return 5
        session_id, start_row = open_session
        # 旧账本可能没有 session_id；新 END 明确记录关联 start_event_id，避免伪造 ID。
        detail = {
            "session_id": session_id,
            "start_event_id": start_row["id"],
            "reason": args.reason,
            "wait_reason": args.wait_reason or "",
            "expected_next_actor": args.expected_next or "",
        }
        now = dbmod.now_iso()
        with dbmod.transactional(conn):
            cur = conn.execute(
                """
                INSERT INTO task_event
                  (task_id, event_type, actor_role, actor_agent, model_used,
                   tokens_input, tokens_output, detail_json, summary, created_at)
                VALUES (?, 'WORK_SESSION_ENDED', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    actor_role,
                    actor_agent,
                    args.model or "",
                    args.tokens_in,
                    args.tokens_out,
                    json.dumps(detail, ensure_ascii=False),
                    args.summary,
                    now,
                ),
            )
            event_id = cur.lastrowid
        # reason=blocked 仅记录事件，不自动转 BLOCKED（状态流转必须显式 task transition）
        print(f"Work session ended: {event_id} (reason={args.reason})")
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
