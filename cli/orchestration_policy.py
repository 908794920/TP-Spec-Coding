# -*- coding: utf-8 -*-
"""校验既有 Base 路由政策与少量 project config 覆盖。

复用 config(key, scope, scope_id)，不另建配置源。角色身份、执行权限、
隔离和最终必要门禁是正确性不变量，不能作为项目偏好关闭。
"""
from __future__ import annotations

import copy
import json
from typing import Any, Iterable

PREFIX = "orchestration."
STAGES = {
    "requirement": ("tp-requirements-manager", "requirement"),
    "product": ("tp-product-manager", "product"),
    "architecture": ("tp-software-architect", "architecture"),
    "architecture_review": ("tp-software-architect", "architecture"),
    "planning": ("tp-tech-lead", "planning"),
    "development": ("tp-development-engineer", "development"),
    "verification": ("tp-test-engineer", "verification"),
    "review": ("tp-code-reviewer", "review"),
    "delivery": ("tp-integration-engineer", "delivery"),
}
SIGNALS = {
    "include_stage_prefix": "workflow:include-stage:",
    "skip_stage_prefix": "workflow:skip-stage:",
    "multiple_routes": "workflow:multiple-feasible-routes",
    "deep_review": "workflow:deep-review",
    "root_cause_prefix": "workflow:root-cause:",
    "security_risk": "workflow:security-risk",
    "database_risk": "workflow:database-risk",
    "knowledge_required": "workflow:knowledge-required",
    "ux_design": "workflow:ux-design",
}
TRIGGERS = {"contextual", "unresolved_scope", "architecture_risk", "behavioral_change", "deep_review"}


class PolicyError(ValueError):
    pass


def stage_phase(stage: str) -> str:
    return STAGES[stage][1]


def checkpoint_actor_ids(stage: str) -> tuple[str, ...]:
    role, _ = STAGES[stage]
    if stage in {"architecture_review", "verification", "review", "delivery"}:
        return ()
    return (role, "tp-product-manager") if stage == "requirement" else (role,)


def _invalid(path: str, reason: str) -> None:
    raise PolicyError(f"ORCHESTRATION_POLICY_INVALID: {path}: {reason}")


def _fields(value: Any, path: str, required: set[str], optional: set[str] | None = None) -> None:
    if not isinstance(value, dict) or set(value) - required - (optional or set()) or required - set(value):
        _invalid(path, "mapping with supported, complete fields required")


def protected_stages(level: str) -> set[str]:
    # Q01 未变：项目偏好不能将最终必要义务改成可选项。
    return {"development", "delivery"} | ({"verification"} if level != "L0" else set()) | (
        {"review", "delivery"} if level in {"L2", "L3"} else set()
    )


