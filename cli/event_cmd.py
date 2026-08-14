# -*- coding: utf-8 -*-
"""TP-Spec-Coding V5.0 event 命令组（M3 + M5-C）。

包含：
- event list（只读）：列出任务所有事件
- event add：追加业务事件（不入 STATE/WORK_SESSION/REWORK 主流程，用于补录 FACT/DECISION 等）
- event sync（M5-C）：回流 flush 追加的 events.jsonl 事件到 DB，同事务推进 task 表

核心保证：
- event add 的 type 必须在 Test-TpSpecTask.ps1 EventTypes 内
- actor 非空保证
- event sync 幂等（flush_id 去重），不变量 task.current_state == events.jsonl 末条 STATE.state
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import db as dbmod
from . import event_policies


# Final Hardening（Task 1）：事件类型由 cli/event_policies 单一来源推导，
# 禁止本模块维护独立 allowlist。event add 仅允许安全事实类。
_EVENT_TYPES = tuple(event_policies.allowed_event_add_types())


def cmd_event_list(args) -> int:
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
            SELECT id, created_at, event_type, from_state, to_state, actor_role, actor_agent,
                   model_used, work_item_id, reason_code, summary, detail_json, evidence_path
            FROM task_event
            WHERE task_id = ?
            ORDER BY id
            """,
            (task_id,),
        ).fetchall()
        if not rows:
            print(f"(no events for {task_id})")
            return 0
        print(f"events for {task_id} ({len(rows)}):")
        for r in rows:
            state_part = ""
            if r["from_state"] or r["to_state"]:
                state_part = f" {r['from_state'] or '-'} -> {r['to_state'] or '-'}"
            print(
                f"  #{r['id']} [{r['created_at']}] {r['event_type']}{state_part} "
                f"actor={r['actor_role'] or '-'}/{r['actor_agent'] or '-'} "
                f"| {r['summary'] or ''}"
            )
        return 0
    finally:
        conn.close()


