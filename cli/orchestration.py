# -*- coding: utf-8 -*-
"""V5.2.1 deterministic, read-only workflow orchestration.

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
from . import risk_signals
from .version import active_version

LEVELS = ("L0", "L1", "L2", "L3")
TERMINAL = {"COMPLETED", "CANCELLED"}
PUBLIC_STATES = {"NEW", "ACTIVE", "BLOCKED", "COMPLETED", "CANCELLED"}
ROUTE_SCHEMA = "tp-spec.workflow-route/v1"


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
        "agents/role-catalog.yaml",
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
            if not stage or stage in seen:
                errors.append(f"{level}: duplicate/missing stage {stage!r}")
            seen.add(stage)
            if role not in roles:
                errors.append(f"{level}.{stage}: unknown role {role!r}")
            if phase not in phases:
                errors.append(f"{level}.{stage}: unknown phase {phase!r}")
            if mode not in {"DIRECT", "AUTO_PLANNING", "AUTO_REVIEW"}:
                errors.append(f"{level}.{stage}: unknown mode {mode!r}")
            if mode == "AUTO_PLANNING" and role != "tp-architecture-design":
                errors.append(f"{level}.{stage}: AUTO_PLANNING must be owned by tp-architecture-design")
            if mode == "AUTO_REVIEW" and role != "tp-verification-engineering":
                errors.append(f"{level}.{stage}: AUTO_REVIEW must be owned by tp-verification-engineering")
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
            skill_text = p.read_text(encoding="utf-8-sig")
            if role_id == "tp-workflow-orchestrator":
                if item.get("type") != "control-role" or item.get("owns_states"):
                    errors.append("tp-workflow-orchestrator must be a stateless control-role")
            elif role_id == "tp-architecture-design":
                if "Deep Planning Capability" not in skill_text or "UltraPlan" not in skill_text:
                    errors.append("tp-architecture-design no longer declares UltraPlan capability")
            elif role_id == "tp-verification-engineering":
                if "Deep Review Capability" not in skill_text or "UltraReview" not in skill_text:
                    errors.append("tp-verification-engineering no longer declares UltraReview capability")
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
            "SELECT id,event_type,from_state,to_state,from_stage,to_stage,actor_role,reason_code,summary,detail_json,created_at "
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
        if e.get("event_type") != "VERIFICATION_COMPLETED" or e.get("actor_role") != "tp-verification-engineering":
            continue
        d = _parse_detail(e.get("detail_json"))
        decision = str(d.get("decision") or e.get("summary") or "").upper()
        return {"decision": decision, "detail": d, "event": e}
    return None


def _latest_arch_review(events: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for e in reversed(list(events)):
        if e.get("event_type") != "REVIEW_COMPLETED" or e.get("actor_role") != "tp-architecture-review":
            continue
        d = _parse_detail(e.get("detail_json"))
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
        "requirement": ("tp-requirement-analysis", "requirement"),
        "product": ("tp-product-design", "product"),
        "architecture": ("tp-architecture-design", "architecture"),
        "development": ("tp-development-engineering", "development"),
        "delivery": ("tp-delivery-convergence", "delivery"),
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
    return False


def _delivery_fact_pack(task: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build compact deterministic input so delivery does not reread the whole Task."""
    facts: Dict[str, Dict[str, Any]] = {}
    for stage, actor in (("requirement", "tp-requirement-analysis"),
                         ("architecture", "tp-architecture-design"),
                         ("development", "tp-development-engineering"),
                         ("verification", "tp-verification-engineering")):
        if stage == "verification":
            latest = _latest_verification(events)
            selected = latest["event"] if latest else None
        else:
            selected = _latest_checkpoint(events, actor=actor, phase=stage)
        if selected:
            detail = _parse_detail(selected.get("detail_json"))
            facts[stage] = {
                "event_id": int(selected.get("id") or 0),
                "summary": str(selected.get("summary") or ""),
                "evidence": list(detail.get("evidence") or []),
            }
    return {
        "mode": "FAST_PATH",
        "max_incremental_ai_overhead_percent": 5,
        "task": {"task_id": task.get("task_id"), "risk_level": task.get("risk_level"), "flow_level": task.get("flow_level")},
        "stage_facts": facts,
        "read_policy": "targeted-only; no full Task/source/Knowledge reread by default",
        "subagents": "forbidden-by-default",
    }


def _execution_mode(step: Dict[str, Any], level: str, signals: set[str]) -> str:
    mode = step.get("mode")
    if mode == "AUTO_PLANNING":
        return "COMPARATIVE" if "workflow:multiple-feasible-routes" in signals else "DIRECT"
    if mode == "AUTO_REVIEW":
        return "DEEP_REVIEW" if level == "L3" or "workflow:deep-review" in signals else "DIRECT"
    return "DIRECT"


def _route_dict(task: Dict[str, Any], level: str, *, next_stage: Optional[str], role_id: Optional[str],
                skill_path: Optional[str], execution_mode: str = "DIRECT", confirmation_required: bool = False,
                confirmation_reason: Optional[str] = None, blocker: Optional[str] = None,
                reason_codes: Optional[List[str]] = None, action: Optional[str] = None,
                context: Optional[Dict[str, Any]] = None,
                transition_from_role: Optional[str] = None) -> Dict[str, Any]:
    data = {
        "schema": ROUTE_SCHEMA,
        "task_id": task.get("task_id"),
        "current_state": task.get("current_state"),
        "current_phase": task.get("current_stage"),
        "effective_level": level,
        "next_stage": next_stage,
        "role_id": role_id,
        "skill_path": skill_path,
        "execution_mode": execution_mode,
        "confirmation_required": bool(confirmation_required),
        "confirmation_reason": confirmation_reason,
        "blocker": blocker,
        "recommended_action": action,
        "reason_codes": reason_codes or [],
        "risk_escalation_signals": list(task.get("_risk_escalation_signals") or []),
    }
    if context is not None:
        data["context"] = context
    if transition_from_role and role_id and transition_from_role != role_id:
        data["transition_from_role"] = transition_from_role
        data["transition_notice_required"] = True
    return data