def validate(data: dict[str, Any], catalog: dict[str, Any]) -> None:
    roles = {row["workflow_role"]: row for row in catalog["roles"]}
    if data.get("entry_role") != "tp-software-lifecycle" or data.get("level_resolution") != {"rule": "MAX_RISK_FLOW"}:
        _invalid("entry_role/level_resolution", "single entry and max risk/flow resolution are invariant")
    confirmation = data["confirmation"]
    _fields(confirmation, "confirmation", {"default_policy", "supported_policies", "user_preference_path"})
    if (confirmation["default_policy"] != "material"
            or confirmation["supported_policies"] != ["material"]
            or confirmation["user_preference_path"] != "~/.tp-spec/preferences.yaml"):
        _invalid("confirmation", "retain material default and existing user preference boundary")
    runtime = data["runtime"]
    _fields(runtime, "runtime", {"new_public_states", "new_database_objects", "ordinary_confirmation_persisted", "trusted_completion_sources"})
    if (runtime["new_public_states"] is not False or runtime["new_database_objects"] is not False
            or runtime["ordinary_confirmation_persisted"] is not True
            or runtime["trusted_completion_sources"] != ["CHECKPOINT", "REVIEW_COMPLETED", "VERIFICATION_COMPLETED", "DELIVERY_RESULT", "KNOWLEDGE_CONVERGENCE_RESULT"]):
        _invalid("runtime", "public states, fact store and trusted completion sources are invariant")
    if set(data["pipelines"]) != {"L0", "L1", "L2", "L3"}:
        _invalid("pipelines", "exactly L0/L1/L2/L3 are supported")
    for level, steps in data["pipelines"].items():
        if not isinstance(steps, list) or not steps:
            _invalid(f"pipelines.{level}", "nonempty stage list required")
        seen: list[str] = []
        for i, step in enumerate(steps):
            path = f"pipelines.{level}[{i}]"
            if not isinstance(step, dict):
                _invalid(path, "mapping required")
            if set(step) - {"stage", "phase", "role", "required", "trigger", "mode", "effects"}:
                _invalid(path, "unknown stage field")
            stage = step.get("stage")
            if not isinstance(stage, str) or stage not in STAGES or stage in seen:
                _invalid(path, "unknown or duplicated stage")
            seen.append(stage)
            if (step.get("role"), step.get("phase")) != STAGES[stage]:
                _invalid(path, "professional role/phase identity cannot be replaced")
            if step["role"] not in roles:
                _invalid(path, "role not in active catalog")
            if type(step.get("required")) is not bool:
                _invalid(path + ".required", "boolean required")
            if stage in protected_stages(level) and step["required"] is not True:
                _invalid(path + ".required", "protected obligation cannot be disabled")
            if step.get("trigger") is not None and (not isinstance(step["trigger"], str) or step["trigger"] not in TRIGGERS):
                _invalid(path + ".trigger", "unknown trigger")
            if not isinstance(step.get("mode"), str) or step["mode"] not in {"DIRECT", "AUTO_PLANNING", "AUTO_REVIEW"}:
                _invalid(path + ".mode", "unsupported mode")
            expected_host = {"AUTO_PLANNING": "auto_planning_host", "AUTO_REVIEW": "auto_review_host"}.get(step["mode"])
            if expected_host and expected_host not in roles[step["role"]].get("orchestration_capabilities", []):
                _invalid(path + ".mode", "role does not own this capability")
            if step.get("effects") != (["repo_mutation"] if stage == "development" else []):
                _invalid(path + ".effects", "execution effects cannot be removed or expanded by policy")
        if not protected_stages(level).issubset(seen):
            _invalid(f"pipelines.{level}", "protected stages missing")
        if seen != sorted(seen, key=list(STAGES).index):
            _invalid(f"pipelines.{level}", "capability dependency order cannot be reversed")
    signals = data["signals"]
    if set(signals) != set(SIGNALS) or any(not isinstance(v, str) or not v.strip() for v in signals.values()):
        _invalid("signals", "supported signal names must have nonempty strings")
    if len(set(signals.values())) != len(signals):
        _invalid("signals", "signal names/prefixes must be distinct")
    for key, prefix in signals.items():
        if key.endswith("_prefix") and any(other.startswith(prefix) for k, other in signals.items() if k != key):
            _invalid("signals", "overlapping signal prefixes are ambiguous")
    execution = data["execution"]
    _fields(execution, "execution", {"lazy_load_role_skill", "prefer_parallel_isolated_subagents", "sequential_isolation_fallback",
            "concurrent_workflow_stages", "assignment_effects", "delivery_fast_path"}, {"artifact_collection"})
    # Keep doctor/routing validation consistent with the collection consumer.
    collection = execution.get("artifact_collection", {})
    _fields(collection, "execution.artifact_collection", set(), {"max_files", "max_file_bytes"})
    for key, value in collection.items():
        if type(value) is not int or value < 1:
            _invalid("execution.artifact_collection." + key, "positive integer required")
    for key in ("lazy_load_role_skill", "sequential_isolation_fallback", "assignment_effects"):
        if execution.get(key) is not True:
            _invalid("execution." + key, "must remain enabled")
    if execution.get("concurrent_workflow_stages") is not False:
        _invalid("execution.concurrent_workflow_stages", "dependent work remains sequential")
    if execution.get("prefer_parallel_isolated_subagents") is not True:
        _invalid("execution.prefer_parallel_isolated_subagents", "retain existing isolated parallel preference and sequential fallback")
    fast = execution["delivery_fast_path"]
    _fields(fast, "execution.delivery_fast_path", {"max_incremental_ai_overhead_percent", "context_source", "allow_default_subagents",
            "allow_full_task_reread", "allow_full_knowledge_scan", "require_targeted_knowledge_search"})
    budget = fast.get("max_incremental_ai_overhead_percent")
    if type(budget) is not int or not 1 <= budget <= 5:
        _invalid("execution.delivery_fast_path.max_incremental_ai_overhead_percent", "integer 1..5; existing upper bound retained")
    for key in ("allow_default_subagents", "allow_full_task_reread", "allow_full_knowledge_scan"):
        if fast.get(key) is not False:
            _invalid("execution.delivery_fast_path." + key, "must remain false")
    if fast.get("require_targeted_knowledge_search") is not True:
        _invalid("execution.delivery_fast_path.require_targeted_knowledge_search", "must remain true")
    if fast.get("context_source") != "runtime_compact_fact_pack":
        _invalid("execution.delivery_fast_path.context_source", "unsupported context source")
    conditional = data.get("conditional_roles", [])
    if not isinstance(conditional, list):
        _invalid("conditional_roles", "list required")
    expected = {"tp-security-engineer": "security_risk", "tp-database-engineer": "database_risk", "tp-code-reviewer": "deep_review", "tp-ux-designer": "ux_design"}
    seen_roles = set()
    for rule in conditional:
        if not isinstance(rule, dict) or set(rule) - {"role", "trigger", "phases", "read_effects", "mutation_effects"}:
            _invalid("conditional_roles", "unknown/malformed role policy")
        role = rule.get("role")
        if not isinstance(role, str) or role not in expected or role in seen_roles or rule.get("trigger") != expected[role]:
            _invalid("conditional_roles", "specialist identity/trigger must remain unambiguous")
        seen_roles.add(role)
        phases = rule.get("phases")
        if not isinstance(phases, list) or not phases or any(p not in roles[role].get("phases", []) for p in phases):
            _invalid("conditional_roles." + role, f"phases {phases!r} must belong to this role in the active role catalog")
        if rule.get("read_effects") != [] or rule.get("mutation_effects", []) not in ([], ["repo_mutation"]):
            _invalid("conditional_roles." + role, "invalid effects")


