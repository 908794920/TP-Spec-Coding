# -*- coding: utf-8 -*-
"""TP-Spec-Coding V5.0 report 命令组（M4）。

包含：
- report task-summary：任务汇总
- report stage-time：按状态分组的耗时
- report rework：返工统计
- report blocked：阻塞任务列表
- report first-pass-rate：首次通过率
- report cross：跨项目聚合

核心保证：
- 全部只读查询，不修改 DB
- stage-time 估算值标注 (estimated)
- cross 检查 schema_version 兼容性，不静默忽略不兼容库
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import db as dbmod
from .reuse_warnings import generate_cost_disclosure_warnings, WARNING_HEADER_CN


_TZ_CN = timezone(timedelta(hours=8))


def _parse_iso(s: str) -> Optional[datetime]:
    """解析 ISO 8601 +08:00 时间字符串。"""
    if not s:
        return None
    try:
        # Python 3.7+ 支持 fromisoformat，但 +08:00 需处理
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _fmt_duration(seconds: Optional[float]) -> str:
    """格式化时长为人类可读字符串。"""
    if seconds is None:
        return "-"
    if seconds < 0:
        return "-"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds/60:.1f}m"
    if seconds < 86400:
        return f"{seconds/3600:.2f}h"
    return f"{seconds/86400:.2f}d"


def _now() -> datetime:
    return datetime.now(_TZ_CN)


def cmd_report_task_summary(args) -> int:
    task_id = args.task
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {task_id}", file=sys.stderr)
            return 4
        state_count = conn.execute(
            "SELECT COUNT(*) AS c FROM task_event WHERE task_id = ? AND event_type = 'STATE'",
            (task_id,),
        ).fetchone()["c"]
        event_count = conn.execute(
            "SELECT COUNT(*) AS c FROM task_event WHERE task_id = ?", (task_id,)
        ).fetchone()["c"]
        session_count = conn.execute(
            "SELECT COUNT(*) AS c FROM task_event WHERE task_id = ? AND event_type = 'WORK_SESSION_STARTED'",
            (task_id,),
        ).fetchone()["c"]
        rework_count = conn.execute(
            "SELECT COUNT(*) AS c FROM task_event WHERE task_id = ? AND event_type = 'REWORK'",
            (task_id,),
        ).fetchone()["c"]
        workitem_total = conn.execute(
            "SELECT COUNT(*) AS c FROM work_item WHERE task_id = ?", (task_id,)
        ).fetchone()["c"]
        workitem_by_status = conn.execute(
            "SELECT status, COUNT(*) AS c FROM work_item WHERE task_id = ? GROUP BY status",
            (task_id,),
        ).fetchall()
        print(f"=== Task Summary: {task_id} ===")
        print(f"  title:         {task['title'] or ''}")
        print(f"  project:       {task['project_id']}")
        print(f"  risk/flow:     {task['risk_level']} / {task['flow_level']}")
        print(f"  current_state: {task['current_state']} (owner={task['owner_role']})")
        print(f"  base_version:  {task['base_version']}")
        print(f"  created_at:    {task['created_at']}")
        print(f"  updated_at:    {task['updated_at']}")
        print(f"  completed_at:  {task['completed_at'] or '-'}")
        print(f"  --- metrics ---")
        print(f"  state transitions: {state_count}")
        print(f"  total events:      {event_count}")
        print(f"  work sessions:     {session_count}")
        print(f"  rework events:     {rework_count}")
        print(f"  work items:        {workitem_total}")
        if workitem_by_status:
            dist = ", ".join(f"{r['status']}={r['c']}" for r in workitem_by_status)
            print(f"  workitem status:   {dist}")
        return 0
    finally:
        conn.close()


def cmd_report_stage_time(args) -> int:
    task_id = args.task
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {task_id}", file=sys.stderr)
            return 4
        # 查询所有 STATE 事件按 id 升序
        state_events = conn.execute(
            "SELECT id, created_at, to_state FROM task_event "
            "WHERE task_id = ? AND event_type = 'STATE' ORDER BY id",
            (task_id,),
        ).fetchall()
        if not state_events:
            print(f"(no STATE events for {task_id})")
            return 0
        # 查询所有 WORK_SESSION_STARTED/ENDED 对
        sessions = conn.execute(
            "SELECT id, event_type, created_at FROM task_event "
            "WHERE task_id = ? AND event_type IN ('WORK_SESSION_STARTED', 'WORK_SESSION_ENDED') "
            "ORDER BY id",
            (task_id,),
        ).fetchall()
        # 查询 REWORK 事件
        rework_events = conn.execute(
            "SELECT id, created_at FROM task_event WHERE task_id = ? AND event_type = 'REWORK' ORDER BY id",
            (task_id,),
        ).fetchall()

        now = _now()
        # 计算 elapsed_time：每个 STATE 的 (下一条 STATE.time - 本条 STATE.time)，最后一条用 now
        stages: List[Dict[str, Any]] = []
        for i, ev in enumerate(state_events):
            start = _parse_iso(ev["created_at"])
            if i + 1 < len(state_events):
                end = _parse_iso(state_events[i + 1]["created_at"])
            else:
                end = now
            elapsed = (end - start).total_seconds() if start and end else None
            stages.append({
                "state": ev["to_state"],
                "start": ev["created_at"],
                "elapsed": elapsed,
                "active": 0.0,
                "normal_wait": 0.0,
                "blocked": 0.0,
            })

        # 构建 state 时间区间索引：每个 stage 的 [start, end)
        def _find_stage(t: datetime) -> Optional[int]:
            for idx, s in enumerate(stages):
                s_start = _parse_iso(s["start"])
                if idx + 1 < len(stages):
                    s_end = _parse_iso(stages[idx + 1]["start"])
                else:
                    s_end = now
                if s_start and s_end and s_start <= t < s_end:
                    return idx
            return None

        # 计算 active_time 和 normal_wait_time：遍历 WORK_SESSION 对
        open_session: Optional[Dict[str, Any]] = None
        for sess in sessions:
            t = _parse_iso(sess["created_at"])
            if sess["event_type"] == "WORK_SESSION_STARTED":
                open_session = {"start": t, "start_time": sess["created_at"]}
            elif sess["event_type"] == "WORK_SESSION_ENDED" and open_session:
                start_t = open_session["start"]
                end_t = t
                duration = (end_t - start_t).total_seconds() if start_t and end_t else 0.0
                # 会话归属其开始时 task 所处状态
                stage_idx = _find_stage(start_t) if start_t else None
                if stage_idx is not None:
                    stages[stage_idx]["active"] += duration
                # 查询这条 WORK_SESSION_ENDED 的 reason
                end_ev = conn.execute(
                    "SELECT detail_json FROM task_event WHERE id = ?", (sess["id"],)
                ).fetchone()
                reason = ""
                if end_ev and end_ev["detail_json"]:
                    try:
                        detail = json.loads(end_ev["detail_json"])
                        reason = detail.get("reason", "")
                    except json.JSONDecodeError:
                        pass
                if reason in ("waiting_human", "waiting_agent", "paused"):
                    if stage_idx is not None:
                        stages[stage_idx]["normal_wait"] += duration
                open_session = None

        # 计算 blocked_time：current_state=BLOCKED 期间
        for idx, s in enumerate(stages):
            if s["state"] == "BLOCKED":
                s["blocked"] = s["elapsed"] or 0.0

        # 输出表格
        print(f"=== Stage Time: {task_id} (current={task['current_state']}) ===")
        headers = ["state", "elapsed", "active", "normal_wait", "blocked"]
        rows = []
        for s in stages:
            is_last = s is stages[-1]
            est = " (estimated)" if is_last else ""
            rows.append([
                s["state"],
                _fmt_duration(s["elapsed"]) + est,
                _fmt_duration(s["active"]),
                _fmt_duration(s["normal_wait"]),
                _fmt_duration(s["blocked"]),
            ])
        widths = [len(h) for h in headers]
        for r in rows:
            for i, v in enumerate(r):
                widths[i] = max(widths[i], len(v))
        def fmt_row(cells):
            return "  ".join(c.ljust(widths[i]) for i, c in enumerate(cells))
        print(fmt_row(headers))
        print("  ".join("-" * w for w in widths))
        for r in rows:
            print(fmt_row(r))
        if rework_events:
            print(f"\n  rework events: {len(rework_events)}")
        return 0
    finally:
        conn.close()


def cmd_report_rework(args) -> int:
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None))
    conn = dbmod.connect(db_path)
    try:
        # 不用 SQL LIKE 匹配 detail_json 里的布尔字段（json.dumps 默认冒号后有空格，
        # LIKE '%"requirement_changed":true%' 永不匹配）。改为取出原始行后在 Python 里
        # json.loads 判断 requirement_changed 布尔来计数，req_changed / req_unchanged 同理。
        sql = (
            "SELECT reason_code, task_id, detail_json "
            "FROM task_event WHERE event_type = 'REWORK'"
        )
        params = []
        if args.project:
            sql += " AND task_id IN (SELECT task_id FROM task WHERE project_id = ?)"
            params.append(args.project)
        sql += " ORDER BY id"
        rows = conn.execute(sql, params).fetchall()
        if not rows:
            print("(no rework events)")
            return 0
        # Python 端聚合：cause -> {cnt, tasks, req_changed, req_unchanged}
        agg = {}
        for r in rows:
            rc = r["reason_code"] or "(unknown)"
            if rc not in agg:
                agg[rc] = {"cnt": 0, "tasks": set(), "req_changed": 0, "req_unchanged": 0}
            detail = {}
            if r["detail_json"]:
                try:
                    detail = json.loads(r["detail_json"])
                except (ValueError, TypeError):
                    detail = {}
            req_changed = bool(detail.get("requirement_changed", False))
            agg[rc]["cnt"] += 1
            agg[rc]["tasks"].add(r["task_id"])
            if req_changed:
                agg[rc]["req_changed"] += 1
            else:
                agg[rc]["req_unchanged"] += 1
        print("=== Rework Report ===")
        print(f"{'cause_type':<25} {'count':>6} {'tasks':>6} {'req_changed':>12} {'req_unchanged':>14}")
        print("-" * 70)
        for rc, a in sorted(agg.items(), key=lambda kv: -kv[1]["cnt"]):
            print(
                f"{rc:<25} {a['cnt']:>6} {len(a['tasks']):>6} "
                f"{a['req_changed']:>12} {a['req_unchanged']:>14}"
            )
        return 0
    finally:
        conn.close()


def cmd_report_blocked(args) -> int:
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None))
    conn = dbmod.connect(db_path)
    try:
        # 列出所有进入过 BLOCKED 的任务
        sql = (
            "SELECT DISTINCT t.task_id, t.project_id, t.title, t.current_state, t.risk_level "
            "FROM task t "
            "JOIN task_event e ON e.task_id = t.task_id "
            "WHERE e.event_type = 'STATE' AND e.to_state = 'BLOCKED'"
        )
        params = []
        if args.project:
            sql += " AND t.project_id = ?"
            params.append(args.project)
        sql += " ORDER BY t.task_id"
        tasks = conn.execute(sql, params).fetchall()
        if not tasks:
            print("(no tasks have entered BLOCKED)")
            return 0
        print("=== Blocked Report ===")
        print(f"{'task_id':<20} {'project':<12} {'current':<16} {'risk':<4} {'blocked_duration':>16} {'reason'}")
        print("-" * 90)
        now = _now()
        for t in tasks:
            # 找最近一次进入 BLOCKED 的事件
            block_ev = conn.execute(
                "SELECT id, created_at, summary FROM task_event "
                "WHERE task_id = ? AND event_type = 'STATE' AND to_state = 'BLOCKED' "
                "ORDER BY id DESC LIMIT 1",
                (t["task_id"],),
            ).fetchone()
            # 找离开 BLOCKED 的事件（如果有）
            exit_ev = conn.execute(
                "SELECT id, created_at FROM task_event "
                "WHERE task_id = ? AND event_type = 'STATE' AND from_state = 'BLOCKED' "
                "AND id > ? ORDER BY id LIMIT 1",
                (t["task_id"], block_ev["id"] if block_ev else 0),
            ).fetchone() if block_ev else None
            block_start = _parse_iso(block_ev["created_at"]) if block_ev else None
            if exit_ev:
                block_end = _parse_iso(exit_ev["created_at"])
            else:
                block_end = now
            duration = (block_end - block_start).total_seconds() if block_start and block_end else None
            print(
                f"{t['task_id']:<20} {t['project_id']:<12} {t['current_state']:<16} "
                f"{t['risk_level']:<4} {_fmt_duration(duration):>16} {block_ev['summary'] if block_ev else ''}"
            )
        return 0
    finally:
        conn.close()


def cmd_report_first_pass_rate(args) -> int:
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None))
    conn = dbmod.connect(db_path)
    try:
        # 找所有进入过 VERIFYING 的任务
        sql = (
            "SELECT DISTINCT t.task_id FROM task t "
            "JOIN task_event e ON e.task_id = t.task_id "
            "WHERE e.event_type = 'STATE' AND e.to_state = 'VERIFYING'"
        )
        params = []
        if args.project:
            sql += " AND t.project_id = ?"
            params.append(args.project)
        tasks = conn.execute(sql, params).fetchall()
        total = len(tasks)
        if total == 0:
            print("first-pass-rate: 0/0 (no tasks entered VERIFYING)")
            return 0
        first_pass = 0
        for t in tasks:
            # 查该任务在首次进入 VERIFYING 之后是否有 REWORK
            first_verify = conn.execute(
                "SELECT id FROM task_event "
                "WHERE task_id = ? AND event_type = 'STATE' AND to_state = 'VERIFYING' "
                "ORDER BY id LIMIT 1",
                (t["task_id"],),
            ).fetchone()
            if not first_verify:
                continue
            # 检查首次 VERIFYING 之后是否有 REWORK
            rework_after = conn.execute(
                "SELECT COUNT(*) AS c FROM task_event "
                "WHERE task_id = ? AND event_type = 'REWORK' AND id > ?",
                (t["task_id"], first_verify["id"]),
            ).fetchone()["c"]
            # 检查是否到达 REVIEWING
            reached_review = conn.execute(
                "SELECT COUNT(*) AS c FROM task_event "
                "WHERE task_id = ? AND event_type = 'STATE' AND to_state = 'REVIEWING'",
                (t["task_id"],),
            ).fetchone()["c"]
            if reached_review > 0 and rework_after == 0:
                first_pass += 1
        rate = (first_pass / total * 100) if total > 0 else 0.0
        print(f"=== First Pass Rate ===")
        print(f"  total:       {total}")
        print(f"  first_pass:  {first_pass}")
        print(f"  rate:        {rate:.1f}%")
        return 0
    finally:
        conn.close()


def cmd_report_cross(args) -> int:
    metric = args.metric
    valid_metrics = ("task_count", "rework_count", "blocked_count", "first_pass_rate")
    if metric not in valid_metrics:
        print(f"ERROR: invalid metric '{metric}' (must be one of: {', '.join(valid_metrics)})", file=sys.stderr)
        return 2
    # 读 registry
    reg_path = dbmod.registry_default_path()
    if not reg_path.exists():
        print("ERROR: no registry found (run 'project init' first)", file=sys.stderr)
        return 4
    try:
        with open(reg_path, "r", encoding="utf-8") as f:
            reg_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"ERROR: failed to read registry: {e}", file=sys.stderr)
        return 5
    all_projects = reg_data.get("projects", [])
    # 过滤 --projects
    filter_pids = None
    if args.projects:
        filter_pids = set(p.strip() for p in args.projects.split(",") if p.strip())
    projects = [p for p in all_projects if not filter_pids or p.get("project_id") in filter_pids]
    if not projects:
        print("(no matching projects)")
        return 0
    base_root = Path(__file__).resolve().parent.parent
    compatible: List[Dict[str, Any]] = []
    incompatible: List[str] = []
    for proj in projects:
        db_path_str = proj.get("db_path", "")
        if not db_path_str:
            incompatible.append(f"{proj.get('project_id')}: no db_path")
            continue
        if not Path(db_path_str).is_absolute():
            db_path_str = str((base_root / db_path_str).resolve())
        if not Path(db_path_str).exists():
            incompatible.append(f"{proj.get('project_id')}: db not found")
            continue
        # 检查 schema_version
        try:
            conn = dbmod.connect(db_path_str)
            try:
                row = conn.execute(
                    "SELECT schema_version FROM schema_meta ORDER BY schema_version DESC LIMIT 1"
                ).fetchone()
                if row is None or row["schema_version"] != dbmod.EXPECTED_SCHEMA_VERSION:
                    incompatible.append(
                        f"{proj.get('project_id')}: schema_version={row['schema_version'] if row else 'none'}"
                    )
                    continue
                compatible.append({"project_id": proj["project_id"], "db_path": db_path_str})
            finally:
                conn.close()
        except Exception as e:
            incompatible.append(f"{proj.get('project_id')}: {type(e).__name__}: {e}")

    print(f"=== Cross Report: metric={metric} ===")
    if not compatible:
        print("  (no compatible projects)")
    else:
        total_value = 0
        total_first_pass = 0
        total_verify = 0
        for proj in compatible:
            conn = dbmod.connect(proj["db_path"])
            try:
                if metric == "task_count":
                    val = conn.execute("SELECT COUNT(*) AS c FROM task").fetchone()["c"]
                    print(f"  {proj['project_id']:<15} task_count={val}")
                    total_value += val
                elif metric == "rework_count":
                    val = conn.execute(
                        "SELECT COUNT(*) AS c FROM task_event WHERE event_type = 'REWORK'"
                    ).fetchone()["c"]
                    print(f"  {proj['project_id']:<15} rework_count={val}")
                    total_value += val
                elif metric == "blocked_count":
                    val = conn.execute(
                        "SELECT COUNT(DISTINCT task_id) AS c FROM task_event "
                        "WHERE event_type = 'STATE' AND to_state = 'BLOCKED'"
                    ).fetchone()["c"]
                    print(f"  {proj['project_id']:<15} blocked_count={val}")
                    total_value += val
                elif metric == "first_pass_rate":
                    tasks = conn.execute(
                        "SELECT DISTINCT task_id FROM task_event "
                        "WHERE event_type = 'STATE' AND to_state = 'VERIFYING'"
                    ).fetchall()
                    proj_total = len(tasks)
                    proj_fp = 0
                    for t in tasks:
                        first_verify = conn.execute(
                            "SELECT id FROM task_event WHERE task_id = ? "
                            "AND event_type = 'STATE' AND to_state = 'VERIFYING' ORDER BY id LIMIT 1",
                            (t["task_id"],),
                        ).fetchone()
                        if not first_verify:
                            continue
                        rework_after = conn.execute(
                            "SELECT COUNT(*) AS c FROM task_event "
                            "WHERE task_id = ? AND event_type = 'REWORK' AND id > ?",
                            (t["task_id"], first_verify["id"]),
                        ).fetchone()["c"]
                        reached_review = conn.execute(
                            "SELECT COUNT(*) AS c FROM task_event "
                            "WHERE task_id = ? AND event_type = 'STATE' AND to_state = 'REVIEWING'",
                            (t["task_id"],),
                        ).fetchone()["c"]
                        if reached_review > 0 and rework_after == 0:
                            proj_fp += 1
                    rate = (proj_fp / proj_total * 100) if proj_total > 0 else 0.0
                    print(f"  {proj['project_id']:<15} first_pass_rate={rate:.1f}% ({proj_fp}/{proj_total})")
                    total_first_pass += proj_fp
                    total_verify += proj_total
            finally:
                conn.close()
        # 汇总
        if metric == "first_pass_rate":
            overall = (total_first_pass / total_verify * 100) if total_verify > 0 else 0.0
            print(f"  {'TOTAL':<15} first_pass_rate={overall:.1f}% ({total_first_pass}/{total_verify})")
        else:
            print(f"  {'TOTAL':<15} {metric}={total_value}")
    if incompatible:
        print(f"\n  incompatible projects ({len(incompatible)}):")
        for msg in incompatible:
            print(f"    - {msg} (please migrate)")
    return 0


_FMT_VERSION = "1.0.0"


_FMT_MONEY = "{:+.2f}"  # 货币值格式：带符号，两位小数
_FMT_PCT = "{:.1%}"     # 百分比格式：一位小数


def _fmt_value(v: float | None, fmt: str = _FMT_MONEY, na: str = "N/A") -> str:
    """格式化数值，None 显示 N/A。"""
    if v is None:
        return na
    return fmt.format(v)


def cmd_report_cost_benefit(args) -> int:
    """V5.2.1 B-15 成本披露报表（强制四列 + W1-W4 告警 + 净亏独立列）。

    对齐升级计划 §3.5（L180-189）与 B-13 设计文档。
    仅披露不阻断：不改变 workflow 状态、不改变风险等级。
    """
    task_id = args.task

    # 解析输入（四列强制字段）
    preflight_self_cost = args.preflight_self_cost
    verification_input_saved = args.verification_input_saved
    net_saving = args.net_saving
    reuse_rate = args.reuse_rate

    # 可选明细字段
    verification_input_baseline = args.verification_input_baseline
    verification_input_actual = args.verification_input_actual
    theoretical_saving = args.theoretical_saving
    actual_saving = args.actual_saving
    has_reported_data = args.has_reported_data
    invalidation_reason = args.invalidation_reason or ""

    # 双 unknown 指标（分母各自明确）
    unknown_session_ratio = args.unknown_session_ratio
    unknown_input_bytes_ratio = args.unknown_input_bytes_ratio
    session_count = args.session_count
    input_bytes_total = args.input_bytes_total

    # 生成 W1-W4 告警（复用已建好的警告模块）
    warnings = generate_cost_disclosure_warnings(
        unknown_session_ratio=unknown_session_ratio,
        unknown_input_bytes_ratio=unknown_input_bytes_ratio,
        net_saving=net_saving,
        reuse_rate=reuse_rate,
        has_reuse_history=True,
    )

    # 构建报表行
    lines: list[str] = []
    lines.append("=== Cost-Benefit Disclosure Report ===")
    lines.append(f"Task: {task_id}")
    lines.append(f"Report Version: {_FMT_VERSION}")
    lines.append("")

    # --- 披露告警区（W1-W4）---
    if warnings:
        lines.extend(warnings)
        lines.append("")

    # --- 强制四列 ---
    lines.append("--- Mandatory Cost-Benefit Metrics ---")
    lines.append(f"  preflight_self_cost:         {_fmt_value(preflight_self_cost)}")
    lines.append(f"  verification_input_saved:    {_fmt_value(verification_input_saved)}")
    lines.append(f"  net_saving:                  {_fmt_value(net_saving)}")
    lines.append(f"  reuse_rate:                  {_fmt_value(reuse_rate, _FMT_PCT)}")
    lines.append("")

    # --- 净亏独立列（net_saving < 0 时展示）---
    if net_saving is not None and net_saving < 0:
        lines.append("--- Net Loss Column (net_saving < 0) ---")
        lines.append(f"  net_saving: {_fmt_value(net_saving)}  (preflight self cost exceeds savings; audit/tuning only, excluded from benefit conclusion)")
        lines.append("")

    # --- Unknown 指标（分母明确）---
    lines.append("--- Unknown Indicators ---")
    session_den = f" (denominator: {session_count} sessions)" if session_count is not None else ""
    bytes_den = f" (denominator: {input_bytes_total} input bytes)" if input_bytes_total is not None else ""
    lines.append(f"  unknown_session_ratio:       {_fmt_value(unknown_session_ratio, _FMT_PCT)}{session_den}")
    lines.append(f"  unknown_input_bytes_ratio:   {_fmt_value(unknown_input_bytes_ratio, _FMT_PCT)}{bytes_den}")
    lines.append("")

    # --- 详细分解 ---
    lines.append("--- Detailed Breakdown ---")
    lines.append(f"  verification_input_baseline: {_fmt_value(verification_input_baseline)}")
    lines.append(f"  verification_input_actual:   {_fmt_value(verification_input_actual)}")
    lines.append(f"  theoretical_saving:          {_fmt_value(theoretical_saving)}")
    if has_reported_data and actual_saving is not None:
        lines.append(f"  actual_saving:               {_fmt_value(actual_saving)}")
    else:
        lines.append(f"  actual_saving:               N/A (no REPORTED data)")
    if invalidation_reason:
        lines.append(f"  invalidation_reason:         {invalidation_reason}")
    lines.append("")

    # --- 样本摘要 ---
    lines.append("--- Summary ---")
    if net_saving is not None and net_saving >= 0:
        lines.append(f"  Net benefit: {_fmt_value(net_saving)} (positive, eligible for benefit conclusion)")
    elif net_saving is not None and net_saving < 0:
        lines.append(f"  Net benefit: {_fmt_value(net_saving)} (net loss, excluded from benefit conclusion)")
    else:
        lines.append("  Net benefit: N/A")
    lines.append("")

    report_text = "\n".join(lines)
    print(report_text)

    # 持久化：写入 JSON 文件（告警内嵌，禁止仅 stdout 闪现）
    if args.output:
        report_data = {
            "report_type": "cost_benefit_disclosure",
            "report_version": _FMT_VERSION,
            "task_id": task_id,
            "mandatory_metrics": {
                "preflight_self_cost": preflight_self_cost,
                "verification_input_saved": verification_input_saved,
                "net_saving": net_saving,
                "reuse_rate": reuse_rate,
            },
            "warnings": warnings,
            "unknown_indicators": {
                "unknown_session_ratio": unknown_session_ratio,
                "unknown_input_bytes_ratio": unknown_input_bytes_ratio,
                "session_count": session_count,
                "input_bytes_total": input_bytes_total,
            },
            "detailed_breakdown": {
                "verification_input_baseline": verification_input_baseline,
                "verification_input_actual": verification_input_actual,
                "theoretical_saving": theoretical_saving,
                "actual_saving": actual_saving if has_reported_data else None,
                "has_reported_data": has_reported_data,
                "invalidation_reason": invalidation_reason,
            },
        }
        import json
        import os
        out_path = Path(args.output)
        os.makedirs(str(out_path.parent), exist_ok=True)
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"Report persisted to: {out_path}")

    return 0


def add_report_subparsers(report_parser) -> None:
    """注册 report 命令组的子命令。"""
    sub = report_parser.add_subparsers(dest="subcommand", required=True)

    # report task-summary
    p_ts = sub.add_parser("task-summary", help="Task summary report")
    p_ts.add_argument("--task", required=True, help="task id")
    p_ts.add_argument("--db", required=False, default=None)
    p_ts.set_defaults(func=cmd_report_task_summary)

    # report stage-time
    p_st = sub.add_parser("stage-time", help="Stage time breakdown")
    p_st.add_argument("--task", required=True, help="task id")
    p_st.add_argument("--db", required=False, default=None)
    p_st.set_defaults(func=cmd_report_stage_time)

    # report rework
    p_rw = sub.add_parser("rework", help="Rework statistics")
    p_rw.add_argument("--project", required=False, default=None)
    p_rw.add_argument("--db", required=False, default=None)
    p_rw.set_defaults(func=cmd_report_rework)

    # report blocked
    p_bl = sub.add_parser("blocked", help="Blocked tasks report")
    p_bl.add_argument("--project", required=False, default=None)
    p_bl.add_argument("--db", required=False, default=None)
    p_bl.set_defaults(func=cmd_report_blocked)

    # report first-pass-rate
    p_fpr = sub.add_parser("first-pass-rate", help="First pass rate report")
    p_fpr.add_argument("--project", required=False, default=None)
    p_fpr.add_argument("--db", required=False, default=None)
    p_fpr.set_defaults(func=cmd_report_first_pass_rate)

    # report cross
    p_cross = sub.add_parser("cross", help="Cross-project aggregation")
    p_cross.add_argument("--metric", required=True, choices=["task_count", "rework_count", "blocked_count", "first_pass_rate"])
    p_cross.add_argument("--projects", required=False, default=None, help="comma-separated project ids")
    p_cross.add_argument("--db", required=False, default=None)
    p_cross.set_defaults(func=cmd_report_cross)

    # report cost-benefit（V5.2.1 B-15 成本披露报表）
    p_cb = sub.add_parser("cost-benefit", help="Cost-benefit disclosure report (V5.2.1 B-15)")
    p_cb.add_argument("--task", required=True, help="task id")
    p_cb.add_argument("--output", required=True, help="persist report to JSON file path")
    # 四列强制字段
    p_cb.add_argument("--preflight-self-cost", required=True, type=float, help="preflight cost (self_cost)")
    p_cb.add_argument("--verification-input-saved", required=True, type=float, help="input bytes saved")
    p_cb.add_argument("--net-saving", required=True, type=float, help="net_saving = actual_or_comparable_saved - self_cost")
    p_cb.add_argument("--reuse-rate", required=True, type=float, help="reuse_rate (0.0-1.0)")
    # 双 unknown 指标
    p_cb.add_argument("--unknown-session-ratio", type=float, default=None, help="unknown session ratio (0.0-1.0)")
    p_cb.add_argument("--unknown-input-bytes-ratio", type=float, default=None, help="unknown input bytes ratio (0.0-1.0)")
    p_cb.add_argument("--session-count", type=int, default=None, help="total session count (denominator for unknown_session_ratio)")
    p_cb.add_argument("--input-bytes-total", type=float, default=None, help="total input bytes (denominator for unknown_input_bytes_ratio)")
    # 可选明细
    p_cb.add_argument("--verification-input-baseline", type=float, default=None, help="verification input baseline bytes")
    p_cb.add_argument("--verification-input-actual", type=float, default=None, help="verification input actual bytes")
    p_cb.add_argument("--theoretical-saving", type=float, default=None, help="theoretical saving")
    p_cb.add_argument("--actual-saving", type=float, default=None, help="actual saving (only when REPORTED data exists)")
    p_cb.add_argument("--has-reported-data", action="store_true", default=False, help="whether REPORTED data exists for actual_saving")
    p_cb.add_argument("--invalidation-reason", default=None, help="reuse invalidation reason")
    p_cb.set_defaults(func=cmd_report_cost_benefit)
