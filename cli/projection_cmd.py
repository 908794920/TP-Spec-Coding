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
from . import command_context

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import db as dbmod
from .version import active_version

DEFAULT_OWNER_ROLE = "tp-software-lifecycle"


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
# 执行计划、步骤、工作段和 REWORK 投影为 FACT，保留 detail 中的真实 event_type。
_TYPE_MAP = {
    "STATE": "STATE",
    "HUMAN_AUTHORITY_RECORDED": "FACT",
    "SECURITY_PROPOSAL_RECORDED": "FACT",
    "SECURITY_WORK_BOUND": "FACT",
    "SECURITY_EVIDENCE_RECORDED": "FACT",
    "EXECUTION_PLAN_RECORDED": "FACT",
    "EXECUTION_STEP_RECORDED": "FACT",
    "WORK_SESSION_UPDATED": "FACT",
    "WORK_SESSION_STARTED": "FACT",
    "WORK_SESSION_ENDED": "FACT",
    "REWORK": "FACT",
    "WORK_ITEM_RECORDED": "FACT",
    "WORK_INTEGRATION_RECORDED": "FACT",
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
    "KNOWLEDGE_CONVERGENCE_REQUEST": "KNOWLEDGE",
    "KNOWLEDGE_CONVERGENCE_RESULT": "KNOWLEDGE",
    "KNOWLEDGE": "KNOWLEDGE",
    # A-04：reconcile 追加的审计事件；投影为 FACT 保持
    # events.jsonl 合法 type 集合不变（Test-TpSpecTask.ps1 EventTypes 零感知）。
    "RECONCILIATION": "FACT",
}


# 新工件（AI-B 模板定义；AI-C 可继续追加）：存在才纳入 source digest。
_V511_SOURCE_NAMES = (
    "requirement.md",
    "requirement-knowledge.md",
    "requirement-clarifications.md",
    "requirement-decisions.md",
    "architecture-review.md",
    "requirement-test-guide.md",
)


