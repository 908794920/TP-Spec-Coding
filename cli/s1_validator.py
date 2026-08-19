# -*- coding: utf-8 -*-
"""V5.2.4 C5 S1 声明拒绝校验器（S1/S2/S3 四级证据矩阵）。

设计依据：历史设计记录 C5-S1-declaration-rejection-design §3-§4
证据锚点：升级计划 §5（L289-294）、§7（L316）；评审表 Q6（L325）；B-17 设计 §3.5（C5-P1~P6）。

确定性校验，无网络/模型/DB；与 C1 anchor_check、敏感扫描正交独立
（本模块不 import anchor_check/sensitive_scanner/review_preflight）。

规则（设计 §4.2）：
- R1 S1+implementation_basis → S1_IMPLEMENTATION_REJECTED
- R2 S1+pass_evidence → S1_PASS_EVIDENCE_REJECTED
- R3 S3+(implementation_basis|performance_claim|acceptance_evidence|pass_evidence)
  → S3_IMPLEMENTATION_REJECTED
- R4 S1+s3_risk_labeled==false → S1_NO_S3_RISK_LABEL（要求标注，不单独拒绝）
- R5 S2+可回链形态（file:line / file:symbol:line）→ 放行
- R6 S1+related_candidate → S1_RELATED_CANDIDATE_REJECTED（OCR README 归并实证场景）
- R7 UNKNOWN/无法识别（等级非法/用途非法/S2 不可回链）→ fail-closed 视为 S1 拒绝
- R8 输入解析/规则加载异常 → S1_VALIDATOR_ERROR（异常即拒绝，不静默放行）

D1 decision 优先级固定：rejected > requires_label > accepted；
errors[] 确定性排序（sorted）。
"""

from __future__ import annotations

import re
from typing import Any

_S1_VALIDATOR_VERSION = "1.0.0"

# --- 错误码枚举（逐字节等于设计 §4.3）---
S1_IMPLEMENTATION_REJECTED = "S1_IMPLEMENTATION_REJECTED"
S1_PASS_EVIDENCE_REJECTED = "S1_PASS_EVIDENCE_REJECTED"
S3_IMPLEMENTATION_REJECTED = "S3_IMPLEMENTATION_REJECTED"
S1_NO_S3_RISK_LABEL = "S1_NO_S3_RISK_LABEL"
S1_RELATED_CANDIDATE_REJECTED = "S1_RELATED_CANDIDATE_REJECTED"
S1_VALIDATOR_ERROR = "S1_VALIDATOR_ERROR"

_DECISION_ACCEPTED = "accepted"
_DECISION_REJECTED = "rejected"
_DECISION_REQUIRES_LABEL = "requires_label"

_EVIDENCE_LEVELS = ("S1", "S2", "S3")
_PURPOSES = (
    "implementation_basis",
    "pass_evidence",
    "performance_claim",
    "acceptance_evidence",
    "design_reference",
    "related_candidate",
    "unknown",
)
_S3_BANNED_PURPOSES = (
    "implementation_basis",
    "performance_claim",
    "acceptance_evidence",
    "pass_evidence",
)

# 拒绝类错误码（D1：命中任一 → decision=rejected；R4 不在其中）
_REJECT_CODES = (
    S1_IMPLEMENTATION_REJECTED,
    S1_PASS_EVIDENCE_REJECTED,
    S3_IMPLEMENTATION_REJECTED,
    S1_RELATED_CANDIDATE_REJECTED,
    S1_VALIDATOR_ERROR,
)

# 可回链形态：file:line 或 file:symbol:line
_LINKABLE_RE = re.compile(r"^[^:]+:\d+$|^[^:]+:[^:]+:\d+$")


def _is_linkable(source: str | None) -> bool:
    return bool(_LINKABLE_RE.fullmatch((source or "").strip()))


def _rejection_message(errors: list[str]) -> str:
    if S1_IMPLEMENTATION_REJECTED in errors:
        return "S1 不得作为实施依据"
    if S1_PASS_EVIDENCE_REJECTED in errors:
        return "S1 不得作为 PASS 证据"
    if S3_IMPLEMENTATION_REJECTED in errors:
        return "S3 不得作为实施/性能/验收证据"
    if S1_RELATED_CANDIDATE_REJECTED in errors:
        return "拒绝作为关联规则依据；按 basename 归并自建实现"
    if S1_VALIDATOR_ERROR in errors:
        return "S1 校验器异常，fail-closed 按拒绝处理"
    return "evidence declaration rejected (fail-closed)"


