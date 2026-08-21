# -*- coding: utf-8 -*-
"""V5.2.6 deterministic, read-only workflow orchestration.

Workflow chooses *when* to invoke a role.  Skills choose *how* to do the work.
The existing Task Runtime remains the only durable fact ledger.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

from . import config_loader
from . import db as dbmod
from . import delivery_contract
from . import environment
from . import risk_signals
from . import workflow_controls
from .version import active_version

LEVELS = ("L0", "L1", "L2", "L3")
TERMINAL = {"COMPLETED", "CANCELLED"}
PUBLIC_STATES = {"NEW", "ACTIVE", "BLOCKED", "COMPLETED", "CANCELLED"}
ROUTE_SCHEMA = "tp-spec.workflow-route/v1"
DECISION_SCHEMA = "tp-spec.workflow-decision/v1"
KNOWN_EFFECTS = {"repo_mutation"}


class OrchestrationError(ValueError):
    pass


def _rank(level: Optional[str]) -> int:
    try:
        return LEVELS.index(str(level or "").upper())
    except ValueError:
        return -1


def resolve_effective_level(risk_level: Optional[str], flow_level: Optional[str]) -> str:
    r, f = _rank(risk_level), _rank(flow_level)
    if r < 0 and f < 0:
        raise OrchestrationError(f"invalid/missing risk_level and flow_level: {risk_level!r}/{flow_level!r}")
    return LEVELS[max(r, f)]


def load_contract(base_root: Optional["str | Path"] = None) -> Dict[str, Any]:
    return config_loader.load_config(
        "governance/orchestration.yaml",
        schema_name="orchestration",
        base_root=base_root,
        strict_unknown_fields=True,
        use_cache=False,
    )


def load_role_catalog(base_root: Optional["str | Path"] = None) -> Dict[str, Any]:
    return config_loader.load_config(
        "governance/role-catalog.yaml",
        schema_name="role-catalog",
        base_root=base_root,
        strict_unknown_fields=True,
        use_cache=False,
    )


def _root(base_root: Optional["str | Path"] = None) -> Path:
    return (Path(base_root) if base_root else Path(__file__).resolve().parent.parent).resolve()


def _safe_child(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    try:
        p.relative_to(root)
    except ValueError as exc:
        raise OrchestrationError(f"path escapes Base: {rel}") from exc
    return p


def _normalized_skill_sha(path: Path) -> str:
    text = path.read_bytes().decode("utf-8-sig")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest().upper()


def _frontmatter(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    m = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", text, re.S)
    if not m:
        raise OrchestrationError(f"invalid Skill front matter: {path}")
    data = yaml.safe_load(m.group(1))
    if not isinstance(data, dict):
        raise OrchestrationError(f"Skill front matter is not mapping: {path}")
    return data


def validate_contract(base_root: Optional["str | Path"] = None) -> List[str]:
    root = _root(base_root)
    errors: List[str] = []
    try:
        contract = load_contract(root)
        catalog = load_role_catalog(root)
    except Exception as exc:
        return [str(exc)]
    version = active_version(root)
    if contract.get("version") != version:
        errors.append(f"orchestration.version={contract.get('version')!r} != VERSION={version!r}")
    if catalog.get("catalog_version") != version or catalog.get("base_version") != version:
        errors.append("role catalog version is not the active Base contract")
    if contract.get("runtime", {}).get("new_public_states") is not False:
        errors.append("orchestration must not introduce public states")
    if contract.get("runtime", {}).get("new_database_objects") is not False:
        errors.append("orchestration must not introduce database objects")
    confirmation = contract.get("confirmation") or {}
    if confirmation.get("default_policy") != "material":
        errors.append("Base default confirmation policy must remain material")
    if set(confirmation.get("supported_policies") or []) != {"material", "each_stage"}:
        errors.append("confirmation policies must be exactly material + each_stage")
    if confirmation.get("user_preference_path") != "~/.tp-spec/preferences.yaml":
        errors.append("confirmation preference must be user-level ~/.tp-spec/preferences.yaml")
    if contract.get("runtime", {}).get("ordinary_confirmation_persisted") is not True:
        errors.append("each-stage confirmations must be persisted as trusted Runtime events")
    if contract.get("execution", {}).get("concurrent_workflow_stages") is not False:
        errors.append("dependent workflow stages must remain sequential")
    if contract.get("execution", {}).get("prefer_parallel_isolated_subagents") is not True:
        errors.append("orchestration must prefer isolated parallel subagents when supported")
    if contract.get("execution", {}).get("sequential_isolation_fallback") is not True:
        errors.append("orchestration must retain isolated sequential fallback")
    delivery_fast = (contract.get("execution") or {}).get("delivery_fast_path") or {}
    if int(delivery_fast.get("max_incremental_ai_overhead_percent") or -1) != 5:
        errors.append("delivery fast-path AI overhead budget must be exactly 5 percent")
    if delivery_fast.get("allow_default_subagents") is not False:
        errors.append("delivery fast path must forbid default subagents")
    if delivery_fast.get("allow_full_task_reread") is not False or delivery_fast.get("allow_full_knowledge_scan") is not False:
        errors.append("delivery fast path must forbid default full rereads/scans")
    if delivery_fast.get("require_targeted_knowledge_search") is not True:
        errors.append("delivery fast path must require targeted Knowledge search")

    if "material_confirmation_prefix" in (contract.get("signals") or {}):
        errors.append("legacy public DECISION material confirmation marker must not remain active")

    # Deep-mode capabilities remain owned by the professional roles.  The
    # orchestrator only decides *when* to request them, so doctor verifies the
    # capability contracts rather than reimplementing either mode here.
    planning_path = root / "governance" / "planning-strategy.yaml"
    try:
        planning = yaml.safe_load(planning_path.read_text(encoding="utf-8-sig")) or {}
        if not isinstance(planning, dict):
            raise OrchestrationError("planning-strategy.yaml must be a mapping")
        if str(planning.get("contract_version") or "") != version:
            errors.append("planning strategy is not on the active Base contract")
        comparative = ((planning.get("modes") or {}).get("COMPARATIVE") or {})
        execution = comparative.get("execution") or {}
        fan_out = comparative.get("fan_out") or {}
        preferred = str(execution.get("preferred") or "").lower()
        fallback = str(execution.get("fallback") or "").lower()
        isolation = str(fan_out.get("isolation") or "").lower()
        perspectives = fan_out.get("perspectives") or []
        if "parallel" not in preferred or "isolat" not in preferred:
            errors.append("UltraPlan preferred execution must be isolated parallel fan-out")
        if "sequential" not in fallback or "isolat" not in fallback:
            errors.append("UltraPlan must define isolated sequential fallback")
        if execution.get("fallback_must_not_block") is not True:
            errors.append("UltraPlan sequential fallback must not block")
        if len(perspectives) < 3 or "do not see one another" not in isolation:
            errors.append("UltraPlan candidate isolation contract is incomplete")
    except Exception as exc:
        errors.append(f"planning strategy: {exc}")

    roles: Dict[str, Dict[str, Any]] = {}
    for item in catalog.get("roles") or []:
        if isinstance(item, dict) and item.get("workflow_role"):
            roles[str(item["workflow_role"])] = item
    if contract.get("entry_role") not in roles:
        errors.append(f"entry_role not declared: {contract.get('entry_role')}")

    workflow = config_loader.load_config(
        "governance/workflow.yaml", schema_name="workflow", base_root=root,
        strict_unknown_fields=True, use_cache=False,
    )
    phases = set(((workflow.get("rules") or {}).get("phases") or {}).get("values") or [])
    for level in LEVELS:
        pipeline = (contract.get("pipelines") or {}).get(level)
        if not isinstance(pipeline, list) or not pipeline:
            errors.append(f"pipeline {level} missing/empty")
            continue
        seen: set[str] = set()
        for i, step in enumerate(pipeline):
            if not isinstance(step, dict):
                errors.append(f"{level}[{i}] must be mapping")
                continue
            stage = str(step.get("stage") or "")
            role = str(step.get("role") or "")
            phase = str(step.get("phase") or "")
            mode = str(step.get("mode") or "")
            effects = step.get("effects")
            if not isinstance(effects, list):
                errors.append(f"{level}.{stage or i}: effects must be a list")
            else:
                unknown_effects = sorted({str(x) for x in effects} - KNOWN_EFFECTS)
                if unknown_effects:
                    errors.append(f"{level}.{stage or i}: unknown effects {unknown_effects}")
            if not stage or stage in seen:
                errors.append(f"{level}: duplicate/missing stage {stage!r}")
            seen.add(stage)
            if role not in roles:
                errors.append(f"{level}.{stage}: unknown role {role!r}")
            if phase not in phases:
                errors.append(f"{level}.{stage}: unknown phase {phase!r}")
            if mode not in {"DIRECT", "AUTO_PLANNING", "AUTO_REVIEW"}:
                errors.append(f"{level}.{stage}: unknown mode {mode!r}")
            orchestration_caps = set((roles.get(role) or {}).get("orchestration_capabilities") or [])
            if mode == "AUTO_PLANNING" and "auto_planning_host" not in orchestration_caps:
                errors.append(f"{level}.{stage}: AUTO_PLANNING role must declare auto_planning_host")
            if mode == "AUTO_REVIEW" and "auto_review_host" not in orchestration_caps:
                errors.append(f"{level}.{stage}: AUTO_REVIEW role must declare auto_review_host")
            if role == "tp-knowledge":
                errors.append(f"{level}.{stage}: tp-knowledge is standalone and must never enter the development workflow")

    for role_id, item in roles.items():
        try:
            rel = str(item.get("skill_path") or "")
            p = _safe_child(root, rel)
            if not p.is_file():
                errors.append(f"{role_id}: missing skill_path {rel}")
                continue
            fm = _frontmatter(p)
            if fm.get("id") != role_id or fm.get("type") != item.get("type"):
                errors.append(f"{role_id}: catalog/front matter identity mismatch")
            if str(fm.get("version")) != version:
                errors.append(f"{role_id}: Skill version {fm.get('version')!r} != {version}")
            if _normalized_skill_sha(p) != str(item.get("content_sha256") or "").upper():
                errors.append(f"{role_id}: content_sha256 mismatch")
            if role_id == "tp-software-lifecycle":
                if item.get("type") != "control-role" or list(item.get("owns_states") or []) != ["NEW"]:
                    errors.append("tp-software-lifecycle must be the NEW owner control-role")
            if role_id == "tp-software-architect" and "auto_planning_host" not in set(item.get("orchestration_capabilities") or []):
                errors.append("tp-software-architect must declare auto_planning_host")
            if role_id == "tp-code-reviewer" and "auto_review_host" not in set(item.get("orchestration_capabilities") or []):
                errors.append("tp-code-reviewer must declare auto_review_host")
        except Exception as exc:
            errors.append(f"{role_id}: {exc}")
    return errors


def _parse_detail(raw: Any) -> Dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_task_facts(task_id: str, db_path: Optional[str] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    path = dbmod.resolve_db_path(db_path, task_id=task_id)
    if not Path(path).is_file():
        raise OrchestrationError(f"database not found: {path}")
    conn = dbmod.connect_readonly(path)
    try:
        row = conn.execute(
            "SELECT t.*, p.root_path AS project_root_path FROM task t "
            "LEFT JOIN project p ON p.project_id=t.project_id WHERE t.task_id=?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise OrchestrationError(f"task not found: {task_id}")
        events = conn.execute(
            "SELECT id,task_id,event_type,from_state,to_state,from_stage,to_stage,actor_role,reason_code,summary,detail_json,workflow_version,created_at "
            "FROM task_event WHERE task_id=? ORDER BY id", (task_id,),
        ).fetchall()
        return dict(row), [dict(e) for e in events]
    finally:
        conn.close()


def _decision_signal_ids(events: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for e in events:
        if str(e.get("event_type") or "").upper() != "DECISION" or str(e.get("actor_role") or "") != "human_owner":
            continue
        summary = str(e.get("summary") or "").strip()
        if summary:
            result[summary] = max(result.get(summary, 0), int(e.get("id") or 0))
    return result


def _decision_signals(events: Iterable[Dict[str, Any]]) -> set[str]:
    return set(_decision_signal_ids(events))


def _latest_verification(events: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for e in reversed(list(events)):
        if e.get("event_type") != "VERIFICATION_COMPLETED" or e.get("actor_role") != "tp-test-engineer":
            continue
        d = _parse_detail(e.get("detail_json"))
        decision = str(d.get("decision") or e.get("summary") or "").upper()
        return {"decision": decision, "detail": d, "event": e}
    return None


def _latest_arch_review(events: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for e in reversed(list(events)):
        if e.get("event_type") != "REVIEW_COMPLETED" or e.get("actor_role") != "tp-software-architect":
            continue
        d = _parse_detail(e.get("detail_json"))
        if str(d.get("review_kind") or "").upper() != "ARCHITECTURE":
            continue
        decision = str(d.get("decision") or e.get("summary") or "").upper()
        return {"decision": decision, "detail": d, "event": e}
    return None

def _latest_code_review(events: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for e in reversed(list(events)):
        if e.get("event_type") != "REVIEW_COMPLETED" or e.get("actor_role") != "tp-code-reviewer":
            continue
        d = _parse_detail(e.get("detail_json"))
        kind = str(d.get("review_kind") or "CODE").upper()
        if kind not in {"CODE", "IMPLEMENTATION", "ULTRA_REVIEW"}:
            continue
        decision = str(d.get("decision") or e.get("summary") or "").upper()
        return {"decision": decision, "detail": d, "event": e}
    return None


def _latest_checkpoint(events: Iterable[Dict[str, Any]], *, actor: str, phase: str) -> Optional[Dict[str, Any]]:
    for e in reversed(list(events)):
        if e.get("event_type") != "FACT" or e.get("actor_role") != actor:
            continue
        d = _parse_detail(e.get("detail_json"))
        if d.get("operation") == "CHECKPOINT" and str(d.get("phase") or e.get("to_stage") or "") == phase:
            return e
    return None


def _stage_completion_event(stage: str, events: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    mapping = {
        "requirement": ("tp-product-manager", "requirement"),
        "product": ("tp-product-manager", "product"),
        "architecture": ("tp-software-architect", "architecture"),
        "planning": ("tp-tech-lead", "planning"),
        "development": ("tp-development-engineer", "development"),
    }
    if stage in mapping:
        actor, phase = mapping[stage]
        return _latest_checkpoint(events, actor=actor, phase=phase)
    if stage == "architecture_review":
        r = _latest_arch_review(events)
        return r["event"] if r and r["decision"] == "PASS" else None
    if stage == "verification":
        v = _latest_verification(events)
        return v["event"] if v and v["decision"] == "PASS" else None
    if stage == "review":
        r = _latest_code_review(events)
        return r["event"] if r and r["decision"] == "PASS" else None
    return None

def _stage_done(stage: str, events: List[Dict[str, Any]]) -> bool:
    return _stage_completion_event(stage, events) is not None


def _stage_has_activity(stage: str, events: List[Dict[str, Any]]) -> bool:
    if _stage_done(stage, events):
        return True
    if stage == "architecture_review":
        return _latest_arch_review(events) is not None
    if stage == "verification":
        return _latest_verification(events) is not None
    if stage == "review":
        return _latest_code_review(events) is not None
    return False


def _stage_included(step: Dict[str, Any], level: str, task: Dict[str, Any], events: List[Dict[str, Any]], signals: set[str]) -> bool:
    stage = str(step["stage"])
    include = f"workflow:include-stage:{stage}"
    skip = f"workflow:skip-stage:{stage}"
    if skip in signals:
        return False
    if bool(step.get("required")) or include in signals or _stage_has_activity(stage, events):
        return True
    # A phase can contain more than one workflow stage (for example architecture
    # and architecture_review).  Current phase alone is therefore only a safe
    # resume hint when the stage name itself is the phase name.
    if stage == str(step.get("phase") or "") and str(task.get("current_stage") or "") == stage:
        return True
    trigger = step.get("trigger")
    if trigger == "architecture_risk":
        return level == "L3"
    if trigger == "behavioral_change":
        return "workflow:behavioral-change" in signals
    if trigger == "contextual":
        return include in signals
    if trigger == "deep_review":
        return "workflow:deep-review" in signals
    return False


def _current_verification_for_delivery(events: List[Dict[str, Any]], task_dir: Optional[Path]) -> Optional[Dict[str, Any]]:
    verification = _latest_verification(events)
    if not verification or verification["decision"] != "PASS":
        return None
    subject_digest = str((verification.get("detail") or {}).get("subject_digest") or "")
    if not subject_digest:
        return None
    if task_dir is not None:
        from .digest import compute_verification_subject_digest
        if compute_verification_subject_digest(task_dir) != subject_digest:
            return None
    return verification

def _delivery_completion_event(events: List[Dict[str, Any]], task_dir: Optional[Path]) -> Optional[Dict[str, Any]]:
    verification = _current_verification_for_delivery(events, task_dir)
    if not verification:
        return None
    subject_digest = str((verification.get("detail") or {}).get("subject_digest") or "")
    return delivery_contract.find_delivery_completion_event(
        events,
        verification_event=verification["event"],
        current_subject_digest=subject_digest,
    )


def _delivery_fact_pack(task: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build compact deterministic input so delivery can do targeted convergence only."""
    facts: Dict[str, Dict[str, Any]] = {}
    knowledge_signals: List[Dict[str, Any]] = []
    delivery_signals: List[str] = []
    verification_binding: Optional[Dict[str, Any]] = None
    for stage, actor in (("requirement", "tp-product-manager"),
                         ("product", "tp-product-manager"),
                         ("architecture", "tp-software-architect"),
                         ("architecture_review", "tp-software-architect"),
                         ("planning", "tp-tech-lead"),
                         ("development", "tp-development-engineer"),
                         ("verification", "tp-test-engineer"),
                         ("review", "tp-code-reviewer")):
        if stage == "verification":
            latest = _latest_verification(events)
            selected = latest["event"] if latest else None
        elif stage == "architecture_review":
            latest_review = _latest_arch_review(events)
            selected = latest_review["event"] if latest_review else None
        elif stage == "review":
            latest_review = _latest_code_review(events)
            selected = latest_review["event"] if latest_review else None
        else:
            selected = _latest_checkpoint(events, actor=actor, phase=stage)
        if not selected:
            continue
        detail = _parse_detail(selected.get("detail_json"))
        source_refs = list(detail.get("source_refs") or [])
        evidence = list(detail.get("evidence") or [])
        facts[stage] = {
            "event_id": int(selected.get("id") or 0),
            "summary": str(selected.get("summary") or ""),
            "evidence": evidence,
            "source_refs": source_refs,
        }
        for raw in detail.get("knowledge_signals") or []:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            item.setdefault("source_stage", stage)
            item.setdefault("source_event_id", int(selected.get("id") or 0))
            if evidence and not item.get("evidence"):
                item["evidence"] = evidence
            if source_refs and not item.get("source_refs"):
                item["source_refs"] = source_refs
            knowledge_signals.append(item)
        for raw in detail.get("delivery_signals") or []:
            value = str(raw or "").strip()
            if value and value not in delivery_signals:
                delivery_signals.append(value)
        if stage == "verification":
            verification_binding = {
                "event_id": int(selected.get("id") or 0),
                "subject_digest": str(detail.get("subject_digest") or ""),
                "decision": str(detail.get("decision") or selected.get("summary") or "").upper(),
            }
    return {
        "mode": "FAST_PATH",
        "max_incremental_ai_overhead_percent": 5,
        "task": {
            "task_id": task.get("task_id"),
            "risk_level": task.get("risk_level"),
            "flow_level": task.get("flow_level"),
        },
        "stage_facts": facts,
        "knowledge_signals": knowledge_signals,
        "delivery_signals": delivery_signals,
        "verification_binding": verification_binding,
        "knowledge_requirement": {
            "scope": "current project + shared",
            "targeted_search_required": True,
            "disposition_required": ["CREATED", "UPDATED", "NO_CHANGE", "DEFERRED", "BLOCKED"],
        },
        "read_policy": "targeted-only; no full Task/source/Knowledge reread by default",
        "subagents": "forbidden-by-default",
    }

