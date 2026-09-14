# -*- coding: utf-8 -*-
"""V5.3.3 deterministic, read-only workflow orchestration.

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
from . import orchestration_policy
from . import db as dbmod
from . import delivery_contract
from . import environment
from . import risk_signals
from . import event_contract
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
    data = config_loader.load_config(
        "governance/orchestration.yaml",
        schema_name="orchestration",
        base_root=base_root,
        strict_unknown_fields=True,
        use_cache=True,
    )

    orchestration_policy.validate(data, load_role_catalog(base_root))
    return data


def load_role_catalog(base_root: Optional["str | Path"] = None) -> Dict[str, Any]:
    return config_loader.load_config(
        "governance/role-catalog.yaml",
        schema_name="role-catalog",
        base_root=base_root,
        strict_unknown_fields=True,
        use_cache=True,
    )


def load_role_topology(base_root: Optional["str | Path"] = None) -> Dict[str, Any]:
    """Return the persisted generated Agent/Role/Skill topology projection.

    Runtime consumers read the catalog projection directly; they do not rescan
    Skill files or rebuild relationships on demand.
    """
    topology = load_role_catalog(base_root).get("topology")
    if not isinstance(topology, dict):
        raise OrchestrationError("role catalog topology is missing or invalid")
    nodes = topology.get("nodes")
    edges = topology.get("edges")
    if not isinstance(nodes, dict) or not isinstance(edges, list):
        raise OrchestrationError("role catalog topology nodes/edges are invalid")
    return topology


def get_role_topology_node(node_id: str, *, base_root: Optional["str | Path"] = None) -> Optional[Dict[str, Any]]:
    topology = load_role_topology(base_root)
    node = (topology.get("nodes") or {}).get(str(node_id or ""))
    return dict(node) if isinstance(node, dict) else None


def search_role_topology(query: str, *, base_root: Optional["str | Path"] = None, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search topology nodes by stable id or display name.

    Exact id/name matches win; otherwise a case-insensitive substring match is
    used. The search only reads the generated catalog projection.
    """
    needle = str(query or "").strip().casefold()
    if not needle:
        return []
    nodes = load_role_topology(base_root).get("nodes") or {}
    rows = [
        dict(node) for node in nodes.values()
        if isinstance(node, dict) and (kind is None or str(node.get("kind") or "") == kind)
    ]

    def exact(row: Dict[str, Any]) -> bool:
        return needle in {str(row.get("id") or "").casefold(), str(row.get("name") or "").casefold()}

    exact_rows = [row for row in rows if exact(row)]
    if exact_rows:
        return exact_rows
    return [
        row for row in rows
        if needle in str(row.get("id") or "").casefold()
        or needle in str(row.get("name") or "").casefold()
    ]


def _display_entry(mapping: Any, key: str) -> Dict[str, Any]:
    if not key:
        return {"label": "", "description": "", "configured": True}
    item = mapping.get(key) if isinstance(mapping, dict) else None
    if isinstance(item, dict) and str(item.get("label") or "").strip():
        return {
            "label": str(item.get("label") or "").strip(),
            "description": str(item.get("description") or "").strip(),
            "configured": True,
        }
    return {"label": "未配置展示名称", "description": "", "configured": False}


def _role_display(role_map: Dict[str, Dict[str, Any]], role_id: str) -> Dict[str, Any]:
    if not role_id:
        return {"label": "", "description": "", "configured": True}
    role = role_map.get(role_id)
    if isinstance(role, dict) and str(role.get("display_name") or "").strip():
        return {"label": str(role.get("display_name") or "").strip(), "description": "", "configured": True}
    return {"label": "未配置展示名称", "description": "", "configured": False}


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
        errors.append("planning/review must prefer isolated parallel subagents")
    if contract.get("execution", {}).get("sequential_isolation_fallback") is not True:
        errors.append("orchestration must retain isolated sequential fallback")
    delivery_fast = (contract.get("execution") or {}).get("delivery_fast_path") or {}
    if not 1 <= int(delivery_fast.get("max_incremental_ai_overhead_percent") or -1) <= 5:
        errors.append("delivery fast-path AI overhead budget must be within 1..5 percent")
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
        strict_unknown_fields=True, use_cache=True,
    )
    phases = set(((workflow.get("rules") or {}).get("phases") or {}).get("values") or [])

    lifecycle_path = root / "governance" / "lifecycle.md"
    try:
        lifecycle_text = lifecycle_path.read_text(encoding="utf-8-sig")
        phase_line = next(
            (line for line in lifecycle_text.splitlines() if "`current_phase`" in line and "记录" in line),
            "",
        )
        declared_lifecycle_phases: set[str] = set()
        for group in re.findall(r"`([^`]+)`", phase_line):
            if group == "current_phase":
                continue
            declared_lifecycle_phases.update(
                value.strip() for value in group.split("/") if value.strip()
            )
        missing_lifecycle_phases = sorted(phases - declared_lifecycle_phases)
        if missing_lifecycle_phases:
            errors.append(
                "lifecycle.md missing workflow phases: " + ", ".join(missing_lifecycle_phases)
            )
    except Exception as exc:
        errors.append(f"lifecycle.md phase declaration: {exc}")

    for rule in contract.get("conditional_roles") or []:
        if not isinstance(rule, dict):
            continue
        role_id = str(rule.get("role") or "")
        role = roles.get(role_id)
        if role is None:
            continue
        catalog_phases = {str(value) for value in (role.get("phases") or [])}
        for phase in (str(value) for value in (rule.get("phases") or [])):
            if phase not in catalog_phases:
                errors.append(
                    f"{role_id}: conditional orchestration phase {phase!r} not declared in role catalog phases"
                )
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


