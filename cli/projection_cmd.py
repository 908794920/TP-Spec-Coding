# -*- coding: utf-8 -*-
"""TP-Spec-Coding V5.1 projection 命令组（M3）。

包含：
- projection rebuild：DB → status.yaml + events.jsonl
- projection validate：比对投影文件与数据库

核心保证：
- status.yaml 字段顺序与兼容投影契约完全一致
- events.jsonl 每行 JSON：id/time/type/actor 非空，type 在 EventTypes 内
- actor 非空保证（回退到 actor_agent，再回退 "unknown" 并告警）
- 末条 STATE 事件的 state = task.current_state（Test-TpSpecTask.ps1 L765-L767 硬校验）
- 不生成 generated/（那是 flush 的产物）
- UTF-8 无 BOM
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import db as dbmod
from .version import active_version


# 与 Test-TpSpecTask.ps1 L25 $EventTypes 完全一致
_EVENT_TYPES = {
    "STATE",
    "FACT",
    "DECISION",
    "BLOCKER",
    "VERIFICATION",
    "REVIEW",
    "REVIEW_COMPLETED",
    "HANDOFF",
    "SCOPE_CHANGE",
    "KNOWLEDGE",
}

# task_event.event_type → events.jsonl type 映射
# WORK_SESSION_STARTED/ENDED/REWORK 不在 EventTypes 内，映射为 FACT
_TYPE_MAP = {
    "STATE": "STATE",
    "WORK_SESSION_STARTED": "FACT",
    "WORK_SESSION_ENDED": "FACT",
    "REWORK": "FACT",
    "ARTIFACT_REFRESH": "FACT",
    "PHASE_EXIT": "FACT",
    "HANDOFF": "HANDOFF",
    "FACT": "FACT",
    "DECISION": "DECISION",
    "BLOCKER": "BLOCKER",
    "VERIFICATION": "VERIFICATION",
    "VERIFICATION_COMPLETED": "VERIFICATION",
    "REVIEW": "REVIEW",
    "REVIEW_COMPLETED": "REVIEW_COMPLETED",
    "SCOPE_CHANGE": "SCOPE_CHANGE",
    "KNOWLEDGE": "KNOWLEDGE",
    # V5.2.1 A-04：reconcile 追加的审计事件；投影为 FACT 保持
    # events.jsonl 合法 type 集合不变（Test-TpSpecTask.ps1 EventTypes 零感知）。
    "RECONCILIATION": "FACT",
}


# V5.2.1 新工件（AI-B 模板定义；AI-C 可继续追加）：存在才纳入 source digest。
_V511_SOURCE_NAMES = (
    "requirement-knowledge.md",
    "requirement-clarifications.md",
    "requirement-decisions.md",
    "architecture-review.md",
    "requirement-test-guide.md",
)


def projection_source_names() -> List[str]:
    """current view source_files 集中注册表（V5.2.1 §10.2）。

    AI-C 接入 V5.2.1 新工件规则时可追加文件名；commit 的
    _continuation_sources 与 reconcile 共用本注册表，存在性过滤保证
    旧任务/低风险任务不受影响。
    """
    return list(_V511_SOURCE_NAMES)


def projection_source_files(task_dir: Path) -> List[Path]:
    """解析后的 source 文件路径（仅返回实际存在的文件）。"""
    return [task_dir / name for name in projection_source_names() if (task_dir / name).is_file()]


def _resolve_task_dir(args_task_dir: Optional[str], task_id: str, conn) -> Path:
    """解析任务目录。

    优先级：
    1. --task-dir 显式指定
    2. registry 中 project root + .tp-spec/tasks/<task_id>
    3. cwd/.tp-spec/tasks/<task_id>
    """
    if args_task_dir:
        return Path(args_task_dir).resolve()
    # 从 task 表查 project_id，再从 registry 查 project root
    task = conn.execute("SELECT project_id FROM task WHERE task_id = ?", (task_id,)).fetchone()
    if task is not None:
        project_id = task["project_id"]
        reg_path = dbmod.registry_default_path()
        if reg_path.exists():
            try:
                with open(reg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for proj in data.get("projects", []):
                    if proj.get("project_id") == project_id:
                        root_path = proj.get("root_path", ".")
                        if not os.path.isabs(root_path):
                            # 相对路径以 tp-spec-base 根为基准
                            base_root = Path(__file__).resolve().parent.parent
                            root_path = str(base_root / root_path)
                        return (Path(root_path) / ".tp-spec" / "tasks" / task_id).resolve()
            except (json.JSONDecodeError, OSError):
                pass
    return (Path.cwd() / ".tp-spec" / "tasks" / task_id).resolve()


def _map_event_type(event_type: str) -> str:
    """task_event.event_type → events.jsonl type。不在 EventTypes 内的映射为 FACT。"""
    mapped = _TYPE_MAP.get(event_type)
    if mapped and mapped in _EVENT_TYPES:
        return mapped
    return "FACT"


def _resolve_actor(actor_role: Optional[str], actor_agent: Optional[str]) -> Tuple[str, bool]:
    """解析 actor，保证非空。返回 (actor, warned)。"""
    if actor_role and actor_role.strip():
        return actor_role.strip(), False
    if actor_agent and actor_agent.strip():
        return actor_agent.strip(), False
    return "unknown", True


def _format_status_yaml(
    task_id: str,
    task_name: str,
    created: str,
    base_version: str,
    current_state: str,
    current_phase: str,
    current_owner: str,
    risk_level: str,
    flow_level: str,
    blockers: List[str],
    findings: List[str],
    scope_changes: List[str],
) -> str:
    """手写兼容 status.yaml 投影。"""
    lines: List[str] = []

    def fmt_list(items: List[str]) -> str:
        if not items:
            return "[]"
        return "[" + ", ".join(items) + "]"

    def fmt_str(s: str) -> str:
        return f'"{s}"'

    lines.append(f"task_id: {fmt_str(task_id)}")
    lines.append(f"task_name: {fmt_str(task_name)}")
    lines.append(f"created: {fmt_str(created)}")
    lines.append(f"base_version: {fmt_str(base_version)}")
    lines.append("artifact_contract:")
    lines.append(f"  version: {fmt_str(active_version())}")
    lines.append(f"current_state: {fmt_str(current_state)}")
    lines.append(f"current_phase: {fmt_str(current_phase)}")
    lines.append(f"current_owner: {fmt_str(current_owner)}")
    lines.append(f"risk_level: {fmt_str(risk_level)}")
    lines.append(f"flow_level: {fmt_str(flow_level)}")
    lines.append(f"blockers: {fmt_list(blockers)}")
    lines.append(f"findings: {fmt_list(findings)}")
    lines.append(f"scope_changes: {fmt_list(scope_changes)}")
    lines.append("artifacts:")
    lines.append('  event_log: "events.jsonl"')
    lines.append('  continuation: "generated/continuation.md"')
    lines.append('  acceptance: "acceptance.md"')
    lines.append('  task_document: "task.md"')
    lines.append('  evidence: "evidence/"')
    return "\n".join(lines) + "\n"


def _build_events_jsonl(events: List[Dict[str, Any]], task_id: str) -> Tuple[str, List[str]]:
    """从 task_event 行构建 events.jsonl 内容。返回 (content, warnings)。"""
    warnings: List[str] = []
    lines: List[str] = []
    # NNN 从 001 起按时间顺序；id 格式 EV-YYYYMMDD-NNN
    seq_by_date: Dict[str, int] = {}
    for ev in events:
        created_at = ev["created_at"] or ""
        # 提取 YYYYMMDD
        date_part = ""
        if len(created_at) >= 10:
            date_part = created_at[:10].replace("-", "")
        seq_by_date[date_part] = seq_by_date.get(date_part, 0) + 1
        seq = seq_by_date[date_part]
        event_id = f"EV-{date_part}-{seq:03d}"

        event_type = ev["event_type"] or "FACT"
        mapped_type = _map_event_type(event_type)

        actor, warned = _resolve_actor(ev["actor_role"], ev["actor_agent"])
        if warned:
            warnings.append(
                f"event #{ev['id']} has empty actor_role/actor_agent, fallback to 'unknown'"
            )

        obj: Dict[str, Any] = {
            "id": event_id,
            "time": created_at,
            "type": mapped_type,
            "actor": actor,
            "note": ev["summary"] or "",
        }

        # STATE 事件输出 state 和 next
        if mapped_type == "STATE":
            to_state = ev["to_state"] or ""
            obj["state"] = to_state
            obj["next"] = to_state  # 计划 §6.2：next 置为 to_state（校验器不查 next，语义无害）
        else:
            # 非 STATE 事件不输出 state/next
            pass

        # REVIEW_COMPLETED 忠实回投：从 detail_json 补 decision/handoff_id/flush_id
        # （M6 修复：校验器 Test-TpSpecTask.ps1 L819-822 交叉校验 REVIEW_COMPLETED 的
        #   decision/time/evidence 与 codex-review.md 匹配；time 已由 created_at 正确回投
        #   （= flush 写入的 review.Timestamp），evidence 已由 evidence_path 回投；
        #   decision/handoff_id/flush_id 原先丢失，导致 rebuild 后过不了校验器。
        #   数据源：event_cmd L184 detail=dict(evt) 全量复制，含这些字段。）
        if mapped_type in {"REVIEW_COMPLETED", "VERIFICATION"}:
            detail = {}
            # sqlite3.Row 不支持 .get()，用键访问 + try/except
            try:
                raw_detail = ev["detail_json"] or ""
            except (KeyError, IndexError):
                raw_detail = ""
            if raw_detail:
                try:
                    detail = json.loads(raw_detail)
                except json.JSONDecodeError:
                    detail = {}
            if "decision" in detail:
                obj["decision"] = detail["decision"]
            if "handoff_id" in detail:
                obj["handoff_id"] = detail["handoff_id"]
            if "flush_id" in detail:
                obj["flush_id"] = detail["flush_id"]
            if "subject_digest" in detail:
                obj["subject_digest"] = detail["subject_digest"]

        # evidence
        evidence_list: List[str] = []
        if ev["evidence_path"]:
            evidence_list.append(ev["evidence_path"])
        obj["evidence"] = evidence_list

        lines.append(json.dumps(obj, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else ""), warnings



def _extract_blockers(conn, task_id: str, current_state: str) -> List[str]:
    """推导 blockers：当前 BLOCKED 时填最近一条 BLOCKED 事件摘要，否则空数组。"""
    if current_state != "BLOCKED":
        return []
    row = conn.execute(
        """
        SELECT summary FROM task_event
        WHERE task_id = ? AND event_type = 'STATE' AND to_state = 'BLOCKED'
        ORDER BY id DESC LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    if row and row["summary"]:
        return [row["summary"]]
    return []