def _role_capabilities(catalog: Dict[str, Any], role_id: str) -> set[str]:
    for item in catalog.get("roles") or []:
        if str(item.get("workflow_role") or "") == role_id:
            return {str(x) for x in (item.get("capabilities") or []) if str(x)}
    return set()

def _conditional_role_recommendations(contract: Dict[str, Any], catalog: Dict[str, Any], *, phase: str, signals: set[str], risk_signals: Iterable[str]) -> List[Dict[str, Any]]:
    risk_ids = {str(x) for x in risk_signals}
    role_map = {str(r.get("workflow_role")): r for r in catalog.get("roles") or [] if isinstance(r, dict)}
    recommendations: List[Dict[str, Any]] = []
    for rule in contract.get("conditional_roles") or []:
        if not isinstance(rule, dict):
            continue
        role_id = str(rule.get("role") or "")
        if phase not in {str(x) for x in (rule.get("phases") or [])}:
            continue
        trigger = str(rule.get("trigger") or "")
        matched = False
        reason = None
        if trigger == "security_risk":
            matched = "workflow:security-risk" in signals or bool(risk_ids & {"PERMISSION", "SENSITIVE_ACCESS_CONTROL", "SECURITY"})
            reason = "SECURITY_RISK"
        elif trigger == "database_risk":
            matched = "workflow:database-risk" in signals or bool(risk_ids & {"DDL", "DML", "PRODUCTION_DATA", "TRANSACTION", "HISTORICAL_REPAIR"})
            reason = "DATABASE_RISK"
        elif trigger == "deep_review":
            matched = "workflow:deep-review" in signals
            reason = "DEEP_REVIEW"
        if not matched or role_id not in role_map:
            continue
        recommendations.append({
            "role_id": role_id,
            "skill_path": str(role_map[role_id].get("skill_path") or ""),
            "trigger": trigger,
            "reason_code": reason,
            "capabilities": sorted(_role_capabilities(catalog, role_id)),
        })
    return recommendations

