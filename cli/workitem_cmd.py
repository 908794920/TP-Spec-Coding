# -*- coding: utf-8 -*-
"""TP-Spec-Coding V5.0 workitem 命令组（M2）。

包含：
- workitem create / claim / complete / release / list

核心保证：
- create：单事务 INSERT work_item(status='PENDING')
- claim：UPDATE status='ACTIVE', owner_role, owner_agent
- complete：UPDATE status='COMPLETED'
- release：UPDATE status='PENDING', owner_role=NULL, owner_agent=NULL
- depends/paths/acceptance 以 JSON 存入对应字段
- workitem 不记录 task_event（仅操作 work_item 表）
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
    consistency = "NEEDS_RECONCILIATION" if issues else ("RECORDED" if items else "NOT_RECORDED")
    summary = (f"WorkItem 登记：待处理 {counts['PENDING']} / 已认领 {counts['ACTIVE']} / 已完成 {counts['COMPLETED']}；"
               f"{consistency}。只代表该任务里程碑记录，不是整任务/项目验收或进程存活。")
    if issues:
        summary += " 待核对：" + "; ".join(issues)
    return {"source": "work_item", "completion_scope": "task_work_items_only", "current": current,
            "counts": counts, "consistency": consistency, "issues": issues,
            "items": [{key: item.get(key) for key in ("item_id", "title", "status", "owner_role",
                       "owner_agent", "depends_on", "unresolved_dependencies", "current", "updated_at")}
                      for item in items], "summary": summary}


def cmd_workitem_create(args) -> int:
    task_id = args.task
    item_id = args.id
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = conn.execute("SELECT task_id FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {task_id}", file=sys.stderr)
            return 4
        existing = conn.execute(
            "SELECT item_id FROM work_item WHERE item_id = ? AND task_id = ?",
            (item_id, task_id),
        ).fetchone()
        if existing is not None:
            print(f"ERROR: work item already exists: {item_id}", file=sys.stderr)
            return 5
        depends = _split_csv(args.depends)
        paths = _split_csv(args.paths)
        acceptance = _split_csv(args.acceptance)
        now = dbmod.now_iso()
        with dbmod.transactional(conn):
            conn.execute(
                """
                INSERT INTO work_item
                  (item_id, task_id, title, status, owner_role, owner_agent,
                   depends_on_json, allowed_paths_json, acceptance_refs_json,
                   created_at, updated_at)
                VALUES (?, ?, ?, 'PENDING', NULL, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    task_id,
                    args.title or "",
                    json.dumps(depends, ensure_ascii=False),
                    json.dumps(paths, ensure_ascii=False),
                    json.dumps(acceptance, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        print(f"Work item created: {item_id} (PENDING)")
        return 0
    finally:
        conn.close()


def cmd_workitem_claim(args) -> int:
    task_id = args.task
    item_id = args.id
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        item = conn.execute(
            "SELECT * FROM work_item WHERE item_id = ? AND task_id = ?",
            (item_id, task_id),
        ).fetchone()
        if item is None:
            print(f"ERROR: work item not found: {item_id}", file=sys.stderr)
            return 4
        if item["status"] == "COMPLETED":
            print(f"ERROR: cannot claim completed work item: {item_id}", file=sys.stderr)
            return 5
        now = dbmod.now_iso()
        with dbmod.transactional(conn):
            conn.execute(
                """
                UPDATE work_item SET
                  status = 'ACTIVE', owner_role = ?, owner_agent = ?, updated_at = ?
                WHERE item_id = ? AND task_id = ?
                """,
                (args.role, args.agent, now, item_id, task_id),
            )
        print(f"Work item claimed: {item_id} (owner={args.role}/{args.agent})")
        return 0
    finally:
        conn.close()


def cmd_workitem_complete(args) -> int:
    task_id = args.task
    item_id = args.id
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        item = conn.execute(
            "SELECT * FROM work_item WHERE item_id = ? AND task_id = ?",
            (item_id, task_id),
        ).fetchone()
        if item is None:
            print(f"ERROR: work item not found: {item_id}", file=sys.stderr)
            return 4
        if item["status"] == "COMPLETED":
            print(f"ERROR: work item already completed: {item_id}", file=sys.stderr)
            return 5
        now = dbmod.now_iso()
        with dbmod.transactional(conn):
            conn.execute(
                """
                UPDATE work_item SET status = 'COMPLETED', updated_at = ?
                WHERE item_id = ? AND task_id = ?
                """,
                (now, item_id, task_id),
            )
        print(f"Work item completed: {item_id}")
        return 0
    finally:
        conn.close()


def cmd_workitem_release(args) -> int:
    task_id = args.task
    item_id = args.id
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        item = conn.execute(
            "SELECT * FROM work_item WHERE item_id = ? AND task_id = ?",
            (item_id, task_id),
        ).fetchone()
        if item is None:
            print(f"ERROR: work item not found: {item_id}", file=sys.stderr)
            return 4
        if item["status"] == "COMPLETED":
            print(f"ERROR: cannot release completed work item: {item_id}", file=sys.stderr)
            return 5
        now = dbmod.now_iso()
        with dbmod.transactional(conn):
            conn.execute(
                """
                UPDATE work_item SET
                  status = 'PENDING', owner_role = NULL, owner_agent = NULL, updated_at = ?
                WHERE item_id = ? AND task_id = ?
                """,
                (now, item_id, task_id),
            )
        print(f"Work item released: {item_id} (PENDING)")
        return 0
    finally:
        conn.close()


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
    p_complete.set_defaults(func=cmd_workitem_complete)

    # workitem release
    p_release = sub.add_parser("release", help="Release a claimed work item back to PENDING")
    p_release.add_argument("--task", required=True, help="task id")
    p_release.add_argument("--id", required=True, help="work item id")
    p_release.add_argument("--db", required=False, default=None)
    p_release.set_defaults(func=cmd_workitem_release)

    # workitem list
    p_list = sub.add_parser("list", help="List work items for a task")
    p_list.add_argument("--task", required=True, help="task id")
    p_list.add_argument("--status", required=False, default=None, choices=["PENDING", "ACTIVE", "COMPLETED"])
    p_list.add_argument("--db", required=False, default=None)
    p_list.set_defaults(func=cmd_workitem_list)