def validate_declaration(declaration: dict[str, Any]) -> dict[str, Any]:
    """对单条 evidence_declaration 执行 R1-R7 确定性判定。

    必填字段缺失/类型错误 → 抛 ValueError（由 validate_declarations 按 R8 兜底）。
    """
    decl_id = declaration["id"]
    source = declaration.get("source") or ""
    level = (declaration.get("evidence_level") or "").strip().upper()
    purpose = (declaration.get("purpose") or "").strip().lower()
    labeled = bool(declaration.get("s3_risk_labeled", False))

    errors: list[str] = []

    # R7：证据等级非法/无法识别 → fail-closed 视为 S1 拒绝
    if level not in _EVIDENCE_LEVELS:
        errors.append(S1_IMPLEMENTATION_REJECTED)
        return {
            "declaration_id": decl_id,
            "decision": _DECISION_REJECTED,
            "errors": sorted(errors),
            "message": "UNKNOWN/unsupported evidence level; fail-closed treated as S1 rejection",
            "s1_validator_version": _S1_VALIDATOR_VERSION,
        }

    # R7：用途非法/无法识别 → fail-closed 拒绝
    if purpose not in _PURPOSES:
        errors.append(S1_IMPLEMENTATION_REJECTED)
        return {
            "declaration_id": decl_id,
            "decision": _DECISION_REJECTED,
            "errors": sorted(errors),
            "message": "UNKNOWN purpose; fail-closed treated as S1 rejection",
            "s1_validator_version": _S1_VALIDATOR_VERSION,
        }

    if level == "S1":
        # R1：S1 作为实施依据
        if purpose == "implementation_basis":
            errors.append(S1_IMPLEMENTATION_REJECTED)
        # R2：S1 作为 PASS 证据
        if purpose == "pass_evidence":
            errors.append(S1_PASS_EVIDENCE_REJECTED)
        # R6：S1 作为关联候选依据（OCR README 归并实证场景）
        if purpose == "related_candidate":
            errors.append(S1_RELATED_CANDIDATE_REJECTED)
        # R4：S1 引用须标注 S3 风险（Q6）
        if not labeled:
            errors.append(S1_NO_S3_RISK_LABEL)
    elif level == "S3":
        # R3：S3 不得作为实施/性能/验收证据
        if purpose in _S3_BANNED_PURPOSES:
            errors.append(S3_IMPLEMENTATION_REJECTED)
    elif level == "S2":
        # R5：S2 + 可回链形态 → 放行；S2 不可回链 → R7 fail-closed 拒绝
        if not _is_linkable(source):
            errors.append(S1_IMPLEMENTATION_REJECTED)
            return {
                "declaration_id": decl_id,
                "decision": _DECISION_REJECTED,
                "errors": sorted(errors),
                "message": "S2 declaration without linkable file:line/symbol:line source; fail-closed rejected",
                "s1_validator_version": _S1_VALIDATOR_VERSION,
            }

    # D1：decision 优先级 rejected > requires_label > accepted
    reject_hits = [code for code in errors if code in _REJECT_CODES]
    if reject_hits:
        decision = _DECISION_REJECTED
        message = _rejection_message(reject_hits)
    elif S1_NO_S3_RISK_LABEL in errors:
        decision = _DECISION_REQUIRES_LABEL
        message = "引用 S1 声明须标注 S3 风险（Q6）"
    else:
        decision = _DECISION_ACCEPTED
        message = "accepted"

    return {
        "declaration_id": decl_id,
        "decision": decision,
        "errors": sorted(errors),
        "message": message,
        "s1_validator_version": _S1_VALIDATOR_VERSION,
    }


def validate_declarations(declarations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """批量校验；单条解析异常 → R8 fail-closed（S1_VALIDATOR_ERROR，不静默放行）。"""
    results: list[dict[str, Any]] = []
    for idx, declaration in enumerate(declarations):
        try:
            results.append(validate_declaration(declaration))
        except Exception as exc:
            results.append({
                "declaration_id": declaration.get("id") if isinstance(declaration, dict) else f"<index:{idx}>",
                "decision": _DECISION_REJECTED,
                "errors": [S1_VALIDATOR_ERROR],
                "message": f"S1 validator error: {type(exc).__name__}: {exc}",
                "s1_validator_version": _S1_VALIDATOR_VERSION,
            })
    return results


def any_rejected(results: list[dict[str, Any]]) -> bool:
    """任一声明 decision==rejected（fail-closed 聚合，供 preflight 退出码判定）。"""
    return any(r.get("decision") == _DECISION_REJECTED for r in results)
