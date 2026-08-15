# -*- coding: utf-8 -*-
"""V5.2.2 legacy transition compatibility / recovery service.

The active Record-first daily API is implemented by :mod:`cli.record_first` and uses
the five public states from ``governance/workflow.yaml``.  This module intentionally
retains the older long-state transition validator/writer so frozen historical
contracts, legacy ``tp-spec commit`` flows and explicit admin-recovery paths can be
interpreted or repaired without duplicating durable-journal logic.

It is therefore *not* the normal V5.2.2 role-flow permission engine.  Code that needs
ordinary task progress should use ``task checkpoint/block/resume/verify/complete``.

Within the compatibility/recovery surface, ``validate_transition()`` is read-only and
``transition_task()`` is the canonical long-state writer: it validates legacy gates,
writes STATE/HANDOFF evidence under one transaction id, uses the durable journal and
atomically rebuilds projections.  Failures remain fail-closed.
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
from . import transaction_journal
from .digest import compute_architecture_subject_digest
from .version import active_version
from .workflow_loader import load_workflow

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
# 转换规则矩阵（Final Hardening Task 2：机器可读单一来源）
# =============================================================================
# key: (from_state, to_state) -> 规则：
#   allowed_actors: tuple[str]          合法执行者（空 = 不额外限制，仅 owner 校验）
#   required_trusted_events: tuple[str] 需要的受信治理事件（"EVENT_TYPE:ACTOR:DECISION"；
#                                       validate_transition 已独立校验，此处为审计声明）
# 权威来源：governance/workflow.yaml（states/transitions/levels）+ agents/role-catalog.yaml
# （state_owner_map / completion_chain）。本矩阵补充 actor 与可信事件语义，
# 与 commit / admin recovery / review record 共用；禁止各模块再维护独立 actor 白名单。
TRANSITION_RULES = {
    # ---- 进入开发（架构评审后）----
    ("NEW", "DEVELOPING"): {"allowed_actors": ("tp-architecture-design",),
                            "required_trusted_events": ("REVIEW_COMPLETED:tp-architecture-review:PASS",)},
    ("RISK_ANALYZING", "DEVELOPING"): {"allowed_actors": ("tp-architecture-design",),
                                       "required_trusted_events": ("REVIEW_COMPLETED:tp-architecture-review:PASS",)},
    ("REQUIREMENT_CLARIFYING", "DEVELOPING"): {"allowed_actors": ("tp-architecture-design",),
                                               "required_trusted_events": ("REVIEW_COMPLETED:tp-architecture-review:PASS",)},
    ("TECH_DESIGNING", "DEVELOPING"): {"allowed_actors": ("tp-architecture-design",),
                                       "required_trusted_events": ("REVIEW_COMPLETED:tp-architecture-review:PASS",)},
    ("TECHNICAL_DISCOVERY", "DEVELOPING"): {"allowed_actors": ("tp-architecture-design",),
                                            "required_trusted_events": ("REVIEW_COMPLETED:tp-architecture-review:PASS",)},
    ("DISCOVERY_REVIEW_REQUIRED", "DEVELOPING"): {"allowed_actors": ("tp-architecture-design",),
                                                  "required_trusted_events": ("REVIEW_COMPLETED:tp-architecture-review:PASS",)},
    ("BLOCKED", "DEVELOPING"): {"allowed_actors": ("tp-architecture-design",),
                                "required_trusted_events": ("REVIEW_COMPLETED:tp-architecture-review:PASS",)},
    # ---- 进入验证 ----
    ("DEVELOPING", "VERIFYING"): {"allowed_actors": ("tp-development-engineering",),
                                  "required_trusted_events": ()},
    ("ASSISTING", "VERIFYING"): {"allowed_actors": ("tp-development-engineering",),
                                 "required_trusted_events": ()},
    ("DEVELOPING", "ASSISTING"): {"allowed_actors": ("tp-development-engineering",),
                                  "required_trusted_events": ()},
    # ---- 验收失败返回开发（不绕架构角色）----
    ("VERIFYING", "DEVELOPING"): {"allowed_actors": ("tp-verification-engineering",),
                                     "required_trusted_events": ()},
    # ---- 进入结单（自动质量门禁）----
    ("VERIFYING", "CLOSING"): {"allowed_actors": ("tp-delivery-convergence",),
                               "required_trusted_events": ("REVIEW_COMPLETED:tp-verification-engineering:PASS",)},
    ("BROWSER_VERIFYING", "CLOSING"): {"allowed_actors": ("tp-delivery-convergence",),
                                       "required_trusted_events": ("REVIEW_COMPLETED:tp-verification-engineering:PASS",)},
    ("REVIEWING", "CLOSING"): {"allowed_actors": ("tp-delivery-convergence",),
                               "required_trusted_events": ("REVIEW_COMPLETED:tp-verification-engineering:PASS",)},
    # ---- 完成（仅从 CLOSING）----
    ("CLOSING", "COMPLETED"): {"allowed_actors": ("tp-delivery-convergence",),
                               "required_trusted_events": ()},
    # ---- 返回开发（评审驳回/验收失败后修订）----
    ("REVIEWING", "DEVELOPING"): {"allowed_actors": ("tp-verification-engineering",),
                                  "required_trusted_events": ()},
}


def transition_rule(from_state: str, to_state: str) -> Optional[Dict[str, Any]]:
    """读取转换规则；未登记的转换返回 None（仅 owner 校验，不额外限制 actor）。"""
    return TRANSITION_RULES.get((from_state, to_state))


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
    """门禁统一入口：tp-architecture-review 的 ARCHITECTURE PASS 可信事件。

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
        actor="tp-architecture-review",
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
        "AND actor_role='tp-architecture-review' AND summary='PASS' ORDER BY id DESC LIMIT 1",
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
                        message="codex-review PASS evidence 'none' is rejected in V5.2.2; requires a real local_file",
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
        actor="tp-verification-engineering",
        decision="PASS",
        review_kind="VERIFICATION",
        artifact_path=review_path,
        expected_subject_digest=compute_verification_subject_digest(task_dir),
        evidence_dir=task_dir,
    )
    if trusted is None:
        issues.append(ValidationIssue(
            code="TRUSTED_VERIFICATION_PASS_MISSING",
            message="CLOSING requires a trusted tp-verification-engineering REVIEW_COMPLETED PASS bound to the current codex-review, subject digest and evidence",
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

def validate_transition(
    *,
    task_id: str,
    task_dir: Path,
    from_state: str,
    to_state: str,
    actor: str,
    conn,
) -> ValidationResult:
    """阶段 preflight 真实实现。只读，零副作用。

    按任务书 §6（L0~L3 门禁）与 §7（架构评审）逐状态执行：
    - L0：默认不强制需求/架构，但接受 acceptance 结单门禁；
    - L1：requirement-knowledge/decisions/clarifications 门禁 + 风险触发时架构 PASS；
    - L2/L3：DEVELOPING 前架构 PASS + test guide 骨架；VERIFYING 前 test guide 开发部分；
    - CLOSING：acceptance/review 正文/test guide/scope change 一致；
    - COMPLETED：无 PENDING/BLOCKED/journal/drift。
    """
    issues: List[ValidationIssue] = []
    task_dir = Path(task_dir)
    task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
    if task is None:
        issues.append(ValidationIssue(code="TASK_NOT_FOUND", message=f"task not found: {task_id}"))
        return ValidationResult(ok=False, issues=issues)
    risk, flow = _risk_levels(task)
    level = _effective_level(risk, flow)
    is_l23 = level in ("L2", "L3")
    is_l1 = level == "L1"

    # 只校验当前目标状态真正依赖的正式工件。
    # 旧实现会把所有未来阶段工件都解析一遍，导致与本次交接无关的模板/草稿损坏
    # 也能阻断当前角色；真实任务压测证明这会制造纯治理返工。
    relevant_artifact = {
        "DEVELOPING": "task.md",
        "VERIFYING": "implementation.md",
        "CLOSING": "codex-review.md",
        "COMPLETED": "quality-and-knowledge.md",
    }.get(to_state)
    if relevant_artifact and (task_dir / relevant_artifact).is_file():
        try:
            parse_frontmatter_yaml(_read(task_dir / relevant_artifact), relevant_artifact)
        except YamlValidationError as e:
            issues.append(ValidationIssue(code=YAML_INVALID, message=str(e), artifact=relevant_artifact))

    # ---- 首次/上游进入 DEVELOPING ----
    # VERIFYING -> DEVELOPING 是已跨过开发入口后的实现返工，不得重新追溯执行
    # 需求/架构入口门禁；它由下方可信 FAIL 专用门禁约束。
    if to_state == "DEVELOPING" and from_state != "VERIFYING":
        if is_l23:
            _check_knowledge(task_dir, issues, require_complete=True)
            _check_blocking_clarifications(task_dir, issues)
            _check_decisions(task_dir, issues, require_decisions=True)
            _check_architecture_review(task_dir, conn, task_id, issues, require_pass=True)
            _check_test_guide(task_dir, issues, require_skeleton=True, to_state="DEVELOPING")
        elif is_l1:
            _check_knowledge(task_dir, issues, require_complete=False)
            _check_blocking_clarifications(task_dir, issues)
            _check_decisions(task_dir, issues, require_decisions=False)
            # Final Hardening（P1-3）：真实风险触发——task.md 风险区命中
            # 权限/DDL/数据删除/跨模块/外部系统/并发/高风险用户确认/scope change 时要求架构评审 PASS。
            if _l1_risk_signals(task_dir):
                _check_architecture_review(task_dir, conn, task_id, issues, require_pass=True)

    # ---- VERIFYING 普通实现缺陷直接退回 DEVELOPING ----
    # 必须先有一个绑定当前 codex-review/受评审内容的 FAIL。
    # NEEDS_FIX 属 VERIFYING 内 LOCAL_REWORK，不触发状态回退；只有较大实现问题才正式回 DEVELOPING。
    if from_state == "VERIFYING" and to_state == "DEVELOPING":
        from .digest import compute_verification_subject_digest
        from . import event_policies
        review_path = task_dir / "codex-review.md"
        trusted = None
        if review_path.is_file():
            for decision in ("FAIL",):
                trusted = event_policies.load_trusted_governance_event(
                    conn, task_id, event_type="REVIEW_COMPLETED",
                    actor="tp-verification-engineering", decision=decision,
                    review_kind="VERIFICATION", artifact_path=review_path,
                    expected_subject_digest=compute_verification_subject_digest(task_dir),
                )
                if trusted is not None:
                    break
        if trusted is None:
            issues.append(ValidationIssue(
                code=VERIFICATION_REWORK_REVIEW_REQUIRED,
                message="VERIFYING -> DEVELOPING requires a trusted verification FAIL bound to the current review subject",
                artifact="codex-review.md",
            ))

    # ---- 进入 VERIFYING ----
    if to_state == "VERIFYING":
        if is_l23:
            _check_test_guide(task_dir, issues, require_development=True, to_state="VERIFYING")
        if not (task_dir / "implementation.md").is_file():
            issues.append(ValidationIssue(
                code=IMPLEMENTATION_INCOMPLETE,
                message="implementation.md must exist before VERIFYING",
                artifact="implementation.md",
            ))

    # ---- 进入 CLOSING ----
    if to_state == "CLOSING":
        _check_closing_gates(task_dir, conn, task_id, issues)

    # ---- 进入 COMPLETED ----
    if to_state == "COMPLETED":
        _check_completed_gates(task_dir, conn, task_id, issues)

    return ValidationResult(ok=not issues, issues=issues)


# =============================================================================
# transition_task（唯一权威状态写入服务）
# =============================================================================

@dataclass
class TransitionResult:
    ok: bool
    message: str = ""
    flush_id: str = ""
    issues: List[ValidationIssue] = field(default_factory=list)


def transition_task(
    *,
    task_id: str,
    task_dir: Path,
    to_state: str,
    actor: str,
    summary: str,
    evidence: Optional[List[str]] = None,
    source_command: str = "commit",
    conn=None,
    db_path: Optional[str] = None,
    extra_detail: Optional[Dict[str, Any]] = None,
    extra_events: Optional[List[Dict[str, Any]]] = None,
    frontmatter_updates: Optional[Dict[str, Dict[str, Any]]] = None,
    handoff_args=None,
    on_projection_warnings=None,
    extra_texts: Optional[Dict[str, str]] = None,
) -> TransitionResult:
    """唯一权威状态写入服务（Final Hardening Task 2：normal commit / admin recovery /
    合法状态操作共用唯一实现）。

    流程：读任务/风险 → validate_transition（真实阶段门禁）→ canonical owner/actor
    校验 → 生成 STATE/HANDOFF 事件（同一 transaction_id）→ durable journal →
    SQLite 单事务 → 原子刷新投影。任一步失败零副作用（DB 未动、无事件）。

    扩展参数（供普通 commit 收敛使用，避免复制状态写入逻辑）：
    - ``extra_events``：附加治理事件（PHASE_EXIT/DECISION/REVIEW_COMPLETED），
      在 STATE/HANDOFF 之前以同一 transaction_id 写入；
    - ``frontmatter_updates``：{rel_path: front_matter_values}，与投影一起原子替换；
    - ``handoff_args``：真实 commit args（保留 changes/risks/actions/constraints），
      缺省时用本函数构造的轻量 args；
    - ``on_projection_warnings``：投影渲染告警回调；
    - ``extra_texts``：额外原子替换文本文件（{rel_path: text}），与投影一起在同一
      durable transaction 提交（用于 admin recovery 在同一事务写正式 receipt 文件）。

    说明：本实现聚焦门禁与事件/投影编排；实际持久化（journal+事务+投影替换）
    复用 cli/commit_cmd 的 _commit_with_recovery 以保证与现有 commit 路径一致。
    """
    from .commit_cmd import (_commit_with_recovery, _current_view_rel, _finalize_texts,
                            _frontmatter_text, _rebuild_current_view_text, _handoff_record)

    task_dir = Path(task_dir)
    # Final Hardening（P1-2）：显式区分外部传入 conn 与自建 conn；只有自建 conn
    # 才由本函数关闭，避免关闭调用方连接。
    owned_conn = False
    if conn is None:
        if not db_path:
            raise ValueError("transition_task requires conn or db_path")
        conn = dbmod.connect(db_path)
        owned_conn = True
    try:
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            return TransitionResult(ok=False, message=f"task not found: {task_id}")
        current = task["current_state"]
        wf = load_workflow()
        if not wf.is_valid_transition(current, to_state):
            return TransitionResult(ok=False, message=f"invalid transition {current} -> {to_state}")
        # 1. 阶段门禁（先于一切写入）
        result = validate_transition(
            task_id=task_id, task_dir=task_dir, from_state=current,
            to_state=to_state, actor=actor, conn=conn,
        )
        if not result.ok:
            codes = ", ".join(i.code for i in result.issues)
            return TransitionResult(ok=False, message=f"transition preflight failed: {codes}", issues=result.issues)
        # 2. canonical owner
        if to_state == "COMPLETED":
            owner = wf.get_completion_owner(task["risk_level"], task["flow_level"]) or "tp-delivery-convergence"
        else:
            owner = wf.get_state_owner(to_state) or ""
        if not owner:
            return TransitionResult(ok=False, message=f"no canonical owner for target state {to_state}")

        # Runtime-owned bookkeeping is advanced atomically with the state change.
        # Roles no longer edit lifecycle/current_owner in requirement-test-guide.md.
        runtime_guide = _runtime_test_guide_update(task_dir, to_state, owner)
        if runtime_guide is not None:
            merged_extra = dict(extra_texts or {})
            merged_extra["requirement-test-guide.md"] = runtime_guide
            extra_texts = merged_extra

        # 3. 转换规则（Task 2：TRANSITION_RULES 单一来源 actor/approval；owner 见步骤 2）
        rule = transition_rule(current, to_state)
        if rule and rule.get("allowed_actors") and actor not in rule["allowed_actors"]:
            return TransitionResult(
                ok=False,
                message=f"actor {actor!r} not allowed for transition {current} -> {to_state}"
                        f" (allowed: {', '.join(rule['allowed_actors'])})",
            )
        if to_state == "COMPLETED":
            if current != "CLOSING":
                return TransitionResult(ok=False, message="completion must be committed from CLOSING")

        # 5. 生成事件 + 投影（复用 commit 的事务机制）
        import uuid
        flush_id = f"FLUSH-{uuid.uuid4().hex}"
        timestamp = dbmod.now_iso()
        detail = dict(extra_detail or {})
        detail.update({
            "flush_id": flush_id,
            "summary": summary,
            "evidence": evidence or [],
            "source_command": source_command,
        })

        # 构造 args 兼容对象供 _handoff_record 使用（普通 commit 传入真实 handoff_args，
        # 保留 changes/risks/actions/constraints；其余入口用轻量默认值）
        from types import SimpleNamespace
        args = handoff_args if handoff_args is not None else SimpleNamespace(
            task=task_id, actor=actor, summary=summary,
            change=[], risk=[], evidence=evidence or [], action=[], constraint=[],
            to=to_state,
        )
        handoff_record = _handoff_record(task_dir, args, flush_id, owner)
        view_rel = _current_view_rel(to_state)

        def db_and_render(conn, transaction_id=""):
            from .projection_cmd import render_projection
            detail.update({
                "transaction_id": transaction_id,
                "producer": source_command,
                "schema_version": active_version(),
            })
            # Final Hardening（Task 2）：附加治理事件以同一 transaction_id 先写，
            # 与 STATE/HANDOFF/UPDATE 在同一 durable transaction。
            # Third Hardening（P0-7）：若事件 artifact 同时被 frontmatter 更新，
            # artifact_digest 必须绑定**最终**文件字节（事件 digest == 最终文件 digest）。
            fm_texts = {}
            for rel, fm_values in (frontmatter_updates or {}).items():
                fm_texts[rel] = _frontmatter_text(task_dir / rel, fm_values)
            for ev in (extra_events or []):
                ev_detail = dict(detail)
                ev_detail.update(ev.get("detail_extra") or {})
                ev_artifact = ev_detail.get("artifact")
                if ev_artifact and ev_artifact in fm_texts:
                    from .digest import compute_text_artifact_digest
                    ev_detail["artifact_digest"] = compute_text_artifact_digest(
                        fm_texts[ev_artifact]
                    )
                conn.execute(
                    "INSERT INTO task_event (task_id,event_type,from_state,to_state,actor_role,summary,detail_json,evidence_path,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (task_id, ev.get("type"), current, to_state, ev.get("actor", actor),
                     ev.get("summary", summary), json.dumps(ev_detail, ensure_ascii=False),
                     ev.get("evidence_path"), timestamp),
                )
            conn.execute(
                "INSERT INTO task_event (task_id,event_type,from_state,to_state,actor_role,summary,detail_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (task_id, "STATE", current, to_state, actor, summary, json.dumps(detail, ensure_ascii=False), timestamp),
            )
            handoff_detail = dict(detail)
            handoff_detail["handoff_payload"] = {
                "handoff_schema": "tp-spec.handoff/v1",
                "from_actor": actor,
                "to_actor": owner,
                "state": to_state,
                "actions": args.action or ["读取正式工件并执行当前状态职责"],
                "constraints": args.constraint or ["正式事实以任务工件和事件账本为准"],
                "evidence": evidence or [],
                "flush_id": flush_id,
                "handoff_record": handoff_record,
            }
            conn.execute(
                "INSERT INTO task_event (task_id,event_type,to_state,actor_role,summary,detail_json,created_at) VALUES (?,?,?,?,?,?,?)",
                (task_id, "HANDOFF", to_state, actor, summary, json.dumps(handoff_detail, ensure_ascii=False), timestamp),
            )
            conn.execute(
                "UPDATE task SET current_state=?, current_stage=?, owner_role=?, updated_at=?, "
                "completed_at=CASE WHEN ?='COMPLETED' THEN ? ELSE completed_at END WHERE task_id=?",
                (to_state, to_state, owner, timestamp, to_state, timestamp, task_id),
            )
            committed = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
            status_yaml, events_jsonl, warnings = render_projection(conn, committed)
            if on_projection_warnings is not None:
                on_projection_warnings(warnings)
            texts = {
                "status.yaml": status_yaml,
                "events.jsonl": events_jsonl,
                "handoff.json": json.dumps(handoff_record, ensure_ascii=False, indent=2) + "\n",
            }
            for rel, text in fm_texts.items():
                texts[rel] = text
            for rel, text in (extra_texts or {}).items():
                texts[rel] = text
            return _finalize_texts(
                task_dir,
                texts,
                view_rel,
                lambda: _rebuild_current_view_text(task_dir, committed, summary, flush_id),
            )

        rel_paths = ["status.yaml", "events.jsonl", "handoff.json", view_rel]
        if frontmatter_updates:
            rel_paths.extend(list(frontmatter_updates.keys()))
        if extra_texts:
            rel_paths.extend(list(extra_texts.keys()))
        _commit_with_recovery(
            task_dir, conn, rel_paths, db_and_render,
            task_id=task_id, operation=source_command,
            db_state_before=current, target_state=to_state,
            owner_before=task["owner_role"] or "", owner_after=owner,
            flush_id=flush_id,
        )
        return TransitionResult(ok=True, message=f"{source_command}: {current} -> {to_state}; owner={owner}", flush_id=flush_id)
    finally:
        if owned_conn:
            conn.close()
