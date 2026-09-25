# -*- coding: utf-8 -*-
"""Scoped Fix creation and read-only repair history.

Explicit-plan repairs reuse a Work identity and preserve the parent's step.
Legacy rework open remains available only for tasks without an explicit plan.
"""

from __future__ import annotations

import json
import sys
from typing import List, Optional

from . import db as dbmod

DEFAULT_ROLE = "tp-software-lifecycle"
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
        from .execution_cmd import load_current
        _, facts = load_current(conn, task_id, allow_legacy=True)
        if facts["plan"]:
            print("ERROR: use rework fix for an explicit-plan repair; rework open cannot rewind its parent", file=sys.stderr)
            return 2
        actor_role = args.role or task["owner_role"] or DEFAULT_ROLE
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
        # B-13 W5：审查包复用告警（复用不替代 VERIFYING，每次复用动作发生时展示）
        print(f"\n{w5_warning()}\n")
        return 0
    finally:
        conn.close()


def cmd_rework_list(args) -> int:
    task_id = args.task
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect_readonly(db_path)
    try:
        conn.execute("BEGIN")
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
        from .work_units import read
        units = [u for u in read(conn, task_id)["units"].values() if u["spec"]["kind"] == "FIX"]
        for unit in units:
            print(f"  {unit['item_id']} FIX issue={unit['spec']['issue_key']} step={unit['waiting_step_id']} "
                  f"attempt={unit['attempt']} status={unit['recorded_state']} received={bool(unit['receipt'])}")
        if not rows:
            if not units:
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


def cmd_rework_fix(args) -> int:
    from .execution_cmd import _write_command
    from .workitem_cmd import _json_file
    from . import work_units as units
    def write(conn, task, facts):
        from .security_authority import identifier
        args.id = identifier(args.id, "work item id")
        units._text(args.summary, "summary")
        raw = _json_file(args.file)
        if not isinstance(raw, dict):
            raise ValueError("FIX_SPEC_OBJECT_REQUIRED")
        if raw.get("step_id") != args.step:
            raise ValueError("FIX_STEP_MISMATCH")
        spec = units.normalize_spec(conn, task, facts, raw, item_id=args.id, kind="FIX", issue=units._text(args.issue, "issue key"))
        spec["cause"] = args.cause
        # Requirement changes are not defects. The scope refs/AC and P4 authority
        # context must refer to the already authorized Task, never this proposal.
        return units.create(conn, task, facts, item_id=args.id, title=args.summary,
                            spec=spec, actor=args.role, agent=args.agent)
    return _write_command(args, write)


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

    fix = sub.add_parser("fix", help="Create/reuse a scoped Fix Work at the current parent step")
    fix.add_argument("--task", required=True)
    fix.add_argument("--id", required=True, help="Globally unique Work ID, e.g. TASK-ID-FIX01")
    fix.add_argument("--issue", required=True, help="Stable issue identity within this Task")
    fix.add_argument("--step", required=True)
    fix.add_argument("--file", required=True, help="Scoped Work JSON; references existing Task scope")
    fix.add_argument("--summary", required=True)
    fix.add_argument("--cause", choices=[c for c in _CAUSE_TYPES if c not in {"REQUIREMENT_CHANGE", "DEPENDENCY_CHANGE"}], default="IMPLEMENTATION_DEFECT")
    fix.add_argument("--role", required=True)
    fix.add_argument("--agent", required=True)
    fix.add_argument("--db", default=None)
    fix.set_defaults(func=cmd_rework_fix)
