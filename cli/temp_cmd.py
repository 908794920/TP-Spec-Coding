# -*- coding: utf-8 -*-
"""TP-Spec-Coding V5.3.1 临时工件维护命令。"""
from __future__ import annotations

import json
from typing import Any, Dict

from . import db as dbmod
from . import temp_artifacts


def _emit(payload: Dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(json.dumps(payload, ensure_ascii=False))


def _validate_runtime_task(db_path: str, project_id: str, task_id: str) -> None:
    """显式 Runtime DB 存在时，只读确认 Task 所属项目，避免伪造 ownership。"""
    conn = dbmod.connect_readonly(db_path)
    try:
        row = conn.execute(
            "SELECT task_id, project_id FROM task WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(f"task not found in runtime: {task_id}")
    if str(row["project_id"] or "") != project_id:
        raise ValueError(
            f"task project mismatch: task={task_id} runtime={row['project_id']} requested={project_id}"
        )


def cmd_temp_create(args) -> int:
    _validate_runtime_task(args.db, args.project, args.task)
    result = temp_artifacts.create_run_root(
        project_id=args.project,
        task_id=args.task,
        creator_role=args.role,
        creator_agent=args.agent or "",
        run_id=args.run_id,
    )
    _emit(result, args.json)
    return 0


def cmd_temp_cleanup(args) -> int:
    result = temp_artifacts.cleanup_run(
        project_id=args.project,
        task_id=args.task,
        run_id=args.run_id,
    )
    _emit(result, args.json)
    return 0 if result.get("status") == temp_artifacts.STATUS_CLEANED else 6


def cmd_temp_summary(args) -> int:
    rows = temp_artifacts.list_records()
    if args.project:
        rows = [row for row in rows if row.get("project_id") == args.project]
    if args.task:
        rows = [row for row in rows if row.get("task_id") == args.task]
    _emit(temp_artifacts.summarize_records(rows), args.json)
    return 0


def cmd_temp_orphan_check(args) -> int:
    result = temp_artifacts.orphan_report(
        workspace_root=args.workspace_root,
        project_id=args.project,
        task_id=args.task,
        db_path=args.db,
    )
    _emit(result, args.json)
    return 0


def add_temp_subparsers(subparsers) -> None:
    parser = subparsers.add_parser("temp", help="Owned temporary artifact management")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_create = sub.add_parser("create", help="Create an owned system-temp run root")
    p_create.add_argument("--project", required=True)
    p_create.add_argument("--task", required=True)
    p_create.add_argument("--role", required=True)
    p_create.add_argument("--agent", required=False, default=None)
    p_create.add_argument("--run-id", required=False, default=None)
    p_create.add_argument("--db", required=True, help="explicit Runtime DB used to validate Task ownership")
    p_create.add_argument("--json", action="store_true")
    p_create.set_defaults(func=cmd_temp_create)

    p_cleanup = sub.add_parser("cleanup", help="Clean one explicitly owned temp run")
    p_cleanup.add_argument("--project", required=True)
    p_cleanup.add_argument("--task", required=True)
    p_cleanup.add_argument("--run-id", required=True)
    p_cleanup.add_argument("--json", action="store_true")
    p_cleanup.set_defaults(func=cmd_temp_cleanup)

    p_summary = sub.add_parser("summary", help="Summarize machine-local temp ownership records")
    p_summary.add_argument("--project", required=False, default=None)
    p_summary.add_argument("--task", required=False, default=None)
    p_summary.add_argument("--json", action="store_true")
    p_summary.set_defaults(func=cmd_temp_summary)

    p_orphan = sub.add_parser("orphan-check", help="Report owned/unmanaged temp candidates without deleting")
    p_orphan.add_argument("--workspace-root", required=False, default=None)
    p_orphan.add_argument("--project", required=False, default=None)
    p_orphan.add_argument("--task", required=False, default=None)
    p_orphan.add_argument("--db", required=False, default=None)
    p_orphan.add_argument("--json", action="store_true")
    p_orphan.set_defaults(func=cmd_temp_orphan_check)