def resolve_route(task_id: str, *, db_path: Optional[str] = None,
                  base_root: Optional["str | Path"] = None,
                  confirmation_policy: Optional[str] = None) -> Dict[str, Any]:
    root = _root(base_root)
    contract = load_contract(root)
    catalog = load_role_catalog(root)
    task, events = _load_task_facts(task_id, db_path)
    if str(task.get("base_version") or "") != active_version(root):
        raise OrchestrationError(
            f"task contract {task.get('base_version')!r} != active {active_version(root)!r}; migrate first"
        )
    state = str(task.get("current_state") or "")
    if state not in PUBLIC_STATES:
        raise OrchestrationError(f"unknown public state: {state!r}")
    level = resolve_effective_level(task.get("risk_level"), task.get("flow_level"))
    project_root = str(task.get("project_root_path") or "").strip()
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
                           reason_codes=["TASK_TERMINAL"], action="none")
    if state == "BLOCKED":
        blocker = next((str(e.get("summary") or "") for e in reversed(events) if e.get("event_type") == "BLOCKER"), "task is BLOCKED")
        return _route_dict(task, level, next_stage=None, role_id=None, skill_path=None,
                           blocker=blocker, reason_codes=["TASK_BLOCKED"], action="task_resume_after_resolution")

    review = _latest_arch_review(events)
    if review and review["decision"] in {"REVISE", "BLOCKED"}:
        architecture_after_review = _stage_completion_event("architecture", events)
        if not architecture_after_review or int(architecture_after_review.get("id") or 0) <= int(review["event"].get("id") or 0):
            role = role_map["tp-architecture-design"]
            code = "ARCHITECTURE_REVIEW_REVISE" if review["decision"] == "REVISE" else "ARCHITECTURE_REVIEW_BLOCKED_REWORK"
            mode = "COMPARATIVE" if "workflow:multiple-feasible-routes" in signals else "DIRECT"
            return _route_dict(task, level, next_stage="architecture", role_id="tp-architecture-design",
                               skill_path=str(role["skill_path"]), execution_mode=mode, reason_codes=[code],
                               transition_from_role="tp-architecture-review")

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
                "requirement": "tp-requirement-analysis",
                "architecture": "tp-architecture-design",
                "development": "tp-development-engineering",
            }
            rid = stage_to_role[target]
            mode = "COMPARATIVE" if target == "architecture" and "workflow:multiple-feasible-routes" in signals else "DIRECT"
            return _route_dict(task, level, next_stage=target, role_id=rid, skill_path=str(role_map[rid]["skill_path"]),
                               execution_mode=mode, reason_codes=[code],
                               transition_from_role="tp-verification-engineering")

    pipeline = (contract.get("pipelines") or {}).get(level) or []
    included = [s for s in pipeline if _stage_included(s, level, task, events, signals)]
    upstream_completion_id = 0
    previous_role: Optional[str] = None
    for step in included:
        stage = str(step["stage"])
        completion = _stage_completion_event(stage, events)
        if completion is not None and int(completion.get("id") or 0) > upstream_completion_id:
            upstream_completion_id = int(completion.get("id") or 0)
            previous_role = str(step.get("role") or "") or None
            continue
        rid = str(step["role"])
        role = role_map.get(rid)
        if role is None:
            raise OrchestrationError(f"pipeline references unknown role: {rid}")
        policy = confirmation_policy or str((contract.get("confirmation") or {}).get("default_policy") or "material")
        confirm = False
        confirm_reason = None
        if policy == "each_stage":
            confirm = bool(events)
            confirm_reason = "EACH_STAGE_POLICY" if confirm else None
        elif policy == "material" and stage == "development" and level in {"L2", "L3"} and _stage_done("architecture", events):
            marker = "workflow:material-confirmed:architecture->development"
            # A confirmation from an older architecture/review cycle is stale.
            # Require the durable marker to be newer than the current upstream
            # decision-complete stage; same-session confirmations remain ephemeral.
            if int(signal_ids.get(marker, 0)) <= upstream_completion_id:
                confirm = True
                confirm_reason = "MATERIAL_ARCHITECTURE_TO_IMPLEMENTATION"
        skill_path = str(role["skill_path"])
        action = "dispatch_role"
        if confirm and str(confirm_reason or "").startswith("MATERIAL_"):
            skill_path = None
            action = "await_confirmation"
        return _route_dict(
            task, level, next_stage=stage, role_id=rid, skill_path=skill_path,
            execution_mode=_execution_mode(step, level, signals), confirmation_required=confirm,
            confirmation_reason=confirm_reason, reason_codes=["NEXT_STAGE_RESOLVED"], action=action,
            context=_delivery_fact_pack(task, events) if stage == "delivery" else None,
            transition_from_role=previous_role,
        )

    # All selected stages have completed. A truthful PASS means the task may close;
    # lack of a required verification step above would have returned that step.
    return _route_dict(task, level, next_stage="complete", role_id=None, skill_path=None,
                       reason_codes=["PIPELINE_COMPLETE"], action="task_complete")
