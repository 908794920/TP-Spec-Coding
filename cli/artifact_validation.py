# -*- coding: utf-8 -*-
"""Current five-state artifact validation helpers for TP-Spec-Coding v5.2.4.

This module contains only artifact/evidence validation and trusted current-role
checks. Frozen long-state transition rules live under cli.migrations.v5_2_3.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import db as dbmod
from . import event_policies
from . import frontmatter
from . import projection_cmd
from .digest import compute_architecture_subject_digest
from .version import active_version

# 稳定错误码（ValidationIssue.code）
REQUIREMENT_KNOWLEDGE_MISSING = "REQUIREMENT_KNOWLEDGE_MISSING"
REQUIREMENT_KNOWLEDGE_INCOMPLETE = "REQUIREMENT_KNOWLEDGE_INCOMPLETE"
REQUIREMENT_KNOWLEDGE_UNPARSEABLE = "REQUIREMENT_KNOWLEDGE_UNPARSEABLE"
ACCEPTANCE_INVALID = "ACCEPTANCE_INVALID"
ACCEPTANCE_CRITERIA_MISSING = "ACCEPTANCE_CRITERIA_MISSING"
BLOCKING_CLARIFICATION_OPEN = "BLOCKING_CLARIFICATION_OPEN"
BLOCKING_CLARIFICATION_INVALID = "BLOCKING_CLARIFICATION_INVALID"
DECISIONS_MISSING = "DECISIONS_MISSING"
DECISIONS_INVALID = "DECISIONS_INVALID"
DECISIONS_UNRESOLVED_BLOCKING = "DECISIONS_UNRESOLVED_BLOCKING"
ARCHITECTURE_REVIEW_REQUIRED = "ARCHITECTURE_REVIEW_REQUIRED"
ARCHITECTURE_REVIEW_STALE = "ARCHITECTURE_REVIEW_STALE"
TEST_GUIDE_INCOMPLETE = "TEST_GUIDE_INCOMPLETE"
TEST_GUIDE_OWNER_MISMATCH = "TEST_GUIDE_OWNER_MISMATCH"
YAML_INVALID = "YAML_INVALID"
ACCEPTANCE_PENDING = "ACCEPTANCE_PENDING"
DEFERRED_ACCEPTANCE_INVALID = "DEFERRED_ACCEPTANCE_INVALID"
CODE_REVIEW_EMPTY = "CODE_REVIEW_EMPTY"
SCOPE_CHANGE_DRIFT = "SCOPE_CHANGE_DRIFT"
USER_CONFIRMATION_REQUIRED = "USER_CONFIRMATION_REQUIRED"
BASELINE_BLOCKED_ACTIVE = "BASELINE_BLOCKED_ACTIVE"
VERIFICATION_REWORK_REVIEW_REQUIRED = "VERIFICATION_REWORK_REVIEW_REQUIRED"
TEXT_INTEGRITY_INVALID = "TEXT_INTEGRITY_INVALID"
IMPLEMENTATION_INCOMPLETE = "IMPLEMENTATION_INCOMPLETE"


@dataclass
class ValidationIssue:
    code: str
    message: str
    artifact: Optional[str] = None
    field: Optional[str] = None
    severity: str = "ERROR"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "artifact": self.artifact,
            "field": self.field,
            "severity": self.severity,
        }


@dataclass
class ValidationResult:
    ok: bool
    issues: List[ValidationIssue] = field(default_factory=list)

    def error_codes(self) -> List[str]:
        return [i.code for i in self.issues]


# =============================================================================
# YAML fail-closed 解析（任务书 §9.1）
# =============================================================================

class YamlDuplicateKeyError(ValueError):
    pass


class YamlValidationError(ValueError):
    pass


def _yaml_loader():
    """构造 pyyaml loader：重复 key fail-closed。"""
    import yaml

    class _StrictLoader(yaml.SafeLoader):
        pass

    def _construct_mapping(loader, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise YamlDuplicateKeyError(f"duplicate YAML key: {key!r}")
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    _StrictLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
    )
    return _StrictLoader


def parse_frontmatter_yaml(text: str, name: str) -> Dict[str, Any]:
    """解析 front matter 为 dict；缺失/损坏/重复 key/非 mapping 一律抛 YamlValidationError。"""
    parts = frontmatter.split(text)
    if parts is None:
        raise YamlValidationError(f"{name}: missing or invalid YAML front matter")
    front, _, _ = parts
    try:
        import yaml  # type: ignore
    except ImportError:
        raise YamlValidationError(f"{name}: pyyaml unavailable; fail-closed")
    try:
        loader = _yaml_loader()
        data = yaml.load(front, Loader=loader)
    except YamlDuplicateKeyError as e:
        raise YamlValidationError(f"{name}: {e}")
    except Exception as e:
        raise YamlValidationError(f"{name}: YAML not parseable: {e}")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise YamlValidationError(f"{name}: YAML front matter must be a mapping")
    return data


def _read(path: Path) -> str:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


# =============================================================================
# 工件读取辅助
# =============================================================================

def _frontmatter_dict(task_dir: Path, name: str) -> Optional[Dict[str, Any]]:
    """读取工件 front matter 为 dict；文件不存在返回 None，损坏抛 YamlValidationError。"""
    path = task_dir / name
    if not path.is_file():
        return None
    return parse_frontmatter_yaml(_read(path), name)


def _file_exists(task_dir: Path, name: str) -> bool:
    return (task_dir / name).is_file()


def _trusted_arch_pass(conn, task_id: str, *,
                       artifact_path=None, expected_subject_digest=None,
                       evidence_dir=None):
    """门禁统一入口：tp-software-architect 的 ARCHITECTURE PASS 可信事件。

    Final Hardening（INV-03）：不再信任 event_type/actor_role/summary 三元组，
    通过 event_policies.load_trusted_governance_event 完成 producer/schema/
    transaction_id/digest/evidence 全链校验；缺失返回 None。
    Third Hardening（P0-1/P0-2/P1-1）：可传入 artifact_path（校验事件
    artifact_digest == 当前评审文件）、expected_subject_digest（校验受评审内容
    绑定）与 review_kind=ARCHITECTURE。
    Fourth Hardening（P0-2）：可传入 evidence_dir 校验结构化证据链
    （path + sha256，任一删除/替换使 PASS 失效）。
    """
    return event_policies.load_trusted_governance_event(
        conn, task_id,
        event_type="REVIEW_COMPLETED",
        actor="tp-software-architect",
        decision="PASS",
        review_kind="ARCHITECTURE",
        artifact_path=artifact_path,
        expected_subject_digest=expected_subject_digest,
        evidence_dir=evidence_dir,
    )


def _has_arch_review_event(conn, task_id: str) -> bool:
    """是否存在受信架构评审 PASS（完整身份链，非三元组）。"""
    return _trusted_arch_pass(conn, task_id) is not None


def _design_digest(task_dir: Path) -> str:
    """当前设计 digest（受评审内容指纹）。

    Third Hardening（P0-2）：统一为 ``cli.digest.compute_architecture_subject_digest``
    （含 task/knowledge/clarifications/decisions/test-guide/acceptance），
    与 review record 使用同一算法；排除 architecture-review.md 与 implementation.md。
    """
    return compute_architecture_subject_digest(task_dir)


def _latest_arch_pass_digest(conn, task_id: str) -> Optional[str]:
    """最近一次受信架构评审 PASS 事件 detail 中的 subject/design digest。"""
    trusted = _trusted_arch_pass(conn, task_id)
    if trusted is None:
        return None
    detail = trusted.detail
    nested = detail.get("detail")
    if isinstance(nested, dict):
        digest = nested.get("subject_digest") or nested.get("design_digest")
    else:
        digest = None
    if not digest:
        digest = detail.get("subject_digest") or detail.get("design_digest")
    return digest or None


def _risk_levels(task) -> Tuple[str, str]:
    return str(task["risk_level"] or ""), str(task["flow_level"] or "")


def _effective_level(risk: str, flow: str) -> str:
    """取两者较高等级。"""
    order = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
    r = order.get(risk, 0)
    f = order.get(flow, 0)
    return risk if r >= f else flow


def _check_blocking_clarifications(task_dir: Path, issues: List[ValidationIssue]) -> None:
    data = _frontmatter_dict(task_dir, "requirement-clarifications.md")
    if data is None:
        return  # L1 起在工件存在性检查中处理
    blocking_open = data.get("blocking_open")
    if blocking_open is not None:
        # Final Hardening（P1-4）：强类型——非整数值（如字符串 "false"/"0"）视为非法，
        # 禁止把 "false" 当 0 放行。
        try:
            n = int(blocking_open)
        except (TypeError, ValueError):
            issues.append(ValidationIssue(
                code=BLOCKING_CLARIFICATION_INVALID,
                message=f"blocking_open must be an integer, got {blocking_open!r}",
                artifact="requirement-clarifications.md",
                field="blocking_open",
            ))
            return
        if n > 0:
            issues.append(ValidationIssue(
                code=BLOCKING_CLARIFICATION_OPEN,
                message="blocking clarifications must all be closed before proceeding",
                artifact="requirement-clarifications.md",
                field="blocking_open",
            ))


def _check_decisions(task_dir: Path, issues: List[ValidationIssue], require_decisions: bool) -> None:
    data = _frontmatter_dict(task_dir, "requirement-decisions.md")
    if data is None:
        # Decision records are conditional facts, not a quota.  If no business/technical
        # choice was actually required, an L2/L3 task must not fabricate one just to pass
        # a governance gate.  Blocking uncertainty is handled by clarifications instead.
        return
    unresolved = data.get("unresolved_blocking") or []
    if isinstance(unresolved, list) and unresolved:
        issues.append(ValidationIssue(
            code=DECISIONS_UNRESOLVED_BLOCKING,
            message=f"requirement-decisions has unresolved blocking entries: {len(unresolved)}",
            artifact="requirement-decisions.md",
            field="unresolved_blocking",
        ))
    # Final Hardening（P1-4）：强类型 decisions。
    # - 兼容 decision_id / id 两种字段（模板用 decision_id）；
    # - 仅当存在"已声明决策"（任一条目有 decision/selected_option 内容）时才强校验，
    #   模板占位（所有字段为空）视为“没有真实决策”；即使 L2/L3 也不要求
    #   为满足门禁而伪造 D-001。存在真实决策时仍执行完整结构/阻塞校验。
    decisions = data.get("decisions")
    if decisions is not None and not isinstance(decisions, list):
        issues.append(ValidationIssue(
            code=DECISIONS_INVALID,
            message=f"decisions must be a list, got {type(decisions).__name__}",
            artifact="requirement-decisions.md",
            field="decisions",
        ))
        return
    if isinstance(decisions, list):
        has_declared = any(
            isinstance(d, dict) and str(d.get("decision") or d.get("selected_option") or d.get("resolution") or "").strip()
            for d in decisions
        )
        if not has_declared:
            return
        seen: set = set()
        for idx, d in enumerate(decisions):
            if not isinstance(d, dict):
                issues.append(ValidationIssue(
                    code=DECISIONS_INVALID,
                    message=f"decisions[{idx}] must be a mapping",
                    artifact="requirement-decisions.md",
                    field="decisions",
                ))
                continue
            did = d.get("id") or d.get("decision_id") or ""
            if not str(did).strip():
                issues.append(ValidationIssue(
                    code=DECISIONS_INVALID,
                    message=f"decisions[{idx}] missing non-empty id",
                    artifact="requirement-decisions.md",
                    field="decisions",
                ))
            elif did in seen:
                issues.append(ValidationIssue(
                    code=DECISIONS_INVALID,
                    message=f"duplicate decision id: {did!r}",
                    artifact="requirement-decisions.md",
                    field="decisions",
                ))
            seen.add(did)
            content = d.get("decision") or d.get("selected_option") or d.get("resolution") or d.get("note") or ""
            if not str(content).strip():
                issues.append(ValidationIssue(
                    code=DECISIONS_INVALID,
                    message=f"decision entry {did or idx} is empty (no decision content)",
                    artifact="requirement-decisions.md",
                    field="decisions",
                ))
    # No declared decision is valid at every risk level.  Only malformed or unresolved
    # *actual* decisions are blockers.


def _l1_risk_signals(task_dir: Path) -> List[str]:
    """L1 真实风险触发（P1-3）：扫描 task.md 风险区，命中高风险信号要求架构评审。

    至少覆盖：权限、DDL、数据删除、跨模块、外部系统、并发、高风险用户确认、scope change。
    """
    path = task_dir / "task.md"
    if not path.is_file():
        return []
    try:
        text = _read(path)
    except OSError:
        return []
    m = re.search(r"##[^\n]*风险[^\n]*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    risk_section = m.group(1) if m else ""
    signals: List[str] = []
    for kw in ("权限", "DDL", "数据删除", "跨模块", "外部系统", "并发", "高风险用户确认", "scope change"):
        if re.search(re.escape(kw), risk_section, re.IGNORECASE):
            signals.append(kw)
    return signals


def _check_knowledge(task_dir: Path, issues: List[ValidationIssue], require_complete: bool) -> None:
    data = _frontmatter_dict(task_dir, "requirement-knowledge.md")
    if data is None:
        issues.append(ValidationIssue(
            code=REQUIREMENT_KNOWLEDGE_MISSING,
            message="requirement-knowledge.md is required for this risk level",
            artifact="requirement-knowledge.md",
        ))
        return
    complete = data.get("retrieval", {}).get("complete", False) if isinstance(data.get("retrieval"), dict) else data.get("retrieval_complete")
    if require_complete and not complete:
        issues.append(ValidationIssue(
            code=REQUIREMENT_KNOWLEDGE_INCOMPLETE,
            message="requirement-knowledge retrieval must be complete (or explicitly approved incomplete)",
            artifact="requirement-knowledge.md",
            field="retrieval.complete",
        ))


def _arch_review_event_row(conn, task_id: str):
    """最近一条架构评审 PASS 事件原始行（不受信校验，供差异诊断）。"""
    return conn.execute(
        "SELECT * FROM task_event WHERE task_id=? AND event_type='REVIEW_COMPLETED' "
        "AND actor_role='tp-software-architect' AND summary='PASS' ORDER BY id DESC LIMIT 1",
        (task_id,),
    ).fetchone()


def _check_architecture_review(task_dir: Path, conn, task_id: str, issues: List[ValidationIssue],
                               require_pass: bool) -> None:
    """L2/L3 DEVELOPING 前架构评审门禁（含 PASS 失效与可信事件链）。

    Third Hardening（P0-1/P0-2/P1-1）逐级诊断：
    1. artifact/事件缺失 → ARCHITECTURE_REVIEW_REQUIRED
    2. 事件受信链（producer/schema/transaction_id/decision）缺失 → TRUSTED_EVENT_SCHEMA_INVALID
    3. 事件 artifact_digest != 当前 architecture-review.md → ARCHITECTURE_REVIEW_ARTIFACT_MISMATCH
    4. 事件 subject_digest != 当前设计 digest → ARCHITECTURE_REVIEW_STALE
    5. 事件 review_kind != ARCHITECTURE → ARCHITECTURE_REVIEW_KIND_MISMATCH
    """
    if not require_pass:
        return
    data = _frontmatter_dict(task_dir, "architecture-review.md")
    row = _arch_review_event_row(conn, task_id)
    if data is None or row is None:
        issues.append(ValidationIssue(
            code=ARCHITECTURE_REVIEW_REQUIRED,
            message="L2/L3 requires a formal ARCHITECTURE REVIEW_COMPLETED PASS (event + artifact)",
            artifact="architecture-review.md",
        ))
        return
    decision = (data.get("review") or {}).get("decision", "DRAFT") if isinstance(data.get("review"), dict) else data.get("decision", "DRAFT")
    if str(decision).upper() != "PASS":
        issues.append(ValidationIssue(
            code=ARCHITECTURE_REVIEW_REQUIRED,
            message=f"architecture-review decision must be PASS, got {decision!r}",
            artifact="architecture-review.md",
            field="review.decision",
        ))
        return
    # 完整受信链：producer/schema/transaction_id + artifact digest + subject digest
    # + kind + 结构化 evidence（Fourth Hardening P0-2：证据删除/替换使 PASS 失效）
    current_subject = _design_digest(task_dir)
    trusted = _trusted_arch_pass(
        conn, task_id,
        artifact_path=task_dir / "architecture-review.md",
        expected_subject_digest=current_subject,
        evidence_dir=task_dir,
    )
    if trusted is not None:
        return
    # ---- 差异诊断（P0-1/P0-2/P1-1） ----
    detail = {}
    if row["detail_json"]:
        try:
            parsed = json.loads(row["detail_json"])
            detail = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            detail = {}
    producer = detail.get("producer") or detail.get("source_command") or ""
    tx_id = detail.get("transaction_id")
    kind_ok = str(detail.get("review_kind") or "").upper() == "ARCHITECTURE"
    declared_artifact = detail.get("artifact_digest") or ""
    import hashlib as _hl
    try:
        current_artifact = _hl.sha256((task_dir / "architecture-review.md").read_bytes()).hexdigest()
    except OSError:
        current_artifact = ""
    declared_subject = detail.get("subject_digest") or detail.get("design_digest") or ""
    if not producer or not tx_id:
        issues.append(ValidationIssue(
            code=event_policies.TRUSTED_EVENT_SCHEMA_INVALID,
            message="architecture review PASS event is untrusted: producer/transaction_id identity chain missing",
            artifact="architecture-review.md",
            field="transaction_id",
        ))
    elif not declared_artifact or declared_artifact != current_artifact:
        issues.append(ValidationIssue(
            code=event_policies.ARCHITECTURE_REVIEW_ARTIFACT_MISMATCH,
            message="architecture review PASS is not bound to the current review artifact digest",
            artifact="architecture-review.md",
            field="artifact_digest",
        ))
    elif not declared_subject or declared_subject != current_subject:
        issues.append(ValidationIssue(
            code=ARCHITECTURE_REVIEW_STALE,
            message="architecture review PASS is stale: design artifacts changed after the PASS event",
            artifact="architecture-review.md",
            field="design_digest",
        ))
    elif not kind_ok:
        issues.append(ValidationIssue(
            code=event_policies.ARCHITECTURE_REVIEW_KIND_MISMATCH,
            message="architecture review PASS event review_kind is not ARCHITECTURE",
            artifact="architecture-review.md",
            field="review_kind",
        ))
    else:
        issues.append(ValidationIssue(
            code=event_policies.TRUSTED_EVENT_SCHEMA_INVALID,
            message="architecture review PASS event is untrusted: schema validation failed",
            artifact="architecture-review.md",
        ))


def _check_test_guide(task_dir: Path, issues: List[ValidationIssue],
                      require_skeleton: bool = False, require_development: bool = False,
                      require_verification: bool = False, to_state: str = "") -> None:
    """Validate the tester-facing guide without making it a duplicate workflow ledger.

    Real-task pressure testing showed that lifecycle flags, section ownership, AC coverage
    and verification-result duplication caused roles to spend substantial effort keeping
    governance metadata synchronized.  The authoritative lifecycle already lives in
    SQLite/task_event, while acceptance.md + codex-review.md carry verification outcomes.

    Therefore the guide is now a *human execution aid*: for L2/L3 transitions its presence
    and parseable front matter are sufficient.  Runtime-owned lifecycle metadata is updated
    atomically on successful transitions by ``_runtime_test_guide_update`` and is never a
    role-entered gate.
    """
    data = _frontmatter_dict(task_dir, "requirement-test-guide.md")
    if data is None:
        issues.append(ValidationIssue(
            code=TEST_GUIDE_INCOMPLETE,
            message="requirement-test-guide.md is required for this transition",
            artifact="requirement-test-guide.md",
        ))
        return


def _runtime_test_guide_update(task_dir: Path, to_state: str, owner: str) -> Optional[str]:
    """Return a test-guide text with runtime-managed lifecycle metadata advanced.

    This is intentionally best-effort and metadata-only.  Roles own tester-facing prose;
    the Runtime owns lifecycle/current_owner so no role has to edit bookkeeping fields.
    The returned text is committed in the same durable transaction as the state change.
    """
    path = task_dir / "requirement-test-guide.md"
    if not path.is_file():
        return None
    try:
        text = _read(path)
    except OSError:
        return None
    field_by_state = {
        "DEVELOPING": "architecture_outline",
        "VERIFYING": "development_details",
        "CLOSING": "verification_results",
        "COMPLETED": "delivery_finalized",
    }
    field = field_by_state.get(to_state)
    if field:
        text = re.sub(
            rf"(?m)^(\s{{2}}{re.escape(field)}:\s*)(pending|draft|in_progress|done|completed|complete)\s*$",
            rf"\1done",
            text,
            count=1,
        )
    if owner:
        text = re.sub(r"(?m)^current_owner:\s*.*$", f"current_owner: {owner}", text, count=1)
    return text



def _check_acceptance(task_dir: Path, issues: List[ValidationIssue], enforce_no_pending: bool,
                      enforce_yaml: bool, conn=None, task_id: str = "", allow_human_pending: bool = False) -> None:
    """acceptance 门禁：YAML 真实解析 + 无非法 PENDING/BLOCKED + deferred 结构合法。

    Third Hardening（P0-3/P0-4）：
    - 零 AC 行且无机器可读 no_acceptance_required → ACCEPTANCE_CRITERIA_MISSING；
    - no_acceptance_required 使用机器可读声明，不依赖人员审批收据；
    - verdict=PASS 的 AC 证据路径经 validate_evidence_path 真实校验（文件存在/不越界）。

    委托 cli/yaml_checks.check_acceptance_yaml（与 PowerShell validator 语义一致）。
    """
    from . import yaml_checks
    from .yaml_checks import normalize_verdict
    from .evidence import validate_evidence_path
    path = task_dir / "acceptance.md"
    if not path.is_file():
        issues.append(ValidationIssue(
            code=ACCEPTANCE_PENDING,
            message="acceptance.md is missing",
            artifact="acceptance.md",
        ))
        return
    try:
        text = _read(path)
    except OSError as e:
        issues.append(ValidationIssue(code=YAML_INVALID, message=f"cannot read acceptance.md: {e}", artifact="acceptance.md"))
        return
    result = yaml_checks.check_acceptance_yaml(text, enforce_completion=enforce_no_pending, allow_human_pending=allow_human_pending)
    if not result.ok:
        for msg in result.issues:
            code = ACCEPTANCE_PENDING
            if "invalid verdict" in msg or "empty acceptance condition" in msg \
                    or "non-empty acceptance condition" in msg or "PASS requires non-empty evidence" in msg:
                code = ACCEPTANCE_INVALID
            elif "no acceptance criteria" in msg:
                code = ACCEPTANCE_CRITERIA_MISSING
            elif "deferred_acceptance" in msg:
                code = DEFERRED_ACCEPTANCE_INVALID
            elif "human_witness" in msg:
                code = USER_CONFIRMATION_REQUIRED
            elif "YAML" in msg:
                code = YAML_INVALID
            issues.append(ValidationIssue(code=code, message=msg, artifact="acceptance.md"))
    if enforce_no_pending and result.pending_rows:
        issues.append(ValidationIssue(
            code=ACCEPTANCE_PENDING,
            message="acceptance has PENDING/BLOCKED entries: " + ", ".join(result.pending_rows[:5]),
            artifact="acceptance.md",
        ))
    # OWNER_WAIVED / DEFERRED_ACCEPTED are valid only when backed by a trusted
    # human_owner ledger decision. This prevents an AI role from self-authoring an override.
    if enforce_no_pending and conn is not None and task_id:
        from . import event_policies
        trusted = event_policies.load_owner_acceptance_decisions(conn, task_id)
        trusted_pairs = set()
        for item in trusted:
            mode = str(item.get("mode") or "").lower()
            for ac in item.get("acs") or []:
                trusted_pairs.add((str(ac), mode))
        for entry in result.deferred_entries:
            ac = str(entry.get("ac") or "")
            if ac and (ac, "defer") not in trusted_pairs:
                issues.append(ValidationIssue(
                    code=DEFERRED_ACCEPTANCE_INVALID,
                    message=f"DEFERRED_ACCEPTED {ac} requires a trusted human_owner OWNER_ACCEPTANCE_DECISION(defer) event",
                    artifact="acceptance.md",
                    field="deferred_acceptance",
                ))
        for entry in result.owner_waiver_entries:
            ac = str(entry.get("ac") or "")
            if ac and (ac, "waive") not in trusted_pairs:
                issues.append(ValidationIssue(
                    code=USER_CONFIRMATION_REQUIRED,
                    message=f"OWNER_WAIVED {ac} requires a trusted human_owner OWNER_ACCEPTANCE_DECISION(waive) event",
                    artifact="acceptance.md",
                    field="owner_waivers",
                ))
    # ---- Third Hardening（P0-4）：PASS 行的证据路径真实校验 ----
    for line in text.splitlines():
        m = re.match(r"^\s*\|\s*(AC-[^|\s]+)\s*\|", line)
        if not m:
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) <= 8:
            continue
        verdict = normalize_verdict(cells[8])
        if verdict != "PASS":
            continue
        ev = cells[6]
        if not ev:
            continue
        check = validate_evidence_path(task_dir, ev)
        if not check.ok:
            issues.append(ValidationIssue(
                code=ACCEPTANCE_INVALID,
                message=f"acceptance AC {m.group(1)} PASS evidence invalid: {check.error}",
                artifact="acceptance.md",
                field="evidence",
            ))


def _check_codex_review_body(task_dir: Path, issues: List[ValidationIssue]) -> None:
    """codex-review 正文实质（Task 4 §6.3 / P0-3 根因二）：关键词占位不可通过。

    要求：
    - 正文包含结论/证据/残余风险且结论段有实质内容（非空/非占位）；
    - front matter review.decision 必须存在且合法；
    - PASS 必须带 evidence，且正文无 pending/blocked 冲突。
    """
    path = task_dir / "codex-review.md"
    if not path.is_file():
        issues.append(ValidationIssue(code=CODE_REVIEW_EMPTY, message="codex-review.md missing", artifact="codex-review.md"))
        return
    try:
        text = _read(path)
    except OSError as e:
        issues.append(ValidationIssue(code=CODE_REVIEW_EMPTY, message=f"cannot read codex-review.md: {e}", artifact="codex-review.md"))
        return
    # 剥离 front matter 后检查正文
    parts = frontmatter.split(text)
    body = parts[1] if parts else text
    if not body or len(body.strip()) < 200:
        issues.append(ValidationIssue(
            code=CODE_REVIEW_EMPTY,
            message="codex-review body is empty or template placeholder",
            artifact="codex-review.md",
        ))
    checks = {
        "结论": ("审查结论", "结论"),
        "证据": ("证据",),
        "残余风险": ("残余风险",),
    }
    for label, keys in checks.items():
        if not any(k in body for k in keys):
            issues.append(ValidationIssue(
                code=CODE_REVIEW_EMPTY,
                message=f"codex-review body must contain {label} section",
                artifact="codex-review.md",
            ))
    # §6.3：结论段实质内容（非占位符）
    conclusion = re.search(r"## 结论\n(.*?)(?=\n## |\Z)", body, re.DOTALL)
    if conclusion:
        ctext = conclusion.group(1)
        if not ctext.strip() or re.search(r"[:：]\s*$", ctext):
            issues.append(ValidationIssue(
                code=CODE_REVIEW_EMPTY,
                message="codex-review conclusion section must contain substantive content",
                artifact="codex-review.md",
            ))
    # front matter decision/evidence 与正文一致性
    if parts:
        try:
            data = parse_frontmatter_yaml(text, "codex-review.md")
            review = data.get("review") if isinstance(data.get("review"), dict) else {}
            decision = review.get("decision", "")
            if not decision:
                issues.append(ValidationIssue(
                    code=CODE_REVIEW_EMPTY,
                    message="codex-review front matter review.decision is required",
                    artifact="codex-review.md",
                ))
            elif str(decision).upper() not in ("PASS", "FAIL", "NEEDS_FIX", "PENDING", "DRAFT"):
                issues.append(ValidationIssue(
                    code=CODE_REVIEW_EMPTY,
                    message=f"codex-review invalid decision {decision!r}",
                    artifact="codex-review.md",
                    field="review.decision",
                ))
            elif str(decision).upper() != "PASS":
                issues.append(ValidationIssue(
                    code=CODE_REVIEW_EMPTY,
                    message=f"closing requires codex-review decision PASS (got {decision!r})",
                    artifact="codex-review.md",
                    field="review.decision",
                ))
            if str(decision).upper() == "PASS":
                from .evidence import validate_evidence_path
                evidence_fm = review.get("evidence", "")
                if not evidence_fm:
                    issues.append(ValidationIssue(
                        code=CODE_REVIEW_EMPTY,
                        message="codex-review PASS requires non-empty evidence in front matter",
                        artifact="codex-review.md",
                        field="review.evidence",
                    ))
                elif str(evidence_fm).strip().lower() == "none":
                    # Fourth Hardening（P0-3/P1-2）：PASS 不允许 evidence=none
                    issues.append(ValidationIssue(
                        code=CODE_REVIEW_EMPTY,
                        message="codex-review PASS evidence 'none' is rejected in V5.2.4; requires a real local_file",
                        artifact="codex-review.md",
                        field="review.evidence",
                    ))
                else:
                    ev_check = validate_evidence_path(task_dir, evidence_fm)
                    if not ev_check.ok:
                        issues.append(ValidationIssue(
                            code=CODE_REVIEW_EMPTY,
                            message=f"codex-review PASS evidence invalid: {ev_check.error}",
                            artifact="codex-review.md",
                            field="review.evidence",
                        ))
                conflict = re.search(r"(?i)\b(pending|blocked|未验证|not verified)\b", body)
                if conflict:
                    issues.append(ValidationIssue(
                        code=CODE_REVIEW_EMPTY,
                        message=f"codex-review PASS conflicts with body containing {conflict.group(0)!r}",
                        artifact="codex-review.md",
                    ))
        except YamlValidationError as e:
            issues.append(ValidationIssue(code=YAML_INVALID, message=str(e), artifact="codex-review.md"))


def _collect_scope_ids(task_dir: Path, name: str) -> Optional[set]:
    """收集单个工件的 scope_changes id 集合；工件缺失或未声明返回 None。

    Final Hardening（§6.6）：task.md 声明 scope_changes 时，其余工件若显式声明
    scope_changes（front matter 或正文 YAML 块）必须与 task 一致。
    """
    from . import yaml_checks
    path = task_dir / name
    if not path.is_file():
        return None
    ids: set = set()
    try:
        data = _frontmatter_dict(task_dir, name)
        if data is not None and data.get("scope_changes") is not None:
            changes = data.get("scope_changes") or []
            ids |= {str(c.get("id")) for c in changes if isinstance(c, dict) and c.get("id")}
    except YamlValidationError:
        pass
    try:
        text = _read(path)
    except OSError:
        return ids if ids else None
    for block in re.findall(r"```yaml\s*\n(.*?)```", text, re.DOTALL):
        try:
            data = yaml_checks.parse_yaml_fail_closed(block, name)
        except yaml_checks.YamlValidationError:
            continue
        changes = data.get("scope_changes")
        if changes is None:
            continue
        ids |= {str(c.get("id")) for c in changes if isinstance(c, dict) and c.get("id")}
    return ids if ids else None


def _check_scope_change(task_dir: Path, issues: List[ValidationIssue]) -> None:
    """scope change 全链一致性（§6.6/P1-6）：task 声明 scope_changes 时，其余工件
    （decisions/architecture review/implementation/acceptance/test-guide/codex-review/
    handoff/receipt）若显式声明 scope_changes 必须与 task 的 id 集合一致。"""
    task_data = _frontmatter_dict(task_dir, "task.md")
    if task_data is None:
        return
    task_changes = task_data.get("scope_changes") or []
    task_ids = {c.get("id") if isinstance(c, dict) else str(c) for c in task_changes if isinstance(c, dict) and c.get("id")}
    if not task_ids:
        return
    artifacts = (
        "requirement-decisions.md",
        "architecture-review.md",
        "implementation.md",
        "acceptance.md",
        "requirement-test-guide.md",
        "codex-review.md",
    )
    for name in artifacts:
        other_ids = _collect_scope_ids(task_dir, name)
        if other_ids is None:
            continue
        if other_ids != task_ids:
            issues.append(ValidationIssue(
                code=SCOPE_CHANGE_DRIFT,
                message=f"scope changes drift: task.md {sorted(task_ids)} vs {name} {sorted(other_ids)}",
                artifact=name,
            ))




def _check_text_integrity(task_dir: Path, issues: List[ValidationIssue], *, include_quality: bool = False) -> None:
    """Reject only obvious delivery-artifact corruption at closure boundaries.

    This is intentionally not a prose-quality gate. It detects high-confidence encoding
    damage (mojibake/U+FFFD/NUL) and repeated literal PowerShell newline escapes that
    leaked into Markdown outside fenced code blocks.
    """
    from .encoding_guard import detect_mojibake

    names = [
        "task.md", "requirement-knowledge.md", "requirement-clarifications.md",
        "requirement-decisions.md", "architecture-review.md", "requirement-test-guide.md",
        "implementation.md", "acceptance.md", "codex-review.md",
    ]
    if include_quality:
        names.append("quality-and-knowledge.md")
    for name in names:
        path = task_dir / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            issues.append(ValidationIssue(
                code=TEXT_INTEGRITY_INVALID,
                message=f"{name} is not valid readable UTF-8: {exc}",
                artifact=name,
            ))
            continue
        hits = detect_mojibake(text)
        if "\x00" in text:
            hits.append("NUL byte/character")
        # Fenced code may legitimately document PowerShell escape sequences.
        prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        # Detect the characteristic leaked PowerShell CRLF token.  Do not match
        # lone `` `r``/`` `n`` prefixes because normal Markdown inline code such
        # as `requirement-...` would be a false positive.
        escape_hits = len(re.findall(r"`r`n", prose))
        if escape_hits >= 2:
            hits.append(f"literal PowerShell newline escapes outside code fences ({escape_hits})")
        if hits:
            issues.append(ValidationIssue(
                code=TEXT_INTEGRITY_INVALID,
                message=f"{name} has high-confidence text corruption: {'; '.join(hits[:4])}",
                artifact=name,
            ))



def _check_trusted_verification_pass(task_dir: Path, conn, task_id: str, issues: List[ValidationIssue]) -> None:
    """Require the canonical verification PASS at every CLOSING-capable entry point."""
    from . import event_policies
    from .digest import compute_verification_subject_digest
    review_path = task_dir / "codex-review.md"
    if not review_path.is_file():
        return  # body checker emits the concrete missing-artifact issue
    trusted = event_policies.load_trusted_governance_event(
        conn, task_id,
        event_type="REVIEW_COMPLETED",
        actor="tp-test-engineer",
        decision="PASS",
        review_kind="VERIFICATION",
        artifact_path=review_path,
        expected_subject_digest=compute_verification_subject_digest(task_dir),
        evidence_dir=task_dir,
    )
    if trusted is None:
        issues.append(ValidationIssue(
            code="TRUSTED_VERIFICATION_PASS_MISSING",
            message="CLOSING requires a trusted tp-test-engineer REVIEW_COMPLETED PASS bound to the current codex-review, subject digest and evidence",
            artifact="codex-review.md",
        ))


def _check_completed_gates(task_dir: Path, conn, task_id: str, issues: List[ValidationIssue]) -> None:
    """COMPLETED 前：无 PENDING/BLOCKED/journal/drift，自动质量门禁通过。"""
    _check_acceptance(task_dir, issues, enforce_no_pending=True, enforce_yaml=True, conn=conn, task_id=task_id)
    _check_codex_review_body(task_dir, issues)
    _check_trusted_verification_pass(task_dir, conn, task_id, issues)
    _check_test_guide(task_dir, issues, require_verification=True, to_state="COMPLETED")
    _check_scope_change(task_dir, issues)
    _check_text_integrity(task_dir, issues, include_quality=True)
    # 无未完成 transaction journal
    for j in transaction_journal.list_journals(task_dir):
        if j.get("phase") != "COMPLETED":
            issues.append(ValidationIssue(
                code=BASELINE_BLOCKED_ACTIVE,
                message=f"unfinished transaction journal present: {j.get('transaction_id')}",
            ))
            break


def _check_closing_gates(task_dir: Path, conn, task_id: str, issues: List[ValidationIssue]) -> None:
    _check_acceptance(task_dir, issues, enforce_no_pending=True, enforce_yaml=True, conn=conn, task_id=task_id)
    _check_codex_review_body(task_dir, issues)
    _check_trusted_verification_pass(task_dir, conn, task_id, issues)
    _check_test_guide(task_dir, issues, require_verification=True, to_state="CLOSING")
    _check_scope_change(task_dir, issues)
    _check_text_integrity(task_dir, issues, include_quality=False)


# =============================================================================
# validate_transition（阶段 preflight 主入口）
# =============================================================================