def _atomic_write(path: Path, text: str) -> None:
    """临时文件 + os.replace 原子替换（UTF-8 无 BOM、LF）。

    同盘临时文件保证 os.replace 原子性；临时文件带 uuid 后缀避免与
    并发/残留冲突。中断残留的 *.tmp 由 reconcile 检测并清理。
    """
    import uuid

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(tmp, path)


def render_projection(conn, task) -> Tuple[str, str, List[str]]:
    """从 DB 渲染 status.yaml 与 events.jsonl 文本（不落盘）。

    供 commit（事务内预演渲染后原子落盘）与 reconcile（以 DB 为权威重建）共用。
    返回 (status_yaml, events_jsonl, warnings)。
    """
    task_id = task["task_id"]
    base_version = str(task["base_version"] or "")
    # V5.2.1 单一活动契约：旧契约非终态任务须先经官方 migrate/retire 处理；业务命令不直接在旧契约上重建投影。
    if base_version != active_version():
        raise ValueError(
            f"legacy contract task is a frozen static archive; the V5.2.1 runtime "
            f"rebuilds projections only for base_version={active_version()}"
        )
    events = conn.execute(
        "SELECT * FROM task_event WHERE task_id = ? ORDER BY id",
        (task_id,),
    ).fetchall()
    blockers = _extract_blockers(conn, task_id, task["current_state"] or "")
    created_date = ""
    if task["created_at"]:
        created_date = task["created_at"][:10]
    status_yaml = _format_status_yaml(
        task_id=task_id,
        task_name=task["title"] or "",
        created=created_date,
        base_version=base_version,
        current_state=task["current_state"] or "NEW",
        current_phase=task["current_stage"] or "intake",
        current_owner=task["owner_role"] or "tp-architecture-design",
        risk_level=task["risk_level"] or "L1",
        flow_level=task["flow_level"] or "L1",
        blockers=blockers,
        findings=[],  # M3 简化：空数组
        scope_changes=[],  # M3 简化：空数组
    )
    events_jsonl, warnings = _build_events_jsonl(events, task_id)
    return status_yaml, events_jsonl, warnings