def projection_source_names() -> List[str]:
    """current view source_files 集中注册表（§10.2）。

    AI-C 接入新工件规则时可追加文件名；commit 的
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
    quality_facts: Dict[str, str],
    next_responsibility: str,
    presentation: Optional[Dict[str, Any]] = None,
) -> str:
    """手写兼容 status.yaml 投影。"""
    lines: List[str] = []

    def fmt_list(items: List[str]) -> str:
        return json.dumps(items, ensure_ascii=False)

    def fmt_str(s: str) -> str:
        return json.dumps(str(s), ensure_ascii=False)

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
    lines.append(f"next_responsibility: {fmt_str(next_responsibility)}")
    if presentation is not None:
        from .task_views import SCHEMA
        lines.append(f"projection_schema: {fmt_str(SCHEMA)}")
        for key, value in presentation.items():
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.append("quality_facts:")
    lines.append(f"  change_set_id: {fmt_str(quality_facts.get('change_set_id', 'NOT_RECORDED'))}")
    for key in ("development", "verification", "review", "delivery", "knowledge", "memory"):
        lines.append(f"  {key}: {fmt_str(quality_facts.get(key, 'NOT_RECORDED'))}")
    lines.append("artifacts:")
    lines.append('  event_log: "events.jsonl"')
    lines.append('  continuation: "generated/continuation.md"')
    if current_state == "COMPLETED":
        lines.append('  current_view: "generated/final-result.md"')
        lines.append('  final_result: "generated/final-result.md"')
    else:
        lines.append('  current_view: "generated/continuation.md"')
    lines.append('  terminal_manifest: "generated/terminal-manifest.json"')
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
            "runtime_event_id": ev["id"],
            "event_type": event_type,
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
            for key in ("verification_scope", "checks"):
                if key in detail:
                    obj[key] = detail[key]

        # Keep explicit execution identities and payloads in the existing derived log.
        # The DB remains canonical; generic FACT imports cannot become governed events.
        if event_type in {"EXECUTION_PLAN_RECORDED", "EXECUTION_STEP_RECORDED",
                         "WORK_ITEM_RECORDED", "WORK_INTEGRATION_RECORDED",
                          "WORK_SESSION_STARTED", "WORK_SESSION_UPDATED", "WORK_SESSION_ENDED"}:
            raw_detail = ev["detail_json"] or "{}"
            try:
                execution_detail = json.loads(raw_detail)
            except (TypeError, ValueError):
                execution_detail = None
            explicit_kind = event_type in {"EXECUTION_PLAN_RECORDED", "EXECUTION_STEP_RECORDED", "WORK_SESSION_UPDATED", "WORK_ITEM_RECORDED", "WORK_INTEGRATION_RECORDED"}
            if explicit_kind or (isinstance(execution_detail, dict) and "execution_schema" in execution_detail):
                obj.update(event_type=event_type, runtime_event_id=ev["id"],
                           actor_role=ev["actor_role"], actor_agent=ev["actor_agent"],
                           work_item_id=ev["work_item_id"])
                if isinstance(execution_detail, dict):
                    obj["detail"] = execution_detail
                else:
                    obj["detail_raw"] = raw_detail
                    warnings.append(f"event #{ev['id']} has invalid execution detail; raw value preserved")

        # Security provenance stays readable in the derived log, without granting
        # generic imports permission to recreate governed facts.
        if event_type in {"HUMAN_AUTHORITY_RECORDED", "SECURITY_PROPOSAL_RECORDED",
                          "SECURITY_WORK_BOUND", "SECURITY_EVIDENCE_RECORDED", "SCOPE_CHANGE"}:
            raw = ev["detail_json"] or "{}"
            try:
                security_detail = json.loads(raw)
            except (TypeError, ValueError):
                security_detail = None
            if event_type != "SCOPE_CHANGE" or (isinstance(security_detail, dict) and "security_schema" in security_detail):
                obj.update(event_type=event_type, runtime_event_id=ev["id"], work_item_id=ev["work_item_id"])
                if isinstance(security_detail, dict):
                    obj["detail"] = security_detail
                else:
                    obj["detail_raw"] = raw
                    warnings.append(f"event #{ev['id']} has invalid security detail; raw value preserved")

        # Compact learning outcomes stay navigable in the existing event projection.
        # A projected receipt is history, not authorization or current applicability.
        if event_type == "KNOWLEDGE_CONVERGENCE_RESULT":
            from .task_views import learning_brief
            try:
                detail = json.loads(ev["detail_json"] or "{}")
                if isinstance(detail, dict):
                    obj["learning"] = learning_brief(detail)
            except (ValueError, TypeError):
                warnings.append(f"event #{ev['id']} has unreadable learning detail")

        if event_type == "DELIVERY_RESULT":
            from .task_views import excerpt
            try:
                delivery = json.loads(ev["detail_json"] or "{}")
                if isinstance(delivery, dict):
                    risks = delivery.get("residual_risks", [])
                    obj["delivery"] = {"status": delivery.get("delivery_status"),
                                       "reason": excerpt(delivery.get("reason")),
                                       "residual_risks": [excerpt(risk) for risk in risks] if isinstance(risks, list) else None}
            except (ValueError, TypeError):
                warnings.append(f"event #{ev['id']} has unreadable delivery detail")

        # evidence
        evidence_list: List[str] = []
        if ev["evidence_path"]:
            evidence_list.append(ev["evidence_path"])
        obj["evidence"] = evidence_list

        lines.append(json.dumps(obj, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else ""), warnings



def _extract_blockers(conn, task_id: str, current_state: str, waiting_fact: Optional[dict] = None) -> List[str]:
    """投影当前仍有效的公开 blocker 与 Delivery blocker。"""
    blockers: List[str] = []
    if current_state == "BLOCKED":
        row = conn.execute(
            """
            SELECT summary FROM task_event
            WHERE task_id = ? AND event_type = 'STATE' AND to_state = 'BLOCKED'
            ORDER BY id DESC LIMIT 1
            """,
            (task_id,),
        ).fetchone()
        if row and row["summary"]:
            blockers.append(str(row["summary"]))

    if waiting_fact:
        reason = str(waiting_fact.get("reason") or "").strip()
        if reason and reason not in blockers:
            blockers.append(reason)
        blockers.append(f"等待类型：{waiting_fact['kind']}；恢复条件：{waiting_fact['condition']}")
        dependencies = waiting_fact.get("requires_tasks") or []
        if dependencies:
            blockers.append("等待依赖：" + ", ".join(dependencies))
    return blockers


def _latest_code_review_fact(conn, task_id: str):
    """CODE aliases are one chronological lane, not three independent reviews."""
    from . import event_policies

    candidates = event_policies.load_trusted_governance_events(
        conn, task_id, event_type="REVIEW_COMPLETED", actor="tp-code-reviewer", latest_only=True,
    )
    return next((item for item in candidates
                 if str(item.detail.get("review_kind") or "").upper() in {"CODE", "IMPLEMENTATION", "ULTRA_REVIEW"}), None)


def _extract_findings(conn, task_id: str) -> List[str]:
    """投影最新未被后续有效 PASS 闭环的验证/代码审查 finding。"""
    from . import event_policies

    findings: List[str] = []
    verification = event_policies.load_trusted_governance_event(
        conn, task_id, event_type="VERIFICATION_COMPLETED", actor="tp-test-engineer", latest_only=True,
    )
    if verification is not None:
        decision = str(verification.detail.get("decision") or "").upper()
        if decision in {"FAIL", "NEEDS_FIX"}:
            summary = str(verification.detail.get("summary") or verification.row["summary"] or "").strip()
            findings.append(summary or f"verification {decision}")

    review = _latest_code_review_fact(conn, task_id)
    if review is not None:
        decision = str(review.detail.get("decision") or "").upper()
        if decision in {"NEEDS_FIX", "REVISE", "FAIL"}:
            summary = str(review.detail.get("summary") or review.row["summary"] or "").strip()
            findings.append(summary or f"review {decision}")
    return findings


def _extract_scope_changes(conn, task_id: str) -> List[str]:
    """按发生顺序投影可信 human_owner 范围变化。"""
    from . import event_policies

    events = event_policies.load_trusted_governance_events(
        conn, task_id, event_type="SCOPE_CHANGE", actor="human_owner",
    )
    out: List[str] = []
    for event in reversed(events):
        scope_id = str(event.detail.get("scope_id") or "").strip()
        summary = str(event.detail.get("summary") or event.row["summary"] or "").strip()
        if scope_id and summary:
            security = event.detail.get("security_payload") if event.detail.get("security_schema") else None
            if isinstance(security, dict):
                out.append(f"{scope_id} [{security.get('decision', 'UNKNOWN')}; scopes={','.join(security.get('scope_ids', []))}; source event:{security.get('human_event_id')}]: {summary}")
            else:
                out.append(f"{scope_id}: {summary}")
    return out


def _latest_development_fact(conn, task_id: str) -> Dict[str, Any]:
    """返回最新可信 Development checkpoint 的事件 id、Change Set 与仓库根。"""
    from . import event_contract

    rows = conn.execute(
        "SELECT id, detail_json FROM task_event WHERE task_id=? AND event_type='FACT' ORDER BY id DESC",
        (task_id,),
    ).fetchall()
    for row in rows:
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(detail, dict):
            continue
        if detail.get("producer") != "record-first" or str(detail.get("schema") or "") != event_contract.EVENT_SCHEMA:
            continue
        if str(detail.get("operation") or "").upper() != "CHECKPOINT":
            continue
        if str(detail.get("phase") or "").lower() != "development":
            continue
        if str(detail.get("result_status") or "").upper() != "COMPLETED":
            continue
        change_set_id = str(detail.get("change_set_id") or "").strip()
        roots = [str(value).strip() for value in (detail.get("repo_roots") or []) if str(value).strip()]
        if change_set_id:
            return {"event_id": int(row["id"]), "change_set_id": change_set_id, "repo_roots": roots, "detail": detail}
    return {}


def _current_change_set(development: Dict[str, Any]) -> tuple[str, str]:
    """返回 (current_digest, development_status)；Git 读取失败时不伪造 CURRENT。"""
    recorded = str(development.get("change_set_id") or "")
    roots = list(development.get("repo_roots") or [])
    if not recorded:
        return "", "NOT_RECORDED"
    if not roots:
        return recorded, "UNKNOWN"
    try:
        from .change_set import capture_change_set, same_bound_product_content
        snapshot = capture_change_set(roots)
        current = str(snapshot.get("content_digest") or "")
        matches = same_bound_product_content(development["detail"], snapshot)
    except Exception:
        return recorded, "UNKNOWN"
    return current, "CURRENT" if matches else "STALE"


def _stale_value(value: str, *, stale: bool) -> str:
    value0 = str(value or "NOT_RECORDED").upper()
    return f"{value0}_STALE" if stale and value0 != "NOT_RECORDED" else value0


def _extract_quality_facts(conn, task_id: str) -> Dict[str, str]:
    """从可信账本和当前 Git 内容投影 current/stale 质量事实。"""
    from . import event_policies

    development = _latest_development_fact(conn, task_id)
    current_digest, development_status = _current_change_set(development)
    recorded_digest = str(development.get("change_set_id") or "")
    current_id = current_digest or recorded_digest or "NOT_RECORDED"
    out = {
        "change_set_id": current_id,
        "development": development_status,
        "verification": "NOT_RECORDED",
        "review": "NOT_RECORDED",
        "delivery": "NOT_RECORDED",
        # Task 7 会把这一占位投影替换为 typed Knowledge convergence 事实。
        "knowledge": "NOT_RECORDED",
        "memory": "NOT_RECORDED",
    }
    location = conn.execute(
        "SELECT p.root_path FROM task t JOIN project p ON p.project_id=t.project_id WHERE t.task_id=?",
        (task_id,),
    ).fetchone()
    task_dir = Path(location[0]) / ".tp-spec" / "tasks" / task_id if location and location[0] else None
    dev_event_id = int(development.get("event_id") or 0)
    dev_stale = development_status != "CURRENT"

    verification = event_policies.load_trusted_governance_event(
        conn, task_id, event_type="VERIFICATION_COMPLETED", actor="tp-test-engineer", latest_only=True,
    )
    verification_current = False
    if verification is not None:
        v_change = str(verification.detail.get("change_set_id") or "")
        verification_current = (
            not dev_stale
            and int(verification.row["id"]) > dev_event_id
            and bool(current_digest)
            and v_change == current_digest
            and task_dir is not None
            and event_policies.verification_subject_matches(verification.detail, task_dir)
            and (verification.detail.get("decision") != "PASS"
                 or event_policies.load_current_verification(conn, task_id, task_dir) is not None)
        )
        out["verification"] = _stale_value(
            str(verification.detail.get("decision") or "NOT_RECORDED")
            + ("_TECHNICAL" if verification.detail.get("verification_scope") == "technical" else ""),
            stale=not verification_current,
        )

    review = _latest_code_review_fact(conn, task_id)
    review_current = False
    if review is not None:
        r_change = str(review.detail.get("change_set_id") or "")
        current_verification_id = int(verification.row["id"]) if verification is not None else 0
        review_current = False
        if verification_current and r_change == current_digest and task_dir is not None:
            from .workflow_records import _latest_trusted_code_review
            try:
                current_review = _latest_trusted_code_review(
                    conn, task_id, task_dir=task_dir,
                    subject_digest=str(verification.detail.get("subject_digest") or ""),
                    change_set_id=current_digest, verification_event_id=current_verification_id,
                )
                review_current = int(current_review.row["id"]) == int(review.row["id"])
            except ValueError:
                pass
        out["review"] = _stale_value(
            str(review.detail.get("decision") or "NOT_RECORDED"),
            stale=not review_current,
        )

    delivery = event_policies.load_trusted_governance_event(
        conn, task_id, event_type="DELIVERY_RESULT", latest_only=True,
    )
    delivery_current = False
    if delivery is not None:
        d_change = str(delivery.detail.get("change_set_id") or "")
        bound_review = int(delivery.detail.get("review_event_id") or 0)
        current_review_id = int(review.row["id"]) if review is not None else 0
        from .delivery_contract import delivery_result_matches_verification, delivery_evidence_matches
        delivery_current = bool(
            review_current and d_change == current_digest and bound_review == current_review_id
            and verification_current and verification is not None
            and event_policies.verification_scope(verification.detail) == "full"
            and task_dir is not None and delivery_evidence_matches(delivery.detail, task_dir)
            and delivery_result_matches_verification(
                delivery.detail, int(verification.row["id"]),
                str(verification.detail.get("subject_digest") or ""), current_digest,
            )
        )
        out["delivery"] = _stale_value(
            str(delivery.detail.get("delivery_status") or "NOT_RECORDED"),
            stale=not delivery_current,
        )

    if delivery is not None and task_dir is not None:
        from . import orchestration
        from .knowledge import convergence
        # Read the same current facts as closeout, including lightweight delivery.
        facts, rows = orchestration._load_task_facts(task_id, connection=conn, task_dir=task_dir)
        orchestration.resolve_route(task_id, _facts=(facts, rows), task_dir=task_dir)
        terminal = facts.get("current_state") in {"COMPLETED", "CANCELLED"}
        # Terminal receipts describe the accepted historical candidate; subsequent
        # workspace edits do not impose new learning obligations on old tasks.
        current_delivery = (dict(delivery.row) if terminal and delivery.detail.get("delivery_status") == "READY"
                            else orchestration._delivery_completion_event(rows, task_dir, task=facts))
        adopted = delivery.detail.get("closeout_schema") == "tp-spec.closeout/v1"
        if current_delivery:
            out["delivery"] = "READY"
            request = orchestration._knowledge_request_for_delivery(rows, current_delivery)
            if request is None:
                out["knowledge"] = "NOT_RUN" if adopted else "NOT_REQUIRED"
            elif adopted and not terminal and not convergence.current_request(request, rows, task_dir, facts):
                out["knowledge"] = "STALE_INPUT"
            else:
                result = orchestration._knowledge_result_for_request(rows, request, task_dir, task=facts, historical=terminal)
                out["knowledge"] = result["detail"].get("knowledge_disposition", "NOT_RUN") if result else "NOT_RUN"
                if result and result["detail"].get("memory_assessment"):
                    root = facts.get("project_root_path")
                    out["memory"] = convergence.memory_status(result["detail"]["memory_assessment"], Path(root) if root and not terminal else None)["status"]
            if adopted and out["memory"] == "NOT_RECORDED":
                out["memory"] = "NOT_RUN"

    return out


def _extract_next_responsibility(conn, task_id: str, current_owner: str, waiting_fact: Optional[dict] = None) -> str:
    """投影当前最明确的下一责任方，不创建新的 workflow state。"""
    from . import event_policies, waiting

    waiting_fact = waiting_fact or waiting.load_wait(conn, task_id)
    if waiting_fact:
        return str(waiting_fact["responsibility"])
    review = _latest_code_review_fact(conn, task_id)
    if review is not None and str(review.detail.get("decision") or "").upper() in {"NEEDS_FIX", "REVISE", "FAIL"}:
        return "tp-development-engineer"

    verification = event_policies.load_trusted_governance_event(
        conn, task_id, event_type="VERIFICATION_COMPLETED", actor="tp-test-engineer", latest_only=True,
    )
    if verification is not None and str(verification.detail.get("decision") or "").upper() in {"NEEDS_FIX", "FAIL"}:
        return "tp-development-engineer"
    return current_owner or DEFAULT_OWNER_ROLE


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


@command_context.measured("projection")
def render_projection(conn, task) -> Tuple[str, str, List[str]]:
    """从 DB 渲染 status.yaml 与 events.jsonl 文本（不落盘）。

    供 commit（事务内预演渲染后原子落盘）与 reconcile（以 DB 为权威重建）共用。
    返回 (status_yaml, events_jsonl, warnings)。
    """
    task_id = task["task_id"]
    base_version = str(task["base_version"] or "")
    # 单一活动契约：旧契约非终态任务须先经官方 migrate/retire 处理；业务命令不直接在旧契约上重建投影。
    if base_version != active_version():
        raise ValueError(
            f"legacy contract task is a frozen static archive; the current runtime "
            f"rebuilds projections only for base_version={active_version()}"
        )
    events = conn.execute(
        "SELECT * FROM task_event WHERE task_id = ? ORDER BY id",
        (task_id,),
    ).fetchall()
    from . import waiting
    state = str(task["current_state"] or "")
    waiting_fact = waiting.active_wait(events, state)
    if state in {"NEW", "ACTIVE"}:
        waiting_fact = waiting.result_wait(conn, task_id, events)
    blockers = _extract_blockers(conn, task_id, state, waiting_fact)
    created_date = ""
    if task["created_at"]:
        created_date = task["created_at"][:10]
    from .execution import read_execution
    from .task_views import execution_brief, excerpt, TERMINAL
    execution = execution_brief(read_execution(conn, task, rows=events))
    latest = dict(events[-1]) if events else {}
    next_role = ""
    if state not in TERMINAL:
        next_role = _extract_next_responsibility(conn, task_id, task["owner_role"] or DEFAULT_OWNER_ROLE, waiting_fact)
        current_step = execution.get("current_step") or {}
        next_step = execution.get("next_step") or {}
        if not waiting_fact and execution["status"] == "RECORDED":
            next_role = (current_step.get("expected_next_actor") or
                         ", ".join(execution.get("current_roles") or current_step.get("roles") or next_step.get("roles") or [])
                         or "unknown")
    status_yaml = _format_status_yaml(
        task_id=task_id,
        task_name=task["title"] or "",
        created=created_date,
        base_version=base_version,
        current_state=task["current_state"] or "NEW",
        current_phase=task["current_stage"] or "intake",
        current_owner=task["owner_role"] or DEFAULT_OWNER_ROLE,
        risk_level=task["risk_level"] or "L1",
        flow_level=task["flow_level"] or "L1",
        blockers=blockers,
        findings=_extract_findings(conn, task_id),
        scope_changes=_extract_scope_changes(conn, task_id),
        quality_facts=_extract_quality_facts(conn, task_id),
        next_responsibility=next_role,
        presentation={"fact_revision": len(events), "execution": execution,
                      "last_activity": {"event_id": latest.get("id"), "actor": latest.get("actor_role"),
                                        "time": latest.get("created_at"), "summary": excerpt(latest.get("summary"))}},
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
    conn = dbmod.connect_readonly(db_path)
    try:
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {task_id}", file=sys.stderr)
            return 4
        from .task_views import TERMINAL, inspect_task_views
        if str(task["current_state"] or "") in TERMINAL:
            task_dir = _resolve_task_dir(args.task_dir, task_id, conn)
            result = inspect_task_views(task_dir, task)
            print(json.dumps({"view_status": "SEALED", "documents": result}, ensure_ascii=False))
            return 0
        if getattr(args, "view_only", False):
            # Only an unsealed view refresh needs the writer serialization lock.
            conn.close()
            conn = dbmod.connect(db_path)
            from .transaction_commit import refresh_current_view
            task_dir = _resolve_task_dir(args.task_dir, task_id, conn)
            result = refresh_current_view(conn, task_dir, task_id)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["view_status"] in {"CURRENT", "SEALED"} else 5
        # Serialize an explicitly requested projection write with terminal sealing.
        # A read-only initial probe alone cannot prevent a concurrent completion.
        conn.close()
        conn = dbmod.connect(db_path)
        conn.execute("BEGIN IMMEDIATE")
        task = conn.execute("SELECT * FROM task WHERE task_id=?", (task_id,)).fetchone()
        if task is None:
            print("ERROR: task not found", file=sys.stderr)
            return 4
        if str(task["current_state"] or "") in TERMINAL:
            task_dir = _resolve_task_dir(args.task_dir, task_id, conn)
            print(json.dumps({"view_status": "SEALED", "documents": inspect_task_views(task_dir, task)}, ensure_ascii=False))
            return 0
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

    A-04：reconcile 复用本函数做漂移检测（与 cmd_projection_validate 同逻辑）。
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
    conn = dbmod.connect_readonly(db_path)
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


def cmd_projection_inspect(args) -> int:
    """Inspect an archive directly, or use an explicitly selected read-only Runtime."""
    from .task_views import inspect_task_views
    from .execution import read_execution
    task_dir = Path(args.task_dir).resolve()
    if not task_dir.is_dir():
        print("ERROR: task-dir not found", file=sys.stderr)
        return 4
    if not args.db:
        result = inspect_task_views(task_dir, task_id=args.task)
    else:
        conn = dbmod.connect_readonly(args.db)
        try:
            conn.execute("BEGIN")
            task = conn.execute("SELECT * FROM task WHERE task_id=?", (args.task,)).fetchone()
            if task is None:
                print("ERROR: task not found", file=sys.stderr)
                return 4
            events = conn.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id", (args.task,)).fetchall()
            result = inspect_task_views(task_dir, task, events=events, execution=read_execution(conn, task, rows=events))
        finally:
            conn.close()
    print(json.dumps(result, ensure_ascii=False))
    return 0


def add_projection_subparsers(projection_parser) -> None:
    """注册 projection 命令组的子命令。"""
    sub = projection_parser.add_subparsers(dest="subcommand", required=True)

    p_inspect = sub.add_parser("inspect", help="Read-only compact view/freshness; no DB required for an archive")
    p_inspect.add_argument("--task", required=True)
    p_inspect.add_argument("--task-dir", required=True)
    p_inspect.add_argument("--db", default=None, help="optional existing Runtime; never creates or migrates")
    p_inspect.set_defaults(func=cmd_projection_inspect)

    # projection rebuild
    p_rebuild = sub.add_parser("rebuild", help="Rebuild status.yaml and events.jsonl from DB")
    p_rebuild.add_argument("--task", required=True, help="task id")
    p_rebuild.add_argument("--task-dir", required=False, default=None, help="task directory path")
    p_rebuild.add_argument("--db", required=False, default=None)
    p_rebuild.add_argument("--view-only", action="store_true", help="rebuild unsealed continuation only; never change facts")
    p_rebuild.set_defaults(func=cmd_projection_rebuild)

    # projection validate
    p_validate = sub.add_parser("validate", help="Validate projection files against DB")
    p_validate.add_argument("--task", required=True, help="task id")
    p_validate.add_argument("--task-dir", required=False, default=None, help="task directory path")
    p_validate.add_argument("--db", required=False, default=None)
    p_validate.set_defaults(func=cmd_projection_validate)
