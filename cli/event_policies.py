# -*- coding: utf-8 -*-
"""V5.2.0 可信事件注册表（Final Hardening 单一来源）。

依据：《V5.2.0 Final Hardening Invariant 修复任务》Task 1（§3）与《V5.2.0
HARDENING 源码复审报告》P0-1/P0-2。INV-02：治理事件只能由可信生产者产生；
INV-03：门禁不信任 type/actor/summary 三元组，只接受含完整身份链的可信事件。

本模块是唯一事件权威来源：
- CLI（event add / event sync）、transition validator、PowerShell validator、
  测试共同使用本注册表；禁止各模块再维护独立 allowlist。
- ``EVENT_POLICIES``：机器可读注册表，定义每类事件的 authority /
  allowed_producers / affects_gate / required_fields。
- ``load_trusted_governance_event()``：门禁唯一入口，负责 producer、schema、
  transaction_id、digest、evidence 校验；任一缺失返回 None（fail-closed）。

事件分类：
- ``public_fact``（authority=public_fact，affects_gate=False）：安全事实类，
  event add / event sync 允许产生，不影响任何状态机门禁。
- ``governance``（authority=governance，affects_gate=True）：治理事件，只能由
  正式命令/权威服务产生；event add 拒绝、event sync 拒绝导入。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union

# 稳定错误码
GOVERNANCE_EVENT_REQUIRES_TRUSTED_PRODUCER = "GOVERNANCE_EVENT_REQUIRES_TRUSTED_PRODUCER"
EVENT_SYNC_FACT_ONLY = "EVENT_SYNC_FACT_ONLY"
UNKNOWN_EVENT_TYPE = "UNKNOWN_EVENT_TYPE"
# Third Hardening（P0-1/P1-1）：可信事件链诊断错误码（由调用方按场景精确产出）
TRUSTED_EVENT_SCHEMA_INVALID = "TRUSTED_EVENT_SCHEMA_INVALID"
ARCHITECTURE_REVIEW_ARTIFACT_MISMATCH = "ARCHITECTURE_REVIEW_ARTIFACT_MISMATCH"
ARCHITECTURE_REVIEW_KIND_MISMATCH = "ARCHITECTURE_REVIEW_KIND_MISMATCH"
# ARCHITECTURE_REVIEW_STALE 定义于 cli/transition_service.py（保持同义常量）
ARCHITECTURE_REVIEW_STALE = "ARCHITECTURE_REVIEW_STALE"


def _policy(authority: str, producers: tuple, affects_gate: bool,
            required_fields: tuple) -> Dict[str, Any]:
    return {
        "authority": authority,
        "allowed_producers": frozenset(producers),
        "affects_gate": affects_gate,
        "required_fields": tuple(required_fields),
    }


# 治理事件身份链（INV-03 最小集合）：具体事件可增加字段，但不能少于可验证身份链。
# 各事件 required_fields 为子集（STATE/HANDOFF 无 artifact_digest 概念）。
_EVENT_SCHEMA_FIELDS = (
    "transaction_id", "producer", "schema_version", "task_id", "actor_role", "created_at",
)

# REVIEW_COMPLETED / 各类 PASS 判定事件：必须绑定工件与受评审内容 digest。
_REVIEW_IDENTITY_FIELDS = _EVENT_SCHEMA_FIELDS + (
    "decision", "artifact", "artifact_digest", "subject_digest", "evidence",
)


EVENT_POLICIES: Dict[str, Dict[str, Any]] = {
    # ============ 安全事实类（event add / event sync 允许，不影响门禁） ============
    "FACT": _policy("public_fact", ("event_add", "event_sync"), False, ("actor",)),
    "OBSERVATION": _policy("public_fact", ("event_add",), False, ("actor",)),
    "NOTE": _policy("public_fact", ("event_add",), False, ("actor",)),
    "LOG": _policy("public_fact", ("event_add",), False, ("actor",)),
    "BLOCKER": _policy("public_fact", ("event_add",), False, ("actor", "note")),
    "KNOWLEDGE": _policy("public_fact", ("event_add",), False, ("actor",)),
    # DECISION：业务决策记录（commit DIRECT_CHANGE / event add 补录）；门禁不信任。
    "DECISION": _policy("public_fact", ("event_add", "commit"), False, ("actor", "note")),
    # ============ 治理事件（仅正式命令/权威服务，event add/sync 拒绝） ============
    # ARTIFACT_REFRESH：commit --refresh 的内部动作记录；不推进状态、不影响门禁，
    # 但只能由 commit 产生（不允许 event add/sync 伪造审计噪声）。
    "ARTIFACT_REFRESH": _policy("governance", ("commit",), False, _EVENT_SCHEMA_FIELDS + ("flush_id",)),
    "STATE": _policy("governance", ("commit", "transition_task", "admin_recovery", "record-first"), True, _EVENT_SCHEMA_FIELDS + ("flush_id",)),
    "HANDOFF": _policy("governance", ("commit", "transition_task", "admin_recovery"), True, _EVENT_SCHEMA_FIELDS + ("flush_id", "to_state", "handoff_id")),
    "REVIEW_COMPLETED": _policy("governance", ("review_record", "commit"), True, _REVIEW_IDENTITY_FIELDS),
    "REVIEW": _policy("governance", ("review_record", "commit"), True, _EVENT_SCHEMA_FIELDS),
    "VERIFICATION": _policy("governance", ("commit",), True, _EVENT_SCHEMA_FIELDS),
    # V5.2.0 Record-first verification is a trusted fact but no longer a state gate.
    # It binds decision + current technical subject digest + real evidence without
    # requiring a role-authored review artifact.
    "VERIFICATION_COMPLETED": _policy(
        "governance", ("commit", "record-first"), False,
        _EVENT_SCHEMA_FIELDS + ("decision", "subject_digest", "evidence"),
    ),
    "CANCEL_REQUESTED": _policy("governance", ("transition_task", "commit"), True, _EVENT_SCHEMA_FIELDS),
    "CANCEL_CONFIRMED": _policy("governance", ("transition_task", "commit"), True, _EVENT_SCHEMA_FIELDS),
    "RECONCILIATION": _policy("governance", ("reconcile", "task_migrate"), True, _EVENT_SCHEMA_FIELDS + ("flush_id",)),
    # TASK_RETIRED does not falsify workflow state. It administratively removes a
    # non-terminal historical instance from the active set (for example when it was
    # superseded by a rebuilt task). The last workflow state remains auditable.
    "TASK_RETIRED": _policy("governance", ("task_retire",), True, _EVENT_SCHEMA_FIELDS + ("reason",)),
    "OWNER_ACCEPTANCE_DECISION": _policy("governance", ("task_acceptance_override",), True, _EVENT_SCHEMA_FIELDS + ("mode", "acs", "reason", "residual_risk")),
    "SCOPE_CHANGE": _policy("governance", ("commit", "receipt_record"), True, _EVENT_SCHEMA_FIELDS + ("scope_id",)),
    "AUDIT": _policy("governance", ("admin_recovery", "reconcile"), True, _EVENT_SCHEMA_FIELDS),
    "PHASE_EXIT": _policy("governance", ("commit",), False, _EVENT_SCHEMA_FIELDS),
    # 工作会话 / 返工：正式命令产生的动作记录，投影为 FACT；不影响状态机门禁，
    # 但只允许正式命令产生（不允许 event add/sync 伪造审计噪声）。
    "WORK_SESSION_STARTED": _policy("governance", ("work_session",), False, _EVENT_SCHEMA_FIELDS),
    "WORK_SESSION_ENDED": _policy("governance", ("work_session",), False, _EVENT_SCHEMA_FIELDS),
    "REWORK": _policy("governance", ("rework",), False, _EVENT_SCHEMA_FIELDS),
}


def load_owner_acceptance_decisions(conn, task_id: str) -> list[dict]:
    """Load trusted human_owner acceptance defer/waive decisions from the ledger."""
    rows = conn.execute(
        "SELECT * FROM task_event WHERE task_id=? AND event_type='OWNER_ACCEPTANCE_DECISION' ORDER BY id",
        (task_id,),
    ).fetchall()
    out = []
    for row in rows:
        if str(row["actor_role"] or "") != "human_owner":
            continue
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except Exception:
            continue
        if not isinstance(detail, dict):
            continue
        if detail.get("producer") != "task_acceptance_override":
            continue
        if not detail.get("transaction_id") or not detail.get("schema_version"):
            continue
        if str(detail.get("actor_role") or "") != "human_owner":
            continue
        mode = str(detail.get("mode") or "").lower()
        acs = detail.get("acs")
        if mode not in {"defer", "waive"} or not isinstance(acs, list) or not acs:
            continue
        out.append(detail)
    return out


def is_governance_event(event_type: str) -> bool:
    """事件是否治理事件（authority=governance）。未知类型按治理处理（fail-closed）。"""
    policy = EVENT_POLICIES.get(event_type)
    return bool(policy and policy["authority"] == "governance")


def is_public_fact_event(event_type: str) -> bool:
    """事件是否安全事实类（authority=public_fact）。"""
    policy = EVENT_POLICIES.get(event_type)
    return bool(policy and policy["authority"] == "public_fact")


def affects_gate(event_type: str) -> bool:
    """事件是否会影响状态机门禁。未知类型按 True 处理（fail-closed）。"""
    policy = EVENT_POLICIES.get(event_type)
    return bool(policy and policy.get("affects_gate"))


def allowed_event_add_types() -> list:
    """event add 允许的类型（authority=public_fact 且 allowed_producers 含 event_add）。"""
    return sorted(
        t for t, p in EVENT_POLICIES.items()
        if "event_add" in p["allowed_producers"]
    )


def allowed_event_sync_types() -> list:
    """event sync 允许的类型（allowed_producers 含 event_sync）。默认仅 FACT。"""
    return sorted(
        t for t, p in EVENT_POLICIES.items()
        if "event_sync" in p["allowed_producers"]
    )


def event_allowed_for_producer(event_type: str, producer: str) -> bool:
    """判断 producer（正式命令名）是否被允许产生该事件。未知 producer 一律拒绝。"""
    policy = EVENT_POLICIES.get(event_type)
    if not policy:
        return False
    return producer in policy["allowed_producers"]


@dataclass
class TrustedEvent:
    """门禁通过的可信治理事件（含事件行 + 解析后的 detail）。"""
    row: Any
    detail: Dict[str, Any]
    policy: Dict[str, Any]


def _event_detail(row) -> Dict[str, Any]:
    if not row["detail_json"]:
        return {}
    try:
        data = json.loads(row["detail_json"])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _file_sha256(path: Path) -> str:
    # Review artifacts are text contracts.  Bind semantic bytes rather than
    # transport line endings/BOM so editor re-save does not invalidate PASS.
    from .digest import compute_text_artifact_file_digest
    return compute_text_artifact_file_digest(path)


def load_trusted_governance_event(
    conn,
    task_id: str,
    *,
    event_type: str,
    actor: Optional[str] = None,
    decision: Optional[str] = None,
    detail_required: Optional[tuple] = None,
    review_kind: Optional[str] = None,
    artifact_path: Optional[Union[str, Path]] = None,
    expected_subject_digest: Optional[str] = None,
    evidence_dir: Optional[Union[str, Path]] = None,
) -> Optional[TrustedEvent]:
    """Load the most recent *valid* trusted governance event.

    Rows are scanned newest-first and each candidate is validated completely.
    An unrelated or malformed newer event must not hide an older valid event,
    while no invalid candidate is ever accepted (fail-closed).
    """
    policy = EVENT_POLICIES.get(event_type)
    if not policy or policy["authority"] != "governance":
        return None
    rows = conn.execute(
        "SELECT * FROM task_event WHERE task_id=? AND event_type=? ORDER BY id DESC",
        (task_id, event_type),
    ).fetchall()
    fields = tuple(detail_required) if detail_required is not None else policy["required_fields"]
    for row in rows:
        detail = _event_detail(row)
        producer = detail.get("producer") or detail.get("source_command") or ""
        if producer not in policy["allowed_producers"]:
            continue
        if not detail.get("transaction_id"):
            continue
        invalid = False
        for req in fields:
            if detail.get(req):
                continue
            if req in row.keys() and row[req]:
                continue
            invalid = True
            break
        if invalid:
            continue
        if actor is not None and (row["actor_role"] or "") != actor:
            continue
        if decision is not None:
            ev_decision = detail.get("decision") or row["summary"] or ""
            if str(ev_decision).upper() != str(decision).upper():
                continue
        if review_kind is not None:
            kind = detail.get("review_kind") or ""
            if not kind or str(kind).upper() != str(review_kind).upper():
                continue
        if artifact_path is not None:
            declared = detail.get("artifact_digest") or ""
            current = _file_sha256(Path(artifact_path))
            if not declared or not current or declared != current:
                continue
        if expected_subject_digest is not None:
            declared_subject = detail.get("subject_digest") or detail.get("design_digest") or ""
            if not declared_subject or declared_subject != expected_subject_digest:
                continue
        if evidence_dir is not None:
            # Governance PASS evidence must be independent, immutable evidence
            # stored below evidence/.  Projection files and review artifacts are
            # never accepted as proof of themselves.
            items = detail.get("evidence_items")
            if not isinstance(items, list) or not items:
                continue
            from .evidence import validate_evidence_path
            evidence_ok = True
            for item in items:
                if not isinstance(item, dict):
                    evidence_ok = False
                    break
                checked = validate_evidence_path(
                    evidence_dir, item, require_evidence_dir=True
                )
                if not checked.ok:
                    evidence_ok = False
                    break
                if str(item.get("sha256") or "") != checked.sha256:
                    evidence_ok = False
                    break
            if not evidence_ok:
                continue
        return TrustedEvent(row=row, detail=detail, policy=policy)
    return None


def has_trusted_governance_event(
    conn,
    task_id: str,
    *,
    event_type: str,
    actor: Optional[str] = None,
    decision: Optional[str] = None,
) -> bool:
    """门禁便捷入口：可信治理事件是否存在。"""
    return load_trusted_governance_event(
        conn, task_id, event_type=event_type, actor=actor, decision=decision,
    ) is not None


def load_task_retirement(conn, task_id: str) -> Optional[TrustedEvent]:
    """Return the latest valid administrative retirement event, if any."""
    return load_trusted_governance_event(
        conn, task_id, event_type="TASK_RETIRED",
        detail_required=_EVENT_SCHEMA_FIELDS + ("reason",),
    )


def is_task_retired(conn, task_id: str) -> bool:
    """Whether a task is an administratively retired historical instance."""
    return load_task_retirement(conn, task_id) is not None