def _apply(data: dict[str, Any], key: str, value: Any) -> str:
    path = key.removeprefix(PREFIX)
    parts = path.split(".")
    if len(parts) == 4 and parts[0] == "pipelines" and parts[1] in data["pipelines"] and parts[3] == "required":
        step = next((s for s in data["pipelines"][parts[1]] if s["stage"] == parts[2]), None)
        if step is not None and type(value) is bool:
            if parts[2] in protected_stages(parts[1]) and not value:
                _invalid(key, "protected obligation cannot be disabled")
            step["required"] = value
            return path
    if path == "execution.delivery_fast_path.max_incremental_ai_overhead_percent" and type(value) is int and 1 <= value <= 5:
        data["execution"]["delivery_fast_path"][parts[-1]] = value
        return path
    # 仅开放具有实际消费者的政策，不透传任意 YAML。
    _invalid(key, "unsupported override or invalid value; supported: existing stage.required booleans and delivery budget 1..5")


def resolve(data: dict[str, Any], catalog: dict[str, Any], rows: Iterable[Any], *, project_id: str, task_id: str | None = None) -> dict[str, Any]:
    result = copy.deepcopy(data)
    sources = {"$": "governance/orchestration.yaml"}
    for row in rows:
        scope, scope_id = row["scope"], row["scope_id"]
        if scope == "project" and scope_id != project_id:
            if scope_id:
                continue
        elif scope == "task" and task_id and scope_id != task_id:
            continue
        if scope != "project" or not scope_id:
            _invalid(row["key"], "only explicit project scope is supported; repair the legacy config row")
        try:
            value = json.loads(row["value_json"])
        except (ValueError, TypeError) as exc:
            _invalid(row["key"], f"invalid JSON value ({type(exc).__name__})")
        path = _apply(result, row["key"], value)
        sources[path] = "config:project/" + project_id
    validate(result, catalog)
    result["_policy_sources"] = sources
    return result


def read_rows(conn) -> list[Any]:
    return conn.execute("SELECT key,scope,scope_id,value_json FROM config WHERE key LIKE 'orchestration.%' ORDER BY scope,scope_id,key").fetchall()


def validate_write(conn, data: dict[str, Any], catalog: dict[str, Any], *, key: str, value_json: str, scope: str, project_id: str | None) -> None:
    if scope != "project" or not project_id:
        _invalid(key, "an explicit project scope-id is required")
    if conn.execute("SELECT 1 FROM project WHERE project_id=?", (project_id,)).fetchone() is None:
        _invalid(key, "project scope-id is not registered in this database")
    # 同 key 的合法值允许修复旧坏值，不能因先校验旧值而永久锁死。
    rows = [dict(r) for r in read_rows(conn) if not (r["key"] == key and r["scope"] == scope and r["scope_id"] == project_id)]
    rows.append({"key": key, "scope": scope, "scope_id": project_id, "value_json": value_json})
    resolve(data, catalog, rows, project_id=project_id)


def normalize_signal(value: str, configured: dict[str, str]) -> str:
    for key, canonical in SIGNALS.items():
        actual = configured[key]
        if key.endswith("_prefix") and value.startswith(actual):
            return canonical + value[len(actual):]
        if not key.endswith("_prefix") and value == actual:
            return canonical
    return value


def valid_user_source(source: Any) -> bool:
    return (isinstance(source, dict) and source.get('kind') == 'user_instruction'
            and all(isinstance(source.get(key), str) and source[key].strip()
                    for key in ('reference', 'statement')))


def user_source(statement: str | None, reference: str | None) -> dict:
    source = {'kind': 'user_instruction', 'statement': statement, 'reference': reference}
    if not valid_user_source(source):
        raise ValueError('USER_SOURCE_REQUIRED: record the actual user instruction and its context/file reference')
    return {key: value.strip() for key, value in source.items()}