def cmd_event_add(args) -> int:
    task_id = args.task
    # Final Hardening（INV-02/P0-1）：event add 不得产生任何治理事件。
    if event_policies.is_governance_event(args.type):
        print(
            f"ERROR: {event_policies.GOVERNANCE_EVENT_REQUIRES_TRUSTED_PRODUCER}: "
            f"event add cannot produce governance event '{args.type}'; "
            f"it must be produced by its trusted command "
            f"(e.g. 'tp-spec commit', 'tp-spec review record', 'tp-spec receipt record')",
            file=sys.stderr,
        )
        return 8
    if args.type not in _EVENT_TYPES:
        print(
            f"ERROR: invalid type '{args.type}' (must be one of: {', '.join(_EVENT_TYPES)})",
            file=sys.stderr,
        )
        return 2
    if not args.actor:
        print("ERROR: --actor is required and must be non-empty", file=sys.stderr)
        return 2
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {task_id}", file=sys.stderr)
            return 4
        # STATE 类型建议用 task transition，但允许 event add 补录历史
        # event_type 存储时用 args.type（已在 EventTypes 内）
        # detail_json 记录 state/next（若提供）
        detail = None
        if args.state or args.next:
            detail = {"state": args.state or "", "next": args.next or ""}
        now = dbmod.now_iso()
        with dbmod.transactional(conn):
            cur = conn.execute(
                """
                INSERT INTO task_event
                  (task_id, event_type, to_state, actor_role, summary, detail_json,
                   evidence_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    args.type,
                    args.state,
                    args.actor,
                    args.note,
                    json.dumps(detail, ensure_ascii=False) if detail else None,
                    args.evidence,
                    now,
                ),
            )
            event_id = cur.lastrowid
        print(f"Event added: {event_id} ({args.type})")
        return 0
    finally:
        conn.close()


def _load_handoff_json(task_dir: str) -> Optional[Dict[str, Any]]:
    """读取 <task_dir>/handoff.json，返回 dict 或 None（不存在）。

    用 utf-8-sig 容忍 BOM（PowerShell 5.1 Set-Content -Encoding UTF8 会写 BOM）。
    """
    handoff_path = os.path.join(task_dir, "handoff.json")
    if not os.path.isfile(handoff_path):
        return None
    try:
        with open(handoff_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _extract_existing_flush_ids(conn, task_id: str) -> set:
    """查询 DB 中已回流的 flush_id 集合（从 detail_json 解析提取）。"""
    rows = conn.execute(
        "SELECT detail_json FROM task_event WHERE task_id = ? AND detail_json LIKE ?",
        (task_id, '%"flush_id"%'),
    ).fetchall()
    existing = set()
    for r in rows:
        try:
            detail = json.loads(r["detail_json"]) if r["detail_json"] else {}
        except json.JSONDecodeError:
            continue
        fid = detail.get("flush_id")
        if fid:
            existing.add(fid)
    return existing


def _map_event_to_task_event(evt: Dict[str, Any], task_id: str, workflow_version: str,
) -> Tuple:
    """将 events.jsonl 中的 flush 追加事件映射为 task_event INSERT 参数元组。

    返回 (task_id, event_type, from_state, to_state, actor_role, actor_agent,
          summary, detail_json, evidence_path, created_at, workflow_version)
    """
    event_type = evt.get("type", "")
    if event_type == "STATE":
        to_state = evt.get("state")
    elif event_type == "HANDOFF":
        # HANDOFF 事件 next 字段是 state 字符串（flush L298）
        to_state = evt.get("next")
    else:
        # REVIEW_COMPLETED 等
        to_state = None
    actor_role = evt.get("actor")
    summary = evt.get("note") or ""
    evidence_list = evt.get("evidence") or []
    evidence_path = evidence_list[0] if isinstance(evidence_list, list) and evidence_list else None
    detail = dict(evt)  # 全量，含 flush_id/handoff_id 用于去重
    detail_json = json.dumps(detail, ensure_ascii=False)
    created_at = evt.get("time")
    return (
        task_id, event_type, None, to_state, actor_role, None,
        summary, detail_json, evidence_path, created_at, workflow_version,
    )


def cmd_event_sync(args) -> int:
    """回流 flush 追加的 events.jsonl 事件到 DB（M5-C，v3 §4 R2）。

    V5.2.1 Hardening（任务书 §4.3）：默认禁止 event sync 推进权威状态。
    - 允许：导入非状态历史 FACT/DECISION（不更新 task.current_state/owner_role）；
    - 禁止：从可编辑文件（events.jsonl / handoff.json）同步 STATE、HANDOFF 指向的
      新状态、owner_role、completed_at、cancel 状态；
    - 出现上述状态推进输入时返回 ``EVENT_SYNC_STATE_MUTATION_FORBIDDEN``；
    - 管理员恢复：显式 ``--admin-recovery`` + ``--confirm-admin-recovery ADMIN_RECOVERY`` 时，
      转调共享 transition_service.transition_task（共享 validator + durable journal +
      AUDIT/RECONCILIATION 事件），不信任 handoff.json 自报 owner。

    幂等：重复 sync 既不重复插事件，也不重复推进 task 表。
    """
    task_id = args.task
    task_dir = args.task_dir
    if not os.path.isdir(task_dir):
        print(f"ERROR: task-dir not found: {task_dir}", file=sys.stderr)
        return 4
    events_path = os.path.join(task_dir, "events.jsonl")
    if not os.path.isfile(events_path):
        print(f"ERROR: events.jsonl not found in task-dir: {task_dir}", file=sys.stderr)
        return 4

    # 读 events.jsonl（utf-8-sig 容忍 BOM）
    flush_events: List[Dict[str, Any]] = []
    with open(events_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(evt, dict) and "flush_id" in evt:
                flush_events.append(evt)

    if not flush_events:
        print(f"event sync: no flush-appended events in {events_path}")
        return 0

    # 读 handoff.json（F3 owner 来源）
    handoff = _load_handoff_json(task_dir)
    handoff_next = (handoff or {}).get("next") or {}
    next_state = handoff_next.get("state") if isinstance(handoff_next, dict) else None
    next_owner = handoff_next.get("owner") if isinstance(handoff_next, dict) else None

    # ---- V5.2.1 状态推进字段检测（§4.3 禁止清单）----
    _STATE_MUTATION_KEYS = ("state", "to_state", "next", "intended_next", "owner", "owner_role", "completed_at", "cancel")
    state_mutation_found = False
    for evt in flush_events:
        etype = str(evt.get("type") or "").upper()
        if etype in ("STATE", "HANDOFF"):
            state_mutation_found = True
            break
        if any(k in evt for k in _STATE_MUTATION_KEYS):
            state_mutation_found = True
            break
    if next_state or next_owner:
        state_mutation_found = True

    if not getattr(args, "admin_recovery", False):
        if state_mutation_found:
            print(
                "EVENT_SYNC_STATE_MUTATION_FORBIDDEN: event sync must not advance authoritative "
                "state (STATE/HANDOFF/owner/completed_at/cancel). "
                "Use 'tp-spec commit' for state transitions, or '--admin-recovery' with "
                "--confirm-admin-recovery ADMIN_RECOVERY for explicit managed recovery.",
                file=sys.stderr,
            )
            return 8
        # ---- Final Hardening（INV-02/P0-2）：非 admin 模式仅接受严格 FACT ----
        # 输入事件的 type 不能原样信任；REVIEW_COMPLETED/VERIFICATION/DECISION 等
        # 非状态治理事件一律拒绝（EVENT_SYNC_FACT_ONLY）。
        for evt in flush_events:
            etype = str(evt.get("type") or "").upper()
            if etype != "FACT":
                print(
                    f"ERROR: {event_policies.EVENT_SYNC_FACT_ONLY}: event sync only accepts "
                    f"strict FACT events, got type '{etype or '(missing type)'}'; "
                    f"governance events (STATE/HANDOFF/REVIEW_COMPLETED/VERIFICATION/"
                    f"DECISION/...) cannot be imported from editable files.",
                    file=sys.stderr,
                )
                return 8

    # ---- 管理员恢复模式：转调共享 transition_service ----
    if getattr(args, "admin_recovery", False):
        # Personal mode: exact confirmation prevents accidental execution.
        # It is intentionally not a personnel identity or cryptographic approval.
        confirmation = str(getattr(args, "confirm_admin_recovery", "") or "")
        if confirmation != "ADMIN_RECOVERY":
            print(
                "ERROR: ADMIN_RECOVERY_CONFIRMATION_REQUIRED: --admin-recovery requires "
                "--confirm-admin-recovery ADMIN_RECOVERY",
                file=sys.stderr,
            )
            return 8
        if next_state is None:
            print("ERROR: --admin-recovery requires handoff.json next.state", file=sys.stderr)
            return 8
        db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
        from .transition_service import transition_task
        result = transition_task(
            task_id=task_id,
            task_dir=Path(task_dir),
            to_state=next_state,
            actor=getattr(args, "actor", None) or "human_owner",
            summary=getattr(args, "reason", None) or "admin recovery via event sync",
            evidence=[],
            source_command="admin_recovery",
            db_path=db_path,
            extra_detail={
                "recovery_mode": "explicit_personal",
                "handoff_owner_declared": next_owner,
                "confirmation": "ADMIN_RECOVERY",
            },
            extra_events=[
                {
                    "type": "AUDIT",
                    "summary": "admin recovery",
                    "detail_extra": {
                        "audit_reason": getattr(args, "reason", None) or "managed recovery via event sync",
                        "recovery_mode": "explicit_personal",
                        "handoff_owner_declared": next_owner,
                    },
                },
                {
                    "type": "RECONCILIATION",
                    "summary": "admin recovery",
                    "detail_extra": {
                        "target_state": next_state,
                        "target_owner": next_owner,
                    },
                },
            ],
        )
        if not result.ok:
            print(f"ERROR: admin recovery transition failed: {result.message}", file=sys.stderr)
            for issue in result.issues:
                print(f"  - {issue.code}: {issue.message}", file=sys.stderr)
            return 8
        print(f"event sync (admin recovery): {result.message}")
        return 0

    # ---- 非状态历史 FACT 导入（禁止更新 task 表）----
    # 按 flush_id 分组（保持出现顺序）
    groups: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    for evt in flush_events:
        fid = evt.get("flush_id")
        if fid not in groups:
            groups[fid] = []
            order.append(fid)
        groups[fid].append(evt)

    # workflow version
    try:
        from . import workflow_loader
        wf = workflow_loader.load_workflow()
        workflow_version = wf.version or ""
    except Exception:
        workflow_version = ""

    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        # 校验 task 存在
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {task_id}", file=sys.stderr)
            return 4

        existing_flush_ids = _extract_existing_flush_ids(conn, task_id)
        new_flush_ids = [fid for fid in order if fid not in existing_flush_ids]

        if not new_flush_ids:
            print(f"event sync: all {len(order)} flush group(s) already synced (idempotent)")
            return 0

        inserted = 0
        now = dbmod.now_iso()
        with dbmod.transactional(conn):
            for fid in new_flush_ids:
                for evt in groups[fid]:
                    params = _map_event_to_task_event(
                        evt, task_id, workflow_version
                    )
                    conn.execute(
                        """
                        INSERT INTO task_event
                          (task_id, event_type, from_state, to_state, actor_role, actor_agent,
                           summary, detail_json, evidence_path, created_at, workflow_version)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        params,
                    )
                    inserted += 1
        # V5.2.1 Hardening：非状态 FACT 导入禁止 UPDATE task 表（§4.3）。
        # 权威状态只允许经 tp-spec commit / --admin-recovery 修改。
        print(
            f"event sync: imported {len(new_flush_ids)} non-state flush group(s), "
            f"inserted {inserted} FACT event(s); task table untouched (state/owner unchanged)"
        )
        return 0
    finally:
        conn.close()