def _load_task_facts(task_id: str, db_path: Optional[str] = None, *, include_progress: bool = False) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    path = dbmod.resolve_db_path(db_path, task_id=task_id)
    if not Path(path).is_file():
        raise OrchestrationError(f"database not found: {path}")
    conn = dbmod.connect_readonly(path)
    try:
        conn.execute("BEGIN")
        row = conn.execute(
            "SELECT t.*, p.root_path AS project_root_path FROM task t "
            "LEFT JOIN project p ON p.project_id=t.project_id WHERE t.task_id=?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise OrchestrationError(f"task not found: {task_id}")
        events = conn.execute(
            "SELECT id,task_id,event_type,from_state,to_state,from_stage,to_stage,actor_role,actor_agent,model_used,work_item_id,reason_code,summary,detail_json,workflow_version,created_at "
            "FROM task_event WHERE task_id=? ORDER BY id", (task_id,),
        ).fetchall()
        task, facts = dict(row), [dict(e) for e in events]
        task["_orchestration_overrides"] = orchestration_policy.read_rows(conn)
        from . import event_policies
        task["_retired"] = event_policies.is_task_retired(conn, task_id)
        if include_progress:
            from .report_cmd import task_progress_facts
            task["_progress_facts"] = task_progress_facts(conn, task, events=facts, retired=task["_retired"])
        project_root = str(task.get("project_root_path") or "").strip()
        task_dir = Path(project_root) / ".tp-spec" / "tasks" / task_id if project_root else None
        from . import event_policies
        if task_dir is not None:
            task["_owner_acceptance"] = event_policies.effective_owner_acceptance(
                conn, task_id, task_dir=task_dir,
            )
        if not task["_retired"] and task.get("current_state") in {"NEW", "ACTIVE"}:
            from . import waiting
            task["_result_wait"] = waiting.result_wait(conn, task_id, facts, task_dir=task_dir)
            if task_dir is not None:
                current = event_policies.load_current_verification(conn, task_id, task_dir)
                task["_current_verification"] = ({**current.detail, "event_id": int(current.row["id"])}
                                                 if current else {})
                task["_current_code_review"] = {}
                if current:
                    from .workflow_records import _latest_trusted_code_review
                    try:
                        reviewed = _latest_trusted_code_review(
                            conn, task_id, task_dir=task_dir,
                            subject_digest=str(current.detail.get("subject_digest") or ""),
                            change_set_id=str(current.detail.get("change_set_id") or ""),
                            verification_event_id=int(current.row["id"]),
                        )
                    except ValueError:
                        pass  # No usable current review: route its prerequisite, not delivery.
                    else:
                        task["_current_code_review"] = {"event_id": int(reviewed.row["id"])}
        return task, facts
    finally:
        conn.close()


def _decision_signal_ids(events: Iterable[Dict[str, Any]], contract: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    """Return explicit machine workflow signals only.

    Historical DECISION summaries remain readable audit text but never drive
    routing. New producers must write ``detail_json.signal`` or ``signals``.
    """
    result: Dict[str, int] = {}
    for e in events:
        if str(e.get("event_type") or "").upper() != "DECISION" or str(e.get("actor_role") or "") != "human_owner":
            continue
        detail = _parse_detail(e.get("detail_json"))
        values = []
        signal = str(detail.get("signal") or "").strip()
        if signal:
            values.append(signal)
        for raw in detail.get("signals") or []:
            value = str(raw or "").strip()
            if value:
                values.append(value)
        for value in values:
            if contract is not None:
                value = orchestration_policy.normalize_signal(value, contract["signals"])
            result[value] = max(result.get(value, 0), int(e.get("id") or 0))
    return result


def _decision_signals(events: Iterable[Dict[str, Any]], contract: Optional[Dict[str, Any]] = None) -> set[str]:
    return set(_decision_signal_ids(events, contract))


def _latest_verification(events: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for e in reversed(list(events)):
        if e.get("event_type") != "VERIFICATION_COMPLETED" or e.get("actor_role") != "tp-test-engineer":
            continue
        d = _parse_detail(e.get("detail_json"))
        decision = event_contract.normalize_event_semantics(str(e.get("event_type") or ""), d)["decision"]
        return {"decision": decision, "detail": d, "event": e}
    return None


def _latest_arch_review(events: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for e in reversed(list(events)):
        if e.get("event_type") != "REVIEW_COMPLETED" or e.get("actor_role") != "tp-software-architect":
            continue
        d = _parse_detail(e.get("detail_json"))
        if str(d.get("review_kind") or "").upper() != "ARCHITECTURE":
            continue
        decision = event_contract.normalize_event_semantics(str(e.get("event_type") or ""), d)["decision"]
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
        decision = event_contract.normalize_event_semantics(str(e.get("event_type") or ""), d)["decision"]
        return {"decision": decision, "detail": d, "event": e}
    return None


def _latest_checkpoint_activity(events: Iterable[Dict[str, Any]], *, actor: str, phase: str) -> Optional[Dict[str, Any]]:
    for e in reversed(list(events)):
        if e.get("event_type") != "FACT" or e.get("actor_role") != actor:
            continue
        d = _parse_detail(e.get("detail_json"))
        if str(d.get("operation") or "").upper() == "CHECKPOINT" and str(d.get("phase") or e.get("to_stage") or "") == phase:
            return {"event": e, "detail": d, "semantics": event_contract.normalize_event_semantics("FACT", d)}
    return None


def _latest_checkpoint(events: Iterable[Dict[str, Any]], *, actor: str, phase: str) -> Optional[Dict[str, Any]]:
    activity = _latest_checkpoint_activity(events, actor=actor, phase=phase)
    if activity and activity["semantics"]["result_status"] == "COMPLETED":
        return activity["event"]
    return None


def _development_change_set_binding(events: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    activity = _latest_checkpoint_activity(events, actor="tp-development-engineer", phase="development")
    if not activity or activity["semantics"]["result_status"] != "COMPLETED":
        return None
    detail = activity["detail"]
    change_set_id = str(detail.get("change_set_id") or "").strip()
    repo_roots = [str(value).strip() for value in (detail.get("repo_roots") or []) if str(value).strip()]
    if not repo_roots:
        for repo in ((detail.get("change_set") or {}).get("repositories") or []):
            if isinstance(repo, dict) and str(repo.get("root_locator") or "").strip():
                repo_roots.append(str(repo["root_locator"]).strip())
    return {
        "event": activity["event"],
        "detail": detail,
        "change_set_id": change_set_id,
        "repo_roots": repo_roots,
    }


def _current_bound_change_set(binding: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not binding.get("change_set_id") or not binding.get("repo_roots"):
        return None
    from .change_set import capture_change_set
    return capture_change_set(binding["repo_roots"])


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
    mapping = {
        "requirement": ("tp-product-manager", "requirement"),
        "product": ("tp-product-manager", "product"),
        "architecture": ("tp-software-architect", "architecture"),
        "planning": ("tp-tech-lead", "planning"),
        "development": ("tp-development-engineer", "development"),
    }
    if stage in mapping:
        actor, phase = mapping[stage]
        return _latest_checkpoint_activity(events, actor=actor, phase=phase) is not None
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
        if stage in orchestration_policy.protected_stages(level):
            raise OrchestrationError(f"PROTECTED_STAGE: {level}.{stage} cannot be skipped by a routing signal")
        if include in signals:
            raise OrchestrationError(f"CONFLICTING_STAGE_SIGNALS: {stage}")
        return False
    if step["required"] or include in signals or _stage_has_activity(stage, events):
        return True
    if stage == str(step.get("phase") or "") and str(task.get("current_stage") or "") == stage:
        return True
    trigger = step.get("trigger")
    if trigger == "unresolved_scope":
        # 无范围事实的新工作需要澄清；已有下游工作不要求倒补虚构前置事件。
        return not any(_stage_has_activity(name, events) for name in
                       ("requirement", "architecture", "planning", "development", "verification", "review"))
    if trigger == "architecture_risk":
        return bool(task.get("_risk_signals") or signals & {
            "workflow:security-risk", "workflow:database-risk", "workflow:multiple-feasible-routes"})
    if trigger == "behavioral_change":
        snapshot = task.get("_current_change_set") or {}
        empty_patch = "sha256:" + hashlib.sha256(b"").hexdigest()
        changed = any(repo.get("untracked") or repo.get("tracked_patch_sha256") not in {None, empty_patch}
                      for repo in snapshot.get("repositories", []))
        return "workflow:behavioral-change" in signals or changed
    if trigger == "deep_review":
        return "workflow:deep-review" in signals
    if trigger == "contextual" and stage == "planning":
        development = _stage_completion_event("development", events) or {}
        return _reassessment_id(events) > int(development.get("id") or 0)
    return False


def _reassessment_id(events: List[Dict[str, Any]]) -> int:
    """真实上游返修才使旧实现重评，普通新备注不等于需要重做。

    工件和 ChangeSet 的新鲜度仍由原有独立校验保护。
    """
    latest = 0
    failed_verification = 0
    for event in events:
        detail = _parse_detail(event.get("detail_json"))
        if event.get("event_type") == "VERIFICATION_COMPLETED" and event.get("actor_role") == "tp-test-engineer":
            decision = event_contract.normalize_event_semantics("VERIFICATION_COMPLETED", detail)["decision"]
            failed_verification = int(event["id"]) if decision == "FAIL" else 0
        # 已失败验证之后的真实需求/架构重评不能被当成普通备注跳过。
        if failed_verification:
            for stage in ("requirement", "architecture"):
                completion = _stage_completion_event(stage, [event])
                if completion is not None:
                    latest = max(latest, failed_verification)
        if (event.get("event_type") == "REVIEW_COMPLETED"
                and event.get("actor_role") == "tp-software-architect"
                and detail.get("review_kind") == "ARCHITECTURE"
                and event_contract.normalize_event_semantics("REVIEW_COMPLETED", detail)["decision"] in {"REVISE", "FAIL", "NEEDS_FIX"}):
            latest = max(latest, int(event["id"]))
    return latest


def _current_verification_for_delivery(events: List[Dict[str, Any]], task_dir: Optional[Path]) -> Optional[Dict[str, Any]]:
    verification = _latest_verification(events)
    if (not verification or verification["decision"] != "PASS"
            or verification["detail"].get("verification_scope", "full") != "full"):
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
        current_subject_digest=subject_digest, task_dir=task_dir,
    )


def _knowledge_request_for_delivery(events: List[Dict[str, Any]], delivery_event: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if delivery_event is None:
        return None
    delivery_id = int(delivery_event.get("id") or 0)
    for event in reversed(events):
        detail = workflow_controls.trusted_event_detail(
            event,
            event_type="KNOWLEDGE_CONVERGENCE_REQUEST",
            producer="delivery_converge",
            actor="tp-integration-engineer",
        )
        if detail is None:
            continue
        try:
            if int(detail.get("delivery_event_id") or 0) != delivery_id:
                continue
        except (TypeError, ValueError):
            continue
        if not isinstance(detail.get("trigger_reason_codes"), list) or not detail.get("trigger_reason_codes"):
            continue
        if str(detail.get("search_scope") or "") != "project+shared":
            continue
        if not isinstance(detail.get("source_refs"), list) or not detail.get("source_refs"):
            continue
        return {"event": event, "detail": detail}
    return None


def _knowledge_result_sources_current(detail: Dict[str, Any], task_dir: Optional[Path]) -> bool:
    if task_dir is None:
        return False
    refs = {str(x or "").replace("\\", "/").strip() for x in (detail.get("source_refs") or []) if str(x or "").strip()}
    items = detail.get("source_items")
    if not refs or not isinstance(items, list) or not items:
        return False
    from .evidence import validate_evidence_path
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            return False
        path = str(item.get("path") or "").replace("\\", "/").strip()
        if not path or path not in refs:
            return False
        checked = validate_evidence_path(task_dir, item, require_evidence_dir=False)
        if not checked.ok or str(item.get("sha256") or "") != str(checked.sha256 or ""):
            return False
        seen.add(path)
    return seen == refs


def _knowledge_result_for_request(events: List[Dict[str, Any]], request: Dict[str, Any],
                                  task_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    request_event = request["event"]
    request_detail = request["detail"]
    request_id = int(request_event.get("id") or 0)
    change_set_id = str(request_detail.get("change_set_id") or "")
    allowed = {"CREATED", "UPDATED", "DUPLICATE", "NO_DURABLE_INSIGHT"}
    for event in reversed(events):
        detail = workflow_controls.trusted_event_detail(
            event,
            event_type="KNOWLEDGE_CONVERGENCE_RESULT",
            producer="knowledge_task_converge",
            actor="tp-knowledge",
        )
        if detail is None:
            continue
        try:
            if int(detail.get("request_event_id") or 0) != request_id:
                continue
        except (TypeError, ValueError):
            continue
        if str(detail.get("change_set_id") or "") != change_set_id:
            continue
        disposition = str(detail.get("knowledge_disposition") or "").upper()
        if disposition not in allowed:
            continue
        receipts = detail.get("query_receipts")
        if not isinstance(receipts, list) or not receipts:
            continue
        if any(delivery_contract.validate_receipt_payload("search", receipt) for receipt in receipts):
            continue
        if not isinstance(detail.get("source_refs"), list) or not detail.get("source_refs"):
            continue
        if not _knowledge_result_sources_current(detail, task_dir):
            continue
        if not str(detail.get("reason_code") or "").strip():
            continue
        knowledge_ref = str(detail.get("knowledge_ref") or "").strip()
        if disposition in {"CREATED", "UPDATED"} and not knowledge_ref:
            continue
        if disposition == "DUPLICATE":
            matched = {
                str(ref or "").strip()
                for receipt in receipts
                for ref in (receipt.get("matched_canonical_refs") or [])
                if str(ref or "").strip()
            }
            if not knowledge_ref or knowledge_ref not in matched:
                continue
        return {"event": event, "detail": detail}
    return None


def _delivery_fact_pack(task: Dict[str, Any], events: List[Dict[str, Any]], contract: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
                "decision": event_contract.normalize_event_semantics("VERIFICATION_COMPLETED", detail)["decision"],
            }
    return {
        "mode": "FAST_PATH",
        "max_incremental_ai_overhead_percent": (contract or load_contract())["execution"]["delivery_fast_path"]["max_incremental_ai_overhead_percent"],
        "task": {
            "task_id": task.get("task_id"),
            "risk_level": task.get("risk_level"),
            "flow_level": task.get("flow_level"),
        },
        "stage_facts": facts,
        "knowledge_signals": knowledge_signals,
        "delivery_signals": delivery_signals,
        "verification_binding": verification_binding,
        "knowledge_effect": {
            "scope": "current project + shared",
            "request_when_signals_present": True,
            "result_owner": "tp-knowledge",
            "result_dispositions": ["CREATED", "UPDATED", "DUPLICATE", "NO_DURABLE_INSIGHT"],
            "integration_writes_result": False,
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
        "dispatch_effect": "DISPATCH_EFFECT",
        "await_confirmation": "AWAIT_CONFIRMATION",
        "await_effect_approval": "BOUNDARY_REACHED",
        "task_complete": "TASK_COMPLETE",
        "none": "NONE",
        "task_resume_after_resolution": "TASK_BLOCKED",
    }.get(str(action or ""), "NO_ACTION")


def _validation_advice(task: Dict[str, Any]) -> Dict[str, Any]:
    """Bounded inputs for impact selection, never a test result or authorization.

    Reuse the captured product subject. Git paths and declared AC methods narrow
    the investigation; they do not prove callers, coverage or server deployment.
    """
    snapshot = task.get("_current_change_set") or {}
    changed: List[Dict[str, Any]] = []
    paths_status = "unavailable" if not snapshot else "observed"
    from .change_set import _run_git, _nul_paths, _is_product_path, ChangeSetError
    for repo in snapshot.get("repositories", []):
        root = Path(repo["root_locator"])
        try:
            raw = _run_git(root, "diff", "--no-ext-diff", "--no-textconv", "--name-only", "--no-renames", "-z", "HEAD", "--", ".", text=False)
            paths = set(_nul_paths(raw)) | {str(row["path"]) for row in repo.get("untracked", [])}
            changed.extend({"repo_root": str(root), "path": path} for path in sorted(paths) if _is_product_path(path))
        except (OSError, ChangeSetError):
            paths_status = "unavailable"
    candidates = []
    task_dir = task.get("_task_dir")
    if task_dir is not None:
        path = task_dir / "acceptance.md"
        if path.is_file():
            from .task_cmd import _acceptance_table_rows
            for aid, row in _acceptance_table_rows(path.read_text(encoding="utf-8-sig")).items():
                candidates.append({"id": aid, "method": row["cells"][5].strip(),
                                   "witness": row["witness"], "declared_verdict": row["verdict"]})
    return {
        "scope": "affected", "coverage_complete": False, "authorization_granted": False,
        "verification_scope": "technical" if task.get("_full_repository_scope") is False else "full",
        "change_set_id": snapshot.get("content_digest"),
        "diff_basis": "each bound repository HEAD to current worktree; not the complete task history",
        "changed_paths_status": paths_status,
        "changed_files": changed[:64], "changed_file_count": len(changed),
        "acceptance_source": "acceptance.md", "acceptance_candidates": candidates[:12],
        "acceptance_candidate_count": len(candidates),
        "effective_owner_acceptance": {
            "accepted_acs": list((task.get("_owner_acceptance") or {}).get("accepted_acs") or []),
            "visual_acs": list((task.get("_owner_acceptance") or {}).get("visual_acs") or []),
        },
        "usage_mapping": "requires_actual_callers", "risk_signals": task.get("_risk_signals", []),
        "instructions": "先复用相关测试，核对实际调用方/当前AC/风险再选检查；不按Diff行数降风险。候选不是必跑清单；未确定影响不默认全量。编译、浏览器和副作用沿用既有授权，未运行不记PASS。",
    }


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
        "recommended_roles": recommended_roles if recommended_roles is not None else (task.get("_role_recommendations") or {}).get(next_stage, []),
        "policy_sources": task.get("_policy_sources", {}),
        "risk_signals": list(task.get("_risk_signals", [])),
        "recommended_skills": sorted({str(x) for x in (recommended_skills or []) if str(x)}),
    }
    contract = task.get("_effective_contract")
    if contract is not None:
        data["included_stages"] = [step["stage"] for step in contract["pipelines"][level]
            if _stage_included(step, level, task, task["_events"], task["_signals"])]
    if action in {"dispatch_role", "task_complete"} and task.get("_task_dir") is not None:
        context = dict(context or {})
        context["validation"] = _validation_advice(task)
        if action == "dispatch_role" and next_stage in {"development", "verification", "review"}:
            data["recommended_skills"] = sorted(set(data["recommended_skills"]) | {"testing-strategy"})
    if allowed is not None:
        data["allowed_effects"] = allowed
    if task.get("_current_effective", {}).get("status", "ABSENT") != "ABSENT":
        context = dict(context or {})
        context["current_effective"] = task["_current_effective"]
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
    # 返修早返回与常规流水段使用同一执行边界；角色名不授予写权限。
    required_effects = list(required_effects) if required_effects is not None else (["repo_mutation"] if next_stage == "development" else [])
    if allowed_effects is not None:
        missing = sorted(set(required_effects) - set(allowed_effects))
        if missing:
            return _route_dict(
                task, level, next_stage=next_stage, role_id=None, skill_path=None,
                execution_mode=execution_mode, reason_codes=["EXECUTION_BOUNDARY_REACHED"],
                action="await_effect_approval", context=context, transition_from_role=source_role,
                confirmation_policy=policy, required_effects=missing, allowed_effects=allowed_effects,
                decision_reason="effect_not_allowed", recommended_roles=recommended_roles,
            )
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
    contract = orchestration_policy.resolve(contract, catalog, task["_orchestration_overrides"],
                                            project_id=str(task["project_id"]), task_id=task_id)
    task["_policy_sources"] = contract["_policy_sources"]
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
    task["_task_dir"] = task_dir
    from . import current_context
    task["_current_effective"] = current_context.read_current(task_dir, task_id=task_id)
    task["_risk_signals"] = list(risk_scan.get("signals") or [])
    role_map = {str(r["workflow_role"]): r for r in catalog.get("roles") or []}
    signal_ids = _decision_signal_ids(events, contract)
    signals = set(signal_ids)
    task["_effective_contract"], task["_events"], task["_signals"] = contract, events, signals
    task["_role_recommendations"] = {
        stage: _conditional_role_recommendations(contract, catalog, phase=phase,
                 signals=signals, risk_signals=task["_risk_signals"])
        for stage, (_, phase) in orchestration_policy.STAGES.items()
    }

    if task.get("_retired"):
        return _route_dict(task, level, next_stage=None, role_id=None, skill_path=None,
                           reason_codes=["TASK_RETIRED"], action="none", confirmation_policy=policy)
    if state in TERMINAL:
        return _route_dict(task, level, next_stage=None, role_id=None, skill_path=None,
                           reason_codes=["TASK_TERMINAL"], action="none", confirmation_policy=policy)
    if state == "BLOCKED":
        blocker = next((str(e.get("summary") or "") for e in reversed(events) if e.get("event_type") == "BLOCKER"), "task is BLOCKED")
        from .waiting import active_wait
        waiting_fact = active_wait(events, state)
        result = _route_dict(task, level, next_stage=None, role_id=None, skill_path=None,
                           blocker=blocker, reason_codes=["TASK_BLOCKED"], action="task_resume_after_resolution",
                           confirmation_policy=policy, context={"waiting": waiting_fact} if waiting_fact else None)
        if waiting_fact:
            result["next_responsibility"] = waiting_fact["responsibility"]
            result["requires_human"] = waiting_fact["responsibility"] == "human_owner"
        return result

    pending_wait = task.get("_result_wait") or {}
    if pending_wait:
        result = _route_dict(
            task, level, next_stage=pending_wait["source_stage"], role_id=None, skill_path=None,
            blocker=pending_wait["reason"], reason_codes=[pending_wait["reason_code"]],
            action="none", confirmation_policy=policy, context={"waiting": pending_wait},
            decision_reason="prerequisite_unchanged",
        )
        result["next_responsibility"] = pending_wait["responsibility"]
        result["requires_human"] = pending_wait["responsibility"] == "human_owner"
        return result

    if task["_current_effective"]["status"] in current_context.UNUSABLE:
        result = _route_dict(
            task, level, next_stage=None, role_id=None, skill_path=None,
            action="none", reason_codes=["CURRENT_CONTEXT_UNRESOLVED"],
            blocker=current_context.RECOVERY, confirmation_policy=policy,
            decision_reason="current_context_unresolved",
        )
        result["next_responsibility"] = "tp-software-lifecycle"
        return result

    review = _latest_arch_review(events)
    if review and review["decision"] == "REVISE":
        architecture_after_review = _stage_completion_event("architecture", events)
        if not architecture_after_review or int(architecture_after_review.get("id") or 0) <= int(review["event"].get("id") or 0):
            role = role_map["tp-software-architect"]
            code = "ARCHITECTURE_REVIEW_REVISE"
            mode = "COMPARATIVE" if "workflow:multiple-feasible-routes" in signals else "DIRECT"
            return _route_role_boundary(
                task, level, events, policy=policy, next_stage="architecture",
                role_id="tp-software-architect", skill_path=str(role["skill_path"]),
                execution_mode=mode, reason_codes=[code], source_event=review["event"],
                source_stage="architecture_review", source_role="tp-software-architect",
            )

    code_review = _latest_code_review(events)
    if code_review and code_review["decision"] in {"NEEDS_FIX", "REVISE", "FAIL"}:
        development_after_review = _stage_completion_event("development", events)
        if not development_after_review or int(development_after_review.get("id") or 0) <= int(code_review["event"].get("id") or 0):
            return _route_role_boundary(
                task, level, events, policy=policy, next_stage="development",
                role_id="tp-development-engineer",
                skill_path=str(role_map["tp-development-engineer"]["skill_path"]),
                execution_mode="DIRECT", reason_codes=["CODE_REVIEW_REWORK"],
                source_event=code_review["event"], source_stage="review", source_role="tp-code-reviewer",
                required_effects=["repo_mutation"], allowed_effects=allowed_set,
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
                allowed_effects=allowed_set,
            )

    development_activity = _latest_checkpoint_activity(
        events, actor="tp-development-engineer", phase="development"
    )
    if development_activity and development_activity["semantics"]["result_status"] == "COMPLETED":
        legacy_change_set = str(development_activity["detail"].get("change_set_id") or "").strip()
        if not legacy_change_set:
            return _route_role_boundary(
                task, level, events, policy=policy, next_stage="development",
                role_id="tp-development-engineer",
                skill_path=str(role_map["tp-development-engineer"]["skill_path"]),
                execution_mode="DIRECT", reason_codes=["CHANGE_SET_REQUIRED"],
                source_event=development_activity["event"], source_stage="development",
                source_role="tp-development-engineer", required_effects=["repo_mutation"],
                allowed_effects=allowed_set,
            )

    current_verification_required = False
    current_review_required = False
    development_binding = _development_change_set_binding(events)
    # Final scope checks also run for legacy bindings without repository locators.
    known_scope = delivery_contract.repository_scope(events)
    if development_binding and development_binding.get("change_set_id") and development_binding.get("repo_roots"):
        if int(development_binding["event"]["id"]) <= known_scope["scope_event_id"]:
            return _full_repository_scope_wait(task, level, policy)
        try:
            current_change_set = _current_bound_change_set(development_binding)
        except Exception as exc:
            raise OrchestrationError(f"CHANGE_SET_UNAVAILABLE: {exc}") from exc
        task["_current_change_set"] = current_change_set
        task["_full_repository_scope"] = delivery_contract.full_scope_matches(
            known_scope, development_binding["detail"],
            development_event_id=int(development_binding["event"]["id"]),
        )
        from .change_set import same_bound_product_content
        if current_change_set and not same_bound_product_content(development_binding["detail"], current_change_set):
            source = code_review["event"] if code_review else development_binding["event"]
            source_stage = "review" if code_review else "development"
            source_role = "tp-code-reviewer" if code_review else "tp-development-engineer"
            return _route_role_boundary(
                task, level, events, policy=policy, next_stage="development",
                role_id="tp-development-engineer",
                skill_path=str(role_map["tp-development-engineer"]["skill_path"]),
                execution_mode="DIRECT", reason_codes=["CHANGE_SET_STALE"],
                source_event=source, source_stage=source_stage, source_role=source_role,
                required_effects=["repo_mutation"], allowed_effects=allowed_set,
            )

        if current_change_set and task_dir is not None:
            # Reuse the same captured product subject. Routing must not repeatedly
            # dispatch review/delivery against a PASS their normal preflight rejects.
            current_pass = task.get("_current_verification") or {}
            current_verification_required = (
                current_pass.get("change_set_id") != current_change_set.get("content_digest")
                or not verification
                or current_pass.get("event_id") != int(verification["event"]["id"])
            )
            current_review_required = (
                not code_review or (task.get("_current_code_review") or {}).get("event_id")
                != int(code_review["event"]["id"])
            )

    pipeline = (contract.get("pipelines") or {}).get(level) or []
    included = [s for s in pipeline if _stage_included(s, level, task, events, signals)]
    upstream_completion_id = 0
    reassessment_id = _reassessment_id(events)
    previous_role: Optional[str] = None
    previous_stage: Optional[str] = None
    previous_completion: Optional[Dict[str, Any]] = None
    for step in included:
        stage = str(step["stage"])
        completion = _delivery_completion_event(events, task_dir) if stage == "delivery" else _stage_completion_event(stage, events)
        if ((stage == "verification" and current_verification_required)
                or (stage == "review" and current_review_required)):
            completion = None
        reusable_review = (stage == "review" and completion is not None
                           and (task.get("_current_code_review") or {}).get("event_id") == int(completion["id"]))
        if stage in {"verification", "review", "delivery"}:
            dependency_id = upstream_completion_id
        elif stage in {"architecture", "architecture_review", "planning", "development"}:
            dependency_id = reassessment_id
        else:
            dependency_id = 0
        if completion is not None and (int(completion.get("id") or 0) > dependency_id or reusable_review):
            if stage in {"development", "verification", "review", "delivery"}:
                upstream_completion_id = max(upstream_completion_id, int(completion.get("id") or 0))
            previous_role = str(step.get("role") or "") or None
            previous_stage = stage
            previous_completion = completion
            continue
        if stage == "delivery" and development_binding and not delivery_contract.full_scope_matches(
            known_scope, development_binding["detail"],
            development_event_id=int(development_binding["event"]["id"]),
        ):
            return _full_repository_scope_wait(task, level, policy)
        if stage == "delivery" and verification and verification["detail"].get("verification_scope") == "technical":
            return _full_verification_wait(task, level, policy)
        rid = str(step["role"])
        role = role_map.get(rid)
        if role is None:
            raise OrchestrationError(f"pipeline references unknown role: {rid}")
        mode = _execution_mode(step, level, signals)
        context = _delivery_fact_pack(task, events, contract) if stage == "delivery" else None
        recommended_roles = _conditional_role_recommendations(
            contract, catalog, phase=str(step.get("phase") or stage), signals=signals,
            risk_signals=task.get("_risk_signals") or [],
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
            reason_codes=["CURRENT_VERIFICATION_REQUIRED" if stage == "verification" and current_verification_required
                          else "NEXT_STAGE_RESOLVED"], source_event=previous_completion,
            source_stage=previous_stage, source_role=previous_role, context=context,
            human_confirmation_already_satisfied=material_satisfied,
            required_effects=step_effects, allowed_effects=allowed_set,
            recommended_roles=recommended_roles,
        )

    delivery_event = _delivery_completion_event(events, task_dir)
    knowledge_request = _knowledge_request_for_delivery(events, delivery_event)
    if knowledge_request is not None and _knowledge_result_for_request(events, knowledge_request, task_dir) is None:
        knowledge_role = role_map.get("tp-knowledge") or {}
        return _route_dict(
            task, level, next_stage="complete", role_id="tp-knowledge",
            skill_path=str(knowledge_role.get("skill_path") or "agents/tp-knowledge/SKILL.md"),
            execution_mode="DIRECT", reason_codes=["KNOWLEDGE_CONVERGENCE_REQUIRED"],
            action="dispatch_effect", confirmation_policy=policy,
            context={
                "request_event_id": int(knowledge_request["event"].get("id") or 0),
                "change_set_id": str(knowledge_request["detail"].get("change_set_id") or ""),
                "trigger_reason_codes": list(knowledge_request["detail"].get("trigger_reason_codes") or []),
                "search_scope": "project+shared",
                "source_refs": list(knowledge_request["detail"].get("source_refs") or []),
            },
        )

    if development_binding and not delivery_contract.full_scope_matches(
        known_scope, development_binding["detail"],
        development_event_id=int(development_binding["event"]["id"]),
    ):
        return _full_repository_scope_wait(task, level, policy)
    if verification and verification["detail"].get("verification_scope") == "technical":
        return _full_verification_wait(task, level, policy)
    return _route_dict(task, level, next_stage="complete", role_id=None, skill_path=None,
                       reason_codes=["PIPELINE_COMPLETE"], action="task_complete",
                       confirmation_policy=policy)


def _full_repository_scope_wait(task: Dict[str, Any], level: str, policy: str) -> Dict[str, Any]:
    reason = "当前开发记录仅覆盖局部仓库或早于有效范围决定，不能据此授予整任务PASS。"
    waiting = {"reason": reason, "reason_code": "FULL_SCOPE_CHECKPOINT_REQUIRED",
               "responsibility": "tp-software-lifecycle",
               "condition": "在已有授权内用默认development checkpoint绑定已登记完整范围，再按影响取得完整验收证据；不要求重做代码或自动全量回归。"}
    result = _route_dict(task, level, next_stage="verification", role_id=None, skill_path=None,
                        action="none", blocker=reason, reason_codes=["FULL_SCOPE_CHECKPOINT_REQUIRED"],
                        confirmation_policy=policy, context={"waiting": waiting})
    result["next_responsibility"] = waiting["responsibility"]
    return result


def _full_verification_wait(task: Dict[str, Any], level: str, policy: str) -> Dict[str, Any]:
    reason = "技术限定验证仅证明已列明检查；完整验证及必要视觉/人验尚未汇合。"
    waiting = {"reason": reason, "reason_code": "FULL_VERIFICATION_REQUIRED",
               "source_stage": "verification", "responsibility": "tp-test-engineer",
               "condition": "取得当前主体的完整验证证据及必要验收处置后，执行默认 task verify 并重新查询 workflow next。"}
    result = _route_dict(task, level, next_stage="verification", role_id=None, skill_path=None,
                        reason_codes=["FULL_VERIFICATION_REQUIRED"], action="none", blocker=reason,
                        context={"waiting": waiting}, confirmation_policy=policy)
    result["next_responsibility"] = "tp-test-engineer"
    return result


def resolve_progress(
    task_id: str,
    *,
    db_path: Optional[str] = None,
    base_root: Optional["str | Path"] = None,
) -> Dict[str, Any]:
    """Return display-oriented workflow progress from the same orchestration facts.

    This is a read-only projection for presentation surfaces.  It deliberately
    reuses the active pipeline inclusion/completion helpers and ``resolve_route``
    rather than introducing a second workflow state machine.
    """
    root = _root(base_root)
    contract = load_contract(root)
    catalog = load_role_catalog(root)
    presentation = contract.get("presentation") or {}
    stage_presentation = presentation.get("stages") or {}
    action_presentation = presentation.get("actions") or {}
    confirmation_presentation = presentation.get("confirmations") or {}
    role_map = {
        str(item.get("workflow_role") or ""): item
        for item in (catalog.get("roles") or [])
        if isinstance(item, dict) and item.get("workflow_role")
    }
    task, events = _load_task_facts(task_id, db_path, include_progress=True)
    contract = orchestration_policy.resolve(contract, catalog, task["_orchestration_overrides"],
                                            project_id=str(task["project_id"]), task_id=task_id)
    route = resolve_route(task_id, db_path=db_path, base_root=root)
    task["_risk_signals"] = route.get("risk_signals", [])
    level = str(route.get("effective_level") or resolve_effective_level(task.get("risk_level"), task.get("flow_level")))
    signals = _decision_signals(events, contract)
    pipeline = (contract.get("pipelines") or {}).get(level) or []
    selected = route.get("included_stages")
    included = [step for step in pipeline if (step["stage"] in selected if selected is not None
                else _stage_included(step, level, task, events, signals))]

    project_root = str(task.get("project_root_path") or "").strip()
    task_dir = Path(project_root) / ".tp-spec" / "tasks" / task_id if project_root else None
    current_phase = str(task.get("current_stage") or "")
    task_state = str(task.get("current_state") or "")
    waiting_fact = (route.get("context") or {}).get("waiting") or {}
    waiting_stage = str(waiting_fact.get("source_stage") or current_phase) if waiting_fact else ""
    steps: List[Dict[str, Any]] = []
    completed_steps: List[Dict[str, Any]] = []
    current_step: Dict[str, Any] = {}

    for step in included:
        stage = str(step.get("stage") or "")
        role = str(step.get("role") or "")
        completion = _delivery_completion_event(events, task_dir) if stage == "delivery" else _stage_completion_event(stage, events)
        completion_source = ""
        completion_event_id = 0
        undeclared_completion = False
        if task.get("_retired") or task_state in TERMINAL:
            if completion is not None:
                status = "已完成" if stage != "verification" or _parse_detail(completion.get("detail_json")).get("verification_scope") != "technical" else "技术检查通过（限定范围）"
                completion_source = "runtime_event"
                completion_event_id = int(completion.get("id") or 0)
            else:
                status = "已停止（历史阶段）"
        elif waiting_fact and stage == waiting_stage:
            status = "已阻塞"
        elif (stage == "verification" and completion is not None
              and _parse_detail(completion.get("detail_json")).get("verification_scope") == "technical"):
            status = "技术检查通过（限定范围）"
        elif completion is not None:
            status = "已完成"
            completion_source = "runtime_event"
            completion_event_id = int(completion.get("id") or 0)
        else:
            checkpoint_map = {
                "requirement": ("tp-product-manager", "requirement"),
                "product": ("tp-product-manager", "product"),
                "architecture": ("tp-software-architect", "architecture"),
                "planning": ("tp-tech-lead", "planning"),
                "development": ("tp-development-engineer", "development"),
            }
            if stage in checkpoint_map:
                actor0, phase0 = checkpoint_map[stage]
                activity = _latest_checkpoint_activity(events, actor=actor0, phase=phase0)
                if activity and activity["semantics"]["result_status"] == "NOT_RECORDED":
                    undeclared_completion = True
            if undeclared_completion:
                status = "完成状态未声明"
            elif task_state == "BLOCKED" and stage == current_phase:
                status = "已阻塞"
            elif stage == current_phase:
                status = "进行中"
            else:
                status = "待执行"
        item = {
            "stage": stage,
            "stage_display": _display_entry(stage_presentation, stage),
            "phase": str(step.get("phase") or stage),
            "role": role,
            "role_display": _role_display(role_map, role),
            "status": status,
            "required": bool(step.get("required")),
            "trigger": str(step.get("trigger") or ""),
            "definition_source": "workflow.pipeline",
            "completion_event_id": completion_event_id,
            "completion_source": completion_source,
        }
        steps.append(item)
        if status == "已完成":
            completed_steps.append(item)
        elif not current_step and status in {"进行中", "已阻塞"}:
            current_step = item

    pipeline_role_ids = {str(item.get("role") or "") for item in steps if str(item.get("role") or "")}
    conditional_roles: List[Dict[str, Any]] = []
    seen_conditional_roles: set[str] = set()
    for recommendation in route.get("recommended_roles") or []:
        if not isinstance(recommendation, dict):
            continue
        role_id = str(recommendation.get("role_id") or "")
        if not role_id or role_id in pipeline_role_ids or role_id in seen_conditional_roles:
            continue
        seen_conditional_roles.add(role_id)
        conditional_roles.append({
            "role_id": role_id,
            "role_display": _role_display(role_map, role_id),
            "skill_path": str(recommendation.get("skill_path") or ""),
            "trigger": str(recommendation.get("trigger") or ""),
            "reason_code": str(recommendation.get("reason_code") or ""),
            "capabilities": list(recommendation.get("capabilities") or []),
            "definition_source": "workflow.conditional_roles",
        })

    next_stage = str(route.get("next_stage") or waiting_stage or "")
    next_step: Dict[str, Any] = {}
    if next_stage and next_stage != "complete":
        pipeline_step = next((item for item in steps if item["stage"] == next_stage), None)
        next_role = str(waiting_fact.get("responsibility") or route.get("role_id") or (pipeline_step or {}).get("role") or "")
        next_action = str(route.get("recommended_action") or "")
        confirmation_reason = str(route.get("confirmation_reason") or "")
        next_step = {
            "stage": next_stage,
            "stage_display": _display_entry(stage_presentation, next_stage),
            "role": next_role,
            "role_display": _role_display(role_map, next_role),
            "action": next_action,
            "action_display": _display_entry(action_presentation, next_action),
            "confirmation_required": bool(route.get("confirmation_required")),
            "confirmation_reason": confirmation_reason,
            "confirmation_display": _display_entry(confirmation_presentation, confirmation_reason),
            "reason_codes": list(route.get("reason_codes") or []),
        }
    elif next_stage == "complete":
        complete_action = str(route.get("recommended_action") or "task_complete")
        next_step = {
            "stage": "complete",
            "stage_display": _display_entry(stage_presentation, "complete"),
            "role": "",
            "role_display": _role_display(role_map, ""),
            "action": complete_action,
            "action_display": _display_entry(action_presentation, complete_action),
            "confirmation_required": False,
            "confirmation_reason": "",
            "confirmation_display": _display_entry(confirmation_presentation, ""),
            "reason_codes": list(route.get("reason_codes") or []),
        }

    if waiting_fact and next_step:
        next_step["waiting"] = waiting_fact
    return {
        "effective_level": level,
        **task["_progress_facts"],
        "retired": bool(task.get("_retired")),
        **({"current_effective": route["context"]["current_effective"]}
           if "current_effective" in route.get("context", {}) else {}),
        "completed_steps": completed_steps,
        "current_step": current_step,
        "current_step_source": ("runtime_waiting" if waiting_fact else "task.current_stage") if current_step else "unresolved",
        "next_step": next_step,
        "next_step_source": "workflow_contract" if next_step else "none",
        "steps": steps,
        "conditional_roles": conditional_roles,
        "reference_steps": [],
        "route": {
            "decision": str(route.get("decision") or ""),
            "recommended_action": str(route.get("recommended_action") or ""),
            "next_stage": str(route.get("next_stage") or ""),
            "role_id": str(route.get("role_id") or ""),
            "confirmation_required": bool(route.get("confirmation_required")),
            "confirmation_reason": str(route.get("confirmation_reason") or ""),
            "reason_codes": list(route.get("reason_codes") or []),
        },
    }
