# -*- coding: utf-8 -*-
"""Artifact and evidence validation helpers for the current workflow."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import frontmatter
from .digest import compute_architecture_subject_digest_for_detail

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
class VisualVerificationResult:
    ok: bool
    errors: List[str] = field(default_factory=list)
    evidence_paths: List[str] = field(default_factory=list)
    manifest: Dict[str, Any] = field(default_factory=dict)


def validate_visual_verification_manifest(
    task_dir: Path,
    manifest_path: str,
    *,
    expected_change_set_id: str,
    acceptance_ids: Optional[set[str]] = None,
) -> VisualVerificationResult:
    """校验真实浏览器视觉 Evidence Manifest，不解释图片语义。"""
    from .evidence import validate_evidence_path

    root = Path(task_dir).resolve()
    errors: List[str] = []
    evidence_paths: List[str] = []

    def add_evidence(raw: Any, field_name: str, *, required: bool = True) -> None:
        value = str(raw or "").strip()
        if not value:
            if required:
                errors.append(f"{field_name} is required")
            return
        checked = validate_evidence_path(root, value, require_evidence_dir=True)
        if not checked.ok:
            errors.append(f"{field_name} invalid evidence: {checked.error}")
            return
        if checked.path not in evidence_paths:
            evidence_paths.append(checked.path)

    add_evidence(manifest_path, "manifest")
    if errors:
        return VisualVerificationResult(False, errors, evidence_paths, {})
    try:
        data = json.loads((root / manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return VisualVerificationResult(False, [f"manifest JSON invalid: {exc}"], evidence_paths, {})
    if not isinstance(data, dict):
        return VisualVerificationResult(False, ["manifest must be a JSON object"], evidence_paths, {})
    if data.get("schema") != "tp-spec.visual-verification/v1":
        errors.append("schema must be tp-spec.visual-verification/v1")
    if str(data.get("change_set_id") or "") != str(expected_change_set_id or ""):
        errors.append("change_set_id must match current verified product content")
    if not str(data.get("executed_at") or "").strip():
        errors.append("executed_at is required")
    if not str(data.get("browser") or "").strip():
        errors.append("browser is required")

    auth = data.get("auth") or {}
    if not isinstance(auth, dict):
        errors.append("auth must be an object")
        auth = {}
    bypass = auth.get("temporary_bypass_used", False)
    if not isinstance(bypass, bool):
        errors.append("auth.temporary_bypass_used must be boolean")
    elif bypass:
        add_evidence(auth.get("cleanup_evidence"), "auth.cleanup_evidence")

    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("cases must be a non-empty list")
        cases = []
    known_acceptance = set(acceptance_ids or set())
    for index, case in enumerate(cases):
        prefix = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if not str(case.get("id") or "").strip():
            errors.append(f"{prefix}.id is required")
        refs = case.get("acceptance_refs")
        if not isinstance(refs, list) or not refs or any(not str(x or "").strip() for x in refs):
            errors.append(f"{prefix}.acceptance_refs must be a non-empty list")
            refs = []
        if known_acceptance:
            unknown = [str(x) for x in refs if str(x) not in known_acceptance]
            if unknown:
                errors.append(f"{prefix}.acceptance_refs unknown: {', '.join(unknown)}")
        if not str(case.get("route") or "").strip():
            errors.append(f"{prefix}.route is required")
        viewport = case.get("viewport")
        if not isinstance(viewport, dict):
            errors.append(f"{prefix}.viewport is required")
        else:
            for dim in ("width", "height"):
                value = viewport.get(dim)
                if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                    errors.append(f"{prefix}.viewport.{dim} must be a positive integer")
        if not str(case.get("state") or "").strip():
            errors.append(f"{prefix}.state is required")
        add_evidence(case.get("actual"), f"{prefix}.actual")
        add_evidence(case.get("report"), f"{prefix}.report")
        add_evidence(case.get("reference"), f"{prefix}.reference", required=False)
        add_evidence(case.get("diff"), f"{prefix}.diff", required=False)
        if not isinstance(case.get("horizontal_overflow"), bool):
            errors.append(f"{prefix}.horizontal_overflow must be boolean")
        console_errors = case.get("console_errors")
        if not isinstance(console_errors, int) or isinstance(console_errors, bool) or console_errors < 0:
            errors.append(f"{prefix}.console_errors must be a non-negative integer")
        if not isinstance(case.get("failed_requests"), list):
            errors.append(f"{prefix}.failed_requests must be a list")

    return VisualVerificationResult(not errors, errors, evidence_paths, data)


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


def _design_digest(task_dir: Path, detail=None) -> str:
    """当前设计 digest（受评审内容指纹）。

    复用单一摘要实现和 Review 事件已绑定的实际输入集合与记录模式，不重新猜受审范围。
    """
    return compute_architecture_subject_digest_for_detail(task_dir, detail)


def _effective_level(risk: str, flow: str) -> str:
    """取两者较高等级。"""
    order = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
    r = order.get(risk, 0)
    f = order.get(flow, 0)
    return risk if r >= f else flow


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


def _check_test_guide(task_dir: Path, issues: List[ValidationIssue],
                      require_skeleton: bool = False, require_development: bool = False,
                      require_verification: bool = False, to_state: str = "") -> None:
    """Validate the tester-facing guide without making it a duplicate workflow ledger.

    Real-task pressure testing showed that lifecycle flags, section ownership, AC coverage
    and verification-result duplication caused roles to spend substantial effort keeping
    governance metadata synchronized.  The authoritative lifecycle already lives in
    SQLite/task_event, while acceptance.md + codex-review.md carry verification outcomes.

    Therefore the guide is now a *human execution aid*: for L2/L3 transitions its presence
    and parseable front matter are sufficient.
    """
    data = _frontmatter_dict(task_dir, "requirement-test-guide.md")
    if data is None:
        issues.append(ValidationIssue(
            code=TEST_GUIDE_INCOMPLETE,
            message="requirement-test-guide.md is required for this transition",
            artifact="requirement-test-guide.md",
        ))
        return


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
    result = yaml_checks.check_acceptance_with_owner(
        text, conn=conn, task_id=task_id, task_dir=task_dir,
        enforce_completion=enforce_no_pending, allow_human_pending=allow_human_pending,
    )
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
    # A deferred AC cannot stay an integral PASS. Only the AC's own declared
    # obligation is compared; an out-of-scope suggestion never demotes a satisfied
    # AC. The Owner corrects it through the existing NEEDS_FIX/PENDING entries.
    from .task_cmd import _acceptance_table_rows
    deferred_acs = {str(entry.get("ac") or "").strip() for entry in result.deferred_entries}
    rows_now = _acceptance_table_rows(text)
    conflicting = sorted(ac for ac in deferred_acs if ac and (rows_now.get(ac) or {}).get("verdict") == "PASS")
    if conflicting:
        issues.append(ValidationIssue(
            code=DEFERRED_ACCEPTANCE_INVALID,
            message="deferred_acceptance " + ", ".join(conflicting)
                    + " also records PASS; record the remaining gap as PENDING instead",
            artifact="acceptance.md",
            field="deferred_acceptance",
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
                        message="codex-review PASS evidence 'none' is rejected; requires a real local_file",
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