def resolve_task_mode(task: dict, events: Iterable[Any]) -> dict:
    """The sole mode authority: trusted creation/selection facts, never title or risk."""
    from . import event_contract, event_policies, task_coordinator, workflow_controls
    mode, source, issues = 'standard', None, []
    rows = sorted((dict(row) for row in events), key=lambda row: int(row.get('id') or 0))
    for row in rows:
        if row.get('task_id') != task['task_id']:
            continue
        raw = row.get('detail_json') or '{}'
        try:
            detail = json.loads(raw)
        except (ValueError, TypeError):
            detail = None
        creation = row.get('event_type') == 'STATE' and (
            isinstance(detail, dict) and detail.get('producer') == 'task_create')
        selected = row.get('event_type') == 'TASK_MODE_SELECTED'
        claims = (isinstance(detail, dict) and 'workflow_mode' in detail) or '"workflow_mode"' in str(raw)
        if not selected and not (creation and claims):
            if claims and row.get('event_type') == 'STATE' and task_coordinator.claims_creation_metadata(detail, raw):
                issues.append(f'TASK_MODE_INVALID:{row.get("id")}')
            continue
        if creation:
            trusted = task_coordinator.read_creation_coordinator(task, rows)
            valid = not trusted['issues'] and trusted['source'] and trusted['source']['event_id'] == row['id']
        else:
            valid = (isinstance(detail, dict) and event_policies.event_allowed_for_producer('TASK_MODE_SELECTED', 'task_mode_select')
                     and workflow_controls.trusted_event_detail(row, event_type='TASK_MODE_SELECTED',
                         producer='task_mode_select', actor=str(row.get('actor_role') or '')) is not None
                     and not event_contract.validate_event_semantics('TASK_MODE_SELECTED', detail)
                     and detail.get('previous_mode') == mode)
        value = detail.get('workflow_mode') if isinstance(detail, dict) else None
        origin = detail.get('user_source') if isinstance(detail, dict) else None
        if not valid or value not in {'standard', 'quick'} or (
                (selected or value == 'quick' or origin is not None) and not valid_user_source(origin)):
            issues.append(f'TASK_MODE_INVALID:{row.get("id")}')
            continue
        mode = value
        source = {'kind': 'task_create' if creation else 'task_mode_selected', 'event_id': int(row['id']),
                  'user_source': origin, 'digest': workflow_controls.event_digest(row)}
    return {'workflow_mode': mode if not issues else 'standard', 'mode_source': source if not issues else None,
            'issues': issues}


def resolve_task_obligations(task: dict, events: Iterable[Any], included_stages=None) -> dict:
    rows = [dict(row) for row in events]
    facts = resolve_task_mode(task, rows)
    quick = facts['workflow_mode'] == 'quick'
    if included_stages is None and not quick:
        from . import orchestration
        level = orchestration.resolve_effective_level(task.get('risk_level'), task.get('flow_level'))
        contract = task.get('_effective_contract') or orchestration.load_contract()
        signals = orchestration._decision_signals(rows, contract)
        included_stages = [step['stage'] for step in contract['pipelines'][level]
                           if orchestration._stage_included(step, level, task, rows, signals)]
    selected = set(included_stages or [])
    facts['applicable_obligations'] = {
        'development': True, 'verification': True if quick else bool(selected & {'verification', 'review'}),
        'review': False if quick else 'review' in selected, 'delivery': True,
        'acceptance': 'declared' if quick else 'required',
        'knowledge': not quick, 'memory': not quick, 'completion_confirmation': quick,
    }
    return facts


def continuous_actor_ids(task: dict, events: Iterable[Any]) -> set[str]:
    """Actual recorded executor/coordinator identities for quick self checks/delivery."""
    from .task_coordinator import read_creation_coordinator
    from .role_registry import actor_ids
    rows = [dict(row) for row in events]
    if resolve_task_mode(task, rows)['workflow_mode'] != 'quick':
        return {'tp-development-engineer', 'tp-test-engineer', 'tp-integration-engineer'}
    coordinator = read_creation_coordinator(task, rows)['coordinator'] or {}
    allowed = {'tp-development-engineer', 'tp-test-engineer', 'tp-integration-engineer', coordinator.get('role')}
    for row in rows:
        try:
            detail = json.loads(row.get('detail_json') or '{}')
        except (ValueError, TypeError):
            continue
        if (row.get('event_type') == 'FACT' and isinstance(detail, dict)
                and detail.get('producer') == 'record-first' and detail.get('transaction_id')
                and detail.get('operation') == 'CHECKPOINT' and detail.get('phase') == 'development'):
            allowed.add(row.get('actor_role'))
    return set(actor_ids()) & allowed - {'human_owner'}
