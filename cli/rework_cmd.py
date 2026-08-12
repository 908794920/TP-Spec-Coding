# -*- coding: utf-8 -*-
"""TP-Spec-Coding V5.0 rework 命令组（M2）。

包含：
- rework open / list

核心保证：
- rework open：单事务插入 REWORK 事件，detail_json 记录返工结构化字段
- cause 受控（10 类）
- 不自动改 task.current_state（返工可能落在 LOCAL_REWORK，无状态变更）
- actor_role 默认回退到 task.owner_role，actor_agent = --by
"""

from __future__ import annotations

import json
import sys
from typing import List, Optional

from . import db as dbmod
from .reuse_warnings import w5_warning


# rework cause 受控集合（与 rework 规范一致）
_CAUSE_TYPES = (
    "REQUIREMENT_GAP",
    "REQUIREMENT_CHANGE",
    "ASSUMPTION_INVALID",
    "DESIGN_DEFECT",
    "IMPLEMENTATION_DEFECT",
    "TEST_GAP",
    "REVIEW_FINDING",
    "ENVIRONMENT_ISSUE",
    "DEPENDENCY_CHANGE",
    "INTEGRATION_CONFLICT",
)


def _parse_items(items_arg: Optional[str]) -> List[str]:
    """解析 WI-01,WI-02 形式的字符串为列表。"""
    if not items_arg:
        return []
    return [s.strip() for s in items_arg.split(",") if s.strip()]


def cmd_rework_open(args) -> int:
    task_id = args.task
    if args.cause not in _CAUSE_TYPES:
        print(
            f"ERROR: invalid cause '{args.cause}' (must be one of: {', '.join(_CAUSE_TYPES)})",
            file=sys.stderr,
        )
        return 2
    if args.requirement_changed not in ("true", "false"):
        print(
            f"ERROR: --requirement-changed must be 'true' or 'false', got '{args.requirement_changed}'",
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
        actor_role = args.role or task["owner_role"] or "tp-architecture-design"
        actor_agent = args.by or task["owner_agent"] or ""
        affected_items = _parse_items(args.items)
        detail = {
            "from_stage": args.from_stage,
            "to_stage": args.to_stage,
            "cause_type": args.cause,
            "origin_stage": args.origin,
            "discovered_stage": args.discovered,
            "discovered_by": args.by,
            "requirement_changed": args.requirement_changed == "true",
            "affected_work_items": affected_items,
        }
        now = dbmod.now_iso()
        with dbmod.transactional(conn):
            cur = conn.execute(
                """
                INSERT INTO task_event
                  (task_id, event_type, actor_role, actor_agent, reason_code,
                   detail_json, summary, created_at)
                VALUES (?, 'REWORK', ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    actor_role,
                    actor_agent,
                    args.cause,
                    json.dumps(detail, ensure_ascii=False),
                    args.summary or f"rework: {args.from_stage} -> {args.to_stage} ({args.cause})",
                    now,
                ),
            )
            event_id = cur.lastrowid
        # 不自动改 task.current_state（返工可能落在 LOCAL_REWORK，无状态变更）
        print(f"Rework opened: {event_id} ({args.cause})")
        # V5.2.0 B-13 W5：审查包复用告警（复用不替代 VERIFYING，每次复用动作发生时展示）
        print(f"\n{w5_warning()}\n")
        return 0
    finally:
        conn.close()


def cmd_rework_list(args) -> int:
    task_id = args.task
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = conn.execute("SELECT task_id FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {task_id}", file=sys.stderr)
            return 4
        rows = conn.execute(
            """
            SELECT id, created_at, actor_role, actor_agent, reason_code,
                   detail_json, summary
            FROM task_event
            WHERE task_id = ? AND event_type = 'REWORK'
            ORDER BY id
            """,
            (task_id,),
        ).fetchall()
        if not rows:
            print(f"(no rework events for {task_id})")
            return 0
        print(f"rework events for {task_id} ({len(rows)}):")
        for r in rows:
            detail = None
            if r["detail_json"]:
                try:
                    detail = json.loads(r["detail_json"])
                except json.JSONDecodeError:
                    detail = None
            from_stage = detail.get("from_stage", "?") if detail else "?"
            to_stage = detail.get("to_stage", "?") if detail else "?"
            items = detail.get("affected_work_items", []) if detail else []
            items_str = ",".join(items) if items else "-"
            print(
                f"  #{r['id']} [{r['created_at']}] {from_stage} -> {to_stage} "
                f"cause={r['reason_code']} by={r['actor_agent'] or '-'} "
                f"items={items_str}"
            )
        return 0
    finally:
        conn.close()


def add_rework_subparsers(rework_parser) -> None:
    """注册 rework 命令组的子命令。"""
    sub = rework_parser.add_subparsers(dest="subcommand", required=True)

    # rework open
    p_open = sub.add_parser("open", help="Open a rework event")
    p_open.add_argument("--task", required=True, help="task id")
    p_open.add_argument("--from-stage", required=True, help="rework from stage")
    p_open.add_argument("--to-stage", required=True, help="rework to stage")
    p_open.add_argument(
        "--cause",
        required=True,
        choices=list(_CAUSE_TYPES),
        help="rework cause type",
    )
    p_open.add_argument("--origin", required=True, help="origin stage")
    p_open.add_argument("--discovered", required=True, help="discovered stage")
    p_open.add_argument("--by", required=True, help="discovered by agent")
    p_open.add_argument(
        "--requirement-changed",
        required=True,
        choices=["true", "false"],
        help="whether requirement changed",
    )
    p_open.add_argument("--items", required=False, default=None, help="affected work items (WI-01,WI-02)")
    p_open.add_argument("--role", required=False, default=None, help="actor role (default: task.owner_role)")
    p_open.add_argument("--summary", required=False, default="", help="rework summary")
    p_open.add_argument("--db", required=False, default=None)
    p_open.set_defaults(func=cmd_rework_open)

    # rework list
    p_list = sub.add_parser("list", help="List rework events for a task")
    p_list.add_argument("--task", required=True, help="task id")
    p_list.add_argument("--db", required=False, default=None)
    p_list.set_defaults(func=cmd_rework_list)