def add_event_subparsers(event_parser) -> None:
    """注册 event 命令组的子命令。"""
    sub = event_parser.add_subparsers(dest="subcommand", required=True)

    # event list
    p_list = sub.add_parser("list", help="List all events for a task")
    p_list.add_argument("--task", required=True, help="task id")
    p_list.add_argument("--db", required=False, default=None)
    p_list.set_defaults(func=cmd_event_list)

    # event add
    p_add = sub.add_parser("add", help="Add a business event")
    p_add.add_argument("--task", required=True, help="task id")
    # Final Hardening（INV-02/P0-1）：type 不做 argparse choices 预拦——治理事件必须
    # 进入 cmd_event_add 并返回稳定错误码 GOVERNANCE_EVENT_REQUIRES_TRUSTED_PRODUCER(8)，
    # 而非被 argparse 当作"非法选项"返回 2。
    p_add.add_argument(
        "--type",
        required=True,
        help="event type (must be in EventTypes)",
    )
    p_add.add_argument("--actor", required=True, help="actor role (non-empty)")
    p_add.add_argument("--note", required=True, help="event note/summary")
    p_add.add_argument("--evidence", required=False, default=None, help="evidence path")
    p_add.add_argument("--state", required=False, default=None, help="state (for STATE-type events)")
    p_add.add_argument("--next", required=False, default=None, help="next state")
    p_add.add_argument("--db", required=False, default=None)
    p_add.set_defaults(func=cmd_event_add)

    # event sync（M5-C：回流 flush 追加事件到 DB；V5.2.1 默认禁止状态推进）
    p_sync = sub.add_parser("sync", help="Sync flush-appended non-state events to DB (state mutation forbidden)")
    p_sync.add_argument("--task", required=True, help="task id")
    p_sync.add_argument("--task-dir", required=True, help="task directory (events.jsonl location)")
    p_sync.add_argument("--project", required=False, default=None, help="resolve db via registry by project_id")
    p_sync.add_argument("--db", required=False, default=None)
    # V5.2.1 Hardening：显式管理员恢复模式（走共享 transition_service）
    p_sync.add_argument("--admin-recovery", action="store_true", help="V5.2.1 personal mode: explicit managed recovery through shared transition validation")
    p_sync.add_argument("--confirm-admin-recovery", default=None, help="Exact text ADMIN_RECOVERY; explicit confirmation only")
    p_sync.add_argument("--reason", default=None, help="Reason recorded in the admin recovery audit event")
    p_sync.add_argument("--actor", required=False, default=None, help="V5.2.1: recovery actor (default human_owner)")
    p_sync.set_defaults(func=cmd_event_sync)