def _execution_mode(step: Dict[str, Any], level: str, signals: set[str]) -> str:
    mode = step.get("mode")
    if mode == "AUTO_PLANNING":
        return "COMPARATIVE" if "workflow:multiple-feasible-routes" in signals else "DIRECT"
    if mode == "AUTO_REVIEW":
        return "DEEP_REVIEW" if level == "L3" or "workflow:deep-review" in signals else "DIRECT"
    return "DIRECT"


def _decision_for_action(action: Optional[str]) -> str:
    return {
        "dispatch_role": "DISPATCH_ROLE",
        "await_confirmation": "AWAIT_CONFIRMATION",
        "await_effect_approval": "BOUNDARY_REACHED",
        "task_complete": "TASK_COMPLETE",
        "none": "NONE",
        "task_resume_after_resolution": "TASK_BLOCKED",
    }.get(str(action or ""), "NO_ACTION")


def _route_dict(task: Dict[str, Any], level: str, *, next_stage: Optional[str], role_id: Optional[str],
                skill_path: Optional[str], execution_mode: str = "DIRECT", confirmation_required: bool = False,
                confirmation_reason: Optional[str] = None, blocker: Optional[str] = None,
                reason_codes: Optional[List[str]] = None, action: Optional[str] = None,
                context: Optional[Dict[str, Any]] = None,
                transition_from_role: Optional[str] = None,
                confirmation_policy: Optional[str] = None,
                confirmation_binding: Optional[Dict[str, Any]] = None,
                wake_prompt: Optional[str] = None,
                required_effects: Optional[Iterable[str]] = None,
                allowed_effects: Optional[Iterable[str]] = None,
                decision_reason: Optional[str] = None,
                recommended_roles: Optional[List[Dict[str, Any]]] = None,
                recommended_skills: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    effects = sorted({str(x) for x in (required_effects or []) if str(x)})
    allowed = None if allowed_effects is None else sorted({str(x) for x in allowed_effects if str(x)})
    decision = _decision_for_action(action)
    requires_human = bool(confirmation_required or decision == "BOUNDARY_REACHED")
    data = {
        "schema": ROUTE_SCHEMA,
        "decision_schema": DECISION_SCHEMA,
        "decision": decision,
        "required_effects": effects,
        "requires_human": requires_human,
        "reason": decision_reason or str(action or "none"),
        "task_id": task.get("task_id"),
        "current_state": task.get("current_state"),
        "current_phase": task.get("current_stage"),
        "effective_level": level,
        "next_stage": next_stage,
        "role_id": role_id,
        "skill_path": skill_path,
        "execution_mode": execution_mode,
        "confirmation_policy": confirmation_policy,
        "confirmation_required": bool(confirmation_required),
        "confirmation_reason": confirmation_reason,
        "blocker": blocker,
        "recommended_action": action,
        "reason_codes": reason_codes or [],
        "risk_escalation_signals": list(task.get("_risk_escalation_signals") or []),
        "recommended_roles": recommended_roles or [],
        "recommended_skills": sorted({str(x) for x in (recommended_skills or []) if str(x)}),
    }
    if allowed is not None:
        data["allowed_effects"] = allowed
    if context is not None:
        data["context"] = context
    if confirmation_binding is not None:
        data["confirmation_binding"] = confirmation_binding
    if wake_prompt:
        data["wake_prompt"] = wake_prompt
    if transition_from_role and role_id and transition_from_role != role_id:
        data["transition_from_role"] = transition_from_role
        data["transition_notice_required"] = True
    return data

def _route_role_boundary(task: Dict[str, Any], level: str, events: List[Dict[str, Any]], *,
                         policy: str, next_stage: str, role_id: str, skill_path: str,
                         execution_mode: str, reason_codes: List[str],
                         source_event: Optional[Dict[str, Any]] = None,
                         source_stage: Optional[str] = None,
                         source_role: Optional[str] = None,
                         context: Optional[Dict[str, Any]] = None,
                         human_confirmation_already_satisfied: bool = False,
                         required_effects: Optional[Iterable[str]] = None,
                         allowed_effects: Optional[Iterable[str]] = None,
                         recommended_roles: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    binding: Optional[Dict[str, Any]] = None
    wake_prompt: Optional[str] = None
    transition = bool(source_event and source_role and source_role != role_id)
    if policy == "each_stage" and transition:
        binding = workflow_controls.build_boundary_binding(
            task_id=str(task.get("task_id") or ""),
            source_stage=str(source_stage or source_event.get("to_stage") or task.get("current_stage") or "other"),
            source_role=str(source_role),
            source_event_id=int(source_event.get("id") or 0),
            source_event_digest=workflow_controls.event_digest(source_event),
            target_stage=next_stage,
            target_role=role_id,
            execution_mode=execution_mode,
            confirmation_kind='ordinary',
        )
        confirmed = human_confirmation_already_satisfied or workflow_controls.find_matching_confirmation(events, binding) is not None
        if not confirmed:
            return _route_dict(
                task, level, next_stage=next_stage, role_id=role_id, skill_path=None,
                execution_mode=execution_mode, confirmation_required=True,
                confirmation_reason="EACH_STAGE_POLICY", reason_codes=reason_codes,
                action="await_confirmation", context=context,
                transition_from_role=source_role, confirmation_policy=policy,
                confirmation_binding=binding, required_effects=required_effects,
                allowed_effects=allowed_effects, recommended_roles=recommended_roles,
            )
        wake_prompt = workflow_controls.build_wake_prompt(
            task_id=str(task.get("task_id") or ""),
            workspace=str(task.get("project_root_path") or ""),
            source_stage=str(source_stage or source_event.get("to_stage") or task.get("current_stage") or "other"),
            source_role=str(source_role),
            target_stage=next_stage,
            target_role=role_id,
            execution_mode=execution_mode,
        )
    return _route_dict(
        task, level, next_stage=next_stage, role_id=role_id, skill_path=skill_path,
        execution_mode=execution_mode, confirmation_required=False,
        confirmation_reason=None, reason_codes=reason_codes, action="dispatch_role",
        context=context, transition_from_role=source_role,
        confirmation_policy=policy, wake_prompt=wake_prompt,
        required_effects=required_effects, allowed_effects=allowed_effects,
        recommended_roles=recommended_roles,
    )


def resolve_route(task_id: str, *, db_path: Optional[str] = None,
                  base_root: Optional["str | Path"] = None,
                  confirmation_policy: Optional[str] = None,
                  allowed_effects: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    root = _root(base_root)
    contract = load_contract(root)
    catalog = load_role_catalog(root)
    allowed_set = None if allowed_effects is None else {str(x) for x in allowed_effects}
    if allowed_set is not None:
        unknown_allowed = sorted(allowed_set - KNOWN_EFFECTS)
        if unknown_allowed:
            raise OrchestrationError(f"unknown allowed effects: {unknown_allowed}")
    task, events = _load_task_facts(task_id, db_path)
    try:
        policy = workflow_controls.resolve_confirmation_policy(
            confirmation_policy,
            environment.user_tp_spec_root() / "preferences.yaml",
            str((contract.get("confirmation") or {}).get("default_policy") or "material"),
        )
    except workflow_controls.PreferenceError as exc:
        raise OrchestrationError(str(exc)) from exc
    if str(task.get("base_version") or "") != active_version(root):
        raise OrchestrationError(
            f"task contract {task.get('base_version')!r} != active {active_version(root)!r}; migrate first"
        )
    state = str(task.get("current_state") or "")
    if state not in PUBLIC_STATES:
        raise OrchestrationError(f"unknown public state: {state!r}")
    level = resolve_effective_level(task.get("risk_level"), task.get("flow_level"))
    project_root = str(task.get("project_root_path") or "").strip()
    task_dir: Optional[Path] = None
    risk_scan = {"floor": None, "signals": []}
    if project_root:
        task_dir = Path(project_root) / ".tp-spec" / "tasks" / task_id
        risk_scan = risk_signals.scan_task_artifacts(task_dir, base_root=root)
        floor = str(risk_scan.get("floor") or "")
        if _rank(floor) > _rank(level):
            level = floor
    task["_risk_escalation_signals"] = list(risk_scan.get("signals") or []) if _rank(str(risk_scan.get("floor") or "")) > _rank(resolve_effective_level(task.get("risk_level"), task.get("flow_level"))) else []
    role_map = {str(r["workflow_role"]): r for r in catalog.get("roles") or []}
    signal_ids = _decision_signal_ids(events)
    signals = set(signal_ids)

    if state in TERMINAL:
        return _route_dict(task, level, next_stage=None, role_id=None, skill_path=None,
                           reason_codes=["TASK_TERMINAL"], action="none", confirmation_policy=policy)
    if state == "BLOCKED":
        blocker = next((str(e.get("summary") or "") for e in reversed(events) if e.get("event_type") == "BLOCKER"), "task is BLOCKED")
        return _route_dict(task, level, next_stage=None, role_id=None, skill_path=None,
                           blocker=blocker, reason_codes=["TASK_BLOCKED"], action="task_resume_after_resolution",
                           confirmation_policy=policy)

    review = _latest_arch_review(events)
    if review and review["decision"] in {"REVISE", "BLOCKED"}:
        architecture_after_review = _stage_completion_event("architecture", events)
        if not architecture_after_review or int(architecture_after_review.get("id") or 0) <= int(review["event"].get("id") or 0):
            role = role_map["tp-software-architect"]
            code = "ARCHITECTURE_REVIEW_REVISE" if review["decision"] == "REVISE" else "ARCHITECTURE_REVIEW_BLOCKED_REWORK"
            mode = "COMPARATIVE" if "workflow:multiple-feasible-routes" in signals else "DIRECT"
            return _route_role_boundary(
                task, level, events, policy=policy, next_stage="architecture",
                role_id="tp-software-architect", skill_path=str(role["skill_path"]),
                execution_mode=mode, reason_codes=[code], source_event=review["event"],
                source_stage="architecture_review", source_role="tp-software-architect",
            )

    verification = _latest_verification(events)
    if verification and verification["decision"] in {"NEEDS_FIX", "FAIL"}:
        if verification["decision"] == "NEEDS_FIX":
            target = "development"
            code = "VERIFICATION_NEEDS_FIX"
        else:
            root_signal = next((s for s in signals if s.startswith("workflow:root-cause:")), "")
            cause = root_signal.split(":", 2)[2] if root_signal else ""
            if cause in {"requirement", "architecture", "development"}:
                target = cause
            else:
                target = "architecture" if level in {"L2", "L3"} else "development"
            code = "VERIFICATION_FAIL_REASSESS"
        target_completion = _stage_completion_event(target, events)
        if not target_completion or int(target_completion.get("id") or 0) <= int(verification["event"].get("id") or 0):
            stage_to_role = {
                "requirement": "tp-product-manager",
                "architecture": "tp-software-architect",
                "development": "tp-development-engineer",
            }
            rid = stage_to_role[target]
            mode = "COMPARATIVE" if target == "architecture" and "workflow:multiple-feasible-routes" in signals else "DIRECT"
            return _route_role_boundary(
                task, level, events, policy=policy, next_stage=target, role_id=rid,
                skill_path=str(role_map[rid]["skill_path"]), execution_mode=mode,
                reason_codes=[code], source_event=verification["event"],
                source_stage="verification", source_role="tp-test-engineer",
            )

    pipeline = (contract.get("pipelines") or {}).get(level) or []
    included = [s for s in pipeline if _stage_included(s, level, task, events, signals)]
    upstream_completion_id = 0
    previous_role: Optional[str] = None
    previous_stage: Optional[str] = None
    previous_completion: Optional[Dict[str, Any]] = None
    for step in included:
        stage = str(step["stage"])
        completion = _delivery_completion_event(events, task_dir) if stage == "delivery" else _stage_completion_event(stage, events)
        if completion is not None and int(completion.get("id") or 0) > upstream_completion_id:
            upstream_completion_id = int(completion.get("id") or 0)
            previous_role = str(step.get("role") or "") or None
            previous_stage = stage
            previous_completion = completion
            continue
        rid = str(step["role"])
        role = role_map.get(rid)
        if role is None:
            raise OrchestrationError(f"pipeline references unknown role: {rid}")
        mode = _execution_mode(step, level, signals)
        context = _delivery_fact_pack(task, events) if stage == "delivery" else None
        recommended_roles = _conditional_role_recommendations(
            contract, catalog, phase=str(step.get("phase") or stage), signals=signals,
            risk_signals=task.get("_risk_escalation_signals") or [],
        )
        step_effects = [str(x) for x in (step.get("effects") or [])]
        if allowed_set is not None:
            missing_effects = sorted(set(step_effects) - allowed_set)
            if missing_effects:
                return _route_dict(
                    task, level, next_stage=stage, role_id=None, skill_path=None,
                    execution_mode=mode, confirmation_required=False,
                    reason_codes=["EXECUTION_BOUNDARY_REACHED"], action="await_effect_approval",
                    context=context, transition_from_role=previous_role,
                    confirmation_policy=policy, required_effects=missing_effects,
                    allowed_effects=allowed_set, decision_reason="effect_not_allowed",
                    recommended_roles=recommended_roles,
                )

        # Material confirmations are independent of each-stage flow control and
        # therefore run first. A valid material decision may satisfy the ordinary
        # boundary confirmation one-way; an ordinary WORKFLOW_CONFIRMATION can
        # never satisfy a material decision.
        material_satisfied = False
        if stage == "development" and level in {"L2", "L3"} and _stage_done("architecture", events):
            if previous_completion is None or previous_role is None or previous_stage is None:
                raise OrchestrationError("material architecture->development boundary lacks a decision-complete source fact")
            material_binding = workflow_controls.build_boundary_binding(
                task_id=str(task.get("task_id") or ""),
                source_stage=previous_stage,
                source_role=previous_role,
                source_event_id=int(previous_completion.get("id") or 0),
                source_event_digest=workflow_controls.event_digest(previous_completion),
                target_stage=stage,
                target_role=rid,
                execution_mode=mode,
                confirmation_kind='material',
            )
            if workflow_controls.find_matching_confirmation(events, material_binding) is None:
                return _route_dict(
                    task, level, next_stage=stage, role_id=rid, skill_path=None,
                    execution_mode=mode, confirmation_required=True,
                    confirmation_reason="MATERIAL_ARCHITECTURE_TO_IMPLEMENTATION",
                    reason_codes=["NEXT_STAGE_RESOLVED"], action="await_confirmation",
                    context=context, transition_from_role=previous_role,
                    confirmation_policy=policy, confirmation_binding=material_binding,
                    required_effects=step_effects, allowed_effects=allowed_set,
                    recommended_roles=recommended_roles,
                )
            material_satisfied = True

        return _route_role_boundary(
            task, level, events, policy=policy, next_stage=stage, role_id=rid,
            skill_path=str(role["skill_path"]), execution_mode=mode,
            reason_codes=["NEXT_STAGE_RESOLVED"], source_event=previous_completion,
            source_stage=previous_stage, source_role=previous_role, context=context,
            human_confirmation_already_satisfied=material_satisfied,
            required_effects=step_effects, allowed_effects=allowed_set,
            recommended_roles=recommended_roles,
        )

    return _route_dict(task, level, next_stage="complete", role_id=None, skill_path=None,
                       reason_codes=["PIPELINE_COMPLETE"], action="task_complete",
                       confirmation_policy=policy)