def write_projection_files(task_dir: Path, status_yaml: str, events_jsonl: str) -> Tuple[Path, Path]:
    """原子写 status.yaml 与 events.jsonl。返回 (status_path, events_path)。"""
    status_path = task_dir / "status.yaml"
    events_path = task_dir / "events.jsonl"
    _atomic_write(status_path, status_yaml)
    _atomic_write(events_path, events_jsonl)
    return status_path, events_path


def cmd_projection_rebuild(args) -> int:
    task_id = args.task
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {task_id}", file=sys.stderr)
            return 4
        try:
            status_yaml, events_jsonl, warnings = render_projection(conn, task)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 5
        task_dir = _resolve_task_dir(args.task_dir, task_id, conn)
        task_dir.mkdir(parents=True, exist_ok=True)
        status_path, events_path = write_projection_files(task_dir, status_yaml, events_jsonl)
        for w in warnings:
            print(f"WARN: {w}", file=sys.stderr)
        print(f"Projection rebuilt: {status_path}, {events_path}")
        return 0
    finally:
        conn.close()


def _parse_status_yaml(text: str) -> Dict[str, str]:
    """极简解析 status.yaml 的关键字段（仅用于 validate 比对）。"""
    result: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#") or line.startswith(" "):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            # 去掉引号
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            result[key] = value
    return result


def validate_projection_files(conn, task, task_dir: Path) -> List[str]:
    """校验投影文件与 DB 一致，返回错误列表（空列表 = 一致）。

    V5.2.1 A-04：reconcile 复用本函数做漂移检测（与 cmd_projection_validate 同逻辑）。
    """
    task_id = task["task_id"]
    status_path = task_dir / "status.yaml"
    events_path = task_dir / "events.jsonl"
    errors: List[str] = []
    if not status_path.exists():
        return [f"status.yaml not found: {status_path}"]
    if not events_path.exists():
        return [f"events.jsonl not found: {events_path}"]
    with open(status_path, "r", encoding="utf-8") as f:
        status_text = f.read()
    status = _parse_status_yaml(status_text)
    if status.get("task_id") != task["task_id"]:
        errors.append(f"task_id mismatch: status.yaml={status.get('task_id')}, db={task['task_id']}")
    if status.get("current_state") != task["current_state"]:
        errors.append(f"current_state mismatch: status.yaml={status.get('current_state')}, db={task['current_state']}")
    if status.get("risk_level") != task["risk_level"]:
        errors.append(f"risk_level mismatch: status.yaml={status.get('risk_level')}, db={task['risk_level']}")
    with open(events_path, "r", encoding="utf-8") as f:
        event_lines = [line.strip() for line in f if line.strip()]
    db_event_count = conn.execute(
        "SELECT COUNT(*) AS c FROM task_event WHERE task_id = ?", (task_id,)
    ).fetchone()["c"]
    if len(event_lines) != db_event_count:
        errors.append(f"events.jsonl line count mismatch: file={len(event_lines)}, db={db_event_count}")
    latest_state = None
    for i, line in enumerate(event_lines, 1):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"events.jsonl line {i} invalid JSON: {e}")
            continue
        for field in ("id", "time", "type", "actor"):
            if not ev.get(field):
                errors.append(f"events.jsonl line {i} missing field '{field}'")
        if ev.get("type") == "STATE":
            latest_state = ev.get("state")
    if latest_state is not None and latest_state != task["current_state"]:
        errors.append(f"latest STATE event state mismatch: events.jsonl={latest_state}, db={task['current_state']}")
    return errors


def cmd_projection_validate(args) -> int:
    task_id = args.task
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {task_id}", file=sys.stderr)
            return 4
        task_dir = _resolve_task_dir(args.task_dir, task_id, conn)
        errors = validate_projection_files(conn, task, task_dir)
        if errors:
            print(f"Projection validate FAIL: {task_id}", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            return 6
        print(f"Projection OK: {task_id}")
        return 0
    finally:
        conn.close()


def add_projection_subparsers(projection_parser) -> None:
    """注册 projection 命令组的子命令。"""
    sub = projection_parser.add_subparsers(dest="subcommand", required=True)

    # projection rebuild
    p_rebuild = sub.add_parser("rebuild", help="Rebuild status.yaml and events.jsonl from DB")
    p_rebuild.add_argument("--task", required=True, help="task id")
    p_rebuild.add_argument("--task-dir", required=False, default=None, help="task directory path")
    p_rebuild.add_argument("--db", required=False, default=None)
    p_rebuild.set_defaults(func=cmd_projection_rebuild)

    # projection validate
    p_validate = sub.add_parser("validate", help="Validate projection files against DB")
    p_validate.add_argument("--task", required=True, help="task id")
    p_validate.add_argument("--task-dir", required=False, default=None, help="task directory path")
    p_validate.add_argument("--db", required=False, default=None)
    p_validate.set_defaults(func=cmd_projection_validate)
