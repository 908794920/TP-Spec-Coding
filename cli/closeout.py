# -*- coding: utf-8 -*-
"""Read-only closeout diagnostics over existing Runtime facts, not another workflow.

Each check owns only its evidence/applicability diagnostic. Routing, professional
results, acceptance, Work and temporary-artifact policies remain their own sources.
Unknown required facts are not permission to complete. No repair or cleanup here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import delivery_contract, event_policies, orchestration, record_first

SCHEMA = "tp-spec.closeout/v1"

# Only an explicit business prerequisite that is missing/stale becomes PENDING.
# Parse/encoding/IO errors, unsupported ranges and unrecognized exceptions keep
# their original UNKNOWN status.
_PREREQUISITE_ERRORS = frozenset({
    "DELIVERY_REQUIRES_CURRENT_VERIFICATION_PASS",
    "DELIVERY_CHANGE_SET_MISMATCH",
    "REVIEW_BINDING_UNKNOWN",
    "CHANGE_SET_REQUIRED",
    "DEVELOPMENT_CHANGE_SET_REQUIRED",
    "KNOWLEDGE_INPUT_PENDING",
    "OWNER_SCOPE_UNKNOWN",
    "DATABASE_SCOPE_UNKNOWN",
    "VISUAL_SCOPE_UNKNOWN",
})

NODE_STATUSES = ("REUSABLE", "REGISTRATION_PENDING", "CURRENT_GAP", "OWNER_DEFERRED",
                 "BLOCKED_BY_UPSTREAM", "NOT_YET_DUE", "OWNER_PENDING", "NOT_APPLICABLE", "UNKNOWN")

_OWN_FAILURE_TYPES = (OSError, UnicodeError, json.JSONDecodeError)
# A caller may prefix the message with the exception class when it is rendered as
# text; that prefix is transport, not the error's own machine code.
_EXC_PREFIX = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Warning)\s*:\s*")


def _leading_code(exc) -> str:
    """The exception's own machine code, never a code mentioned inside prose."""
    text = str(exc) or ""
    text = _EXC_PREFIX.sub("", text, count=1)
    match = re.match(r"([A-Z][A-Z0-9_]+)", text)
    return match.group(1) if match else ""


def _is_own_failure(exc) -> bool:
    """This check's own read/parse failed; that stays UNKNOWN, never a business gap."""
    return isinstance(exc, _OWN_FAILURE_TYPES)


def _is_prerequisite_error(exc) -> bool:
    """Only an exact leading business code counts, not a substring anywhere."""
    if _is_own_failure(exc):
        return False
    return _leading_code(exc) in _PREREQUISITE_ERRORS


def compact(result: dict[str, Any]) -> dict[str, Any]:
    """Project a completed preflight; never omit a check, blocker or unknown."""
    value = dict(result)
    value["detail_mode"] = "COMPACT"
    if result.get("retired"):
        return value
    value["detail_note"] = "All checks executed; nested facts/route context are available without --compact."
    value["checks"] = []
    for row in result["checks"]:
        facts = row.get("facts") or {}
        omitted = [key for key, item in facts.items() if isinstance(item, (dict, list))]
        value["checks"].append({**row,
            "facts": {key: item for key, item in facts.items() if key not in omitted},
            "detail_fields": omitted})
    route = result.get("route")
    if isinstance(route, dict):
        value["route"] = {key: route[key] for key in (
            "next_stage", "recommended_action", "reason_codes", "blocker", "role_id",
            "next_responsibility", "workflow_mode", "effective_level", "included_stages",
        ) if key in route}
        if isinstance(route.get("plan_route_alignment"), dict):
            value["route"]["plan_route_alignment"] = route["plan_route_alignment"]
    # Nodes are already compact explanation rows; never drop one or its status.
    value["nodes"] = list(result.get("nodes") or [])
    value["current_stage_blockers"] = list(result.get("current_stage_blockers") or [])
    value["downstream_closeout_pending"] = list(result.get("downstream_closeout_pending") or [])
    value["unknown_sources"] = list(result.get("unknown_sources") or [])
    return value


def retired_history(task, task_dir: str, retirement: event_policies.TrustedEvent) -> dict[str, Any]:
    return {"schema": SCHEMA, "task_id": task["task_id"], "state": task["current_state"],
            "retired": True, "ready": False, "already_terminal": False, "read_only": True,
            "task_dir": str(Path(task_dir).absolute()), "checks": [], "blockers": [],
            "unknowns": [], "acceptance_issues": [], "route": None, "next_actions": [],
            "retirement": {"event_id": retirement.row["id"], "reason": retirement.detail["reason"]},
            "coverage_note": "可信退休任务只展示历史，不执行结单预检或追补新义务。"}


def terminal_result(conn, task) -> dict[str, Any]:
    state = str(task["current_state"])
    row = conn.execute(
        "SELECT * FROM task_event WHERE task_id=? AND event_type='STATE' AND to_state=? ORDER BY id DESC LIMIT 1",
        (task["task_id"], state),
    ).fetchone()
    return {"task_id": task["task_id"], "state": state, "already_terminal": True,
            "completed": state == "COMPLETED", "replayed": True, "facts_committed": False,
            "terminal_event_id": row["id"] if row else None,
            "summary": row["summary"] if row else None, "completed_at": task["completed_at"],
            "view_status": "NOT_REFRESHED", "result_scope": "recorded terminal state; not a new verification"}


def _architecture_review_gap(conn, task_id, task_dir, events):
    """Reuse the single read-only architecture diagnosis; never infer a PASS."""
    diagnosis = event_policies.diagnose_architecture_review(conn, task_id, task_dir)
    facts = dict(diagnosis["facts"])
    facts["status"] = diagnosis["status"]
    if diagnosis.get("localized"):
        facts["localized_scope"] = diagnosis["localized"]
    return facts, list(diagnosis["issues"])


def collect(conn, task, task_dir: Path, *, db_path: str, base_root=None) -> dict[str, Any]:
    task = dict(task)
    task_id, state = task["task_id"], str(task["current_state"])
    events = [dict(row) for row in conn.execute('SELECT * FROM task_event WHERE task_id=? ORDER BY id', (task_id,))]
    from .orchestration_policy import resolve_task_mode
    mode = resolve_task_mode(task, events)
    if mode["domain"] != "software":
        from .video_records import closeout
        return closeout(conn, task, task_dir, events, mode=mode, base_root=base_root)
    quick = mode['workflow_mode'] == 'quick'
    result: dict[str, Any] = {"schema": SCHEMA, "task_id": task_id, "state": state,
        "ready": False, "already_terminal": state in record_first.TERMINAL_STATES,
        "checks": [], "blockers": [], "unknowns": [], "acceptance_issues": [], "route": None,
        "next_actions": [], "read_only": True,
        "task_dir": str(task_dir),
        "consistency": "one SQLite read snapshot; files are rechecked, not filesystem-locked",
        "coverage_note": "检查已登记的步骤、范围、AC、人验、数据库操作、证据、Work、临时工件及收敛结果；未知项不会视为通过，不证明未登记业务或真实运行效果。"}
    result.update(workflow_mode=mode['workflow_mode'], mode_source=mode['mode_source'], mode_issues=mode['issues'])
    if result["already_terminal"]:
        result.update(terminal_result(conn, task))
        result["checks"] = [{"id": "transition", "status": "TERMINAL", "required": False,
                             "issues": [], "depends_on": [], "responsibility": None,
                             "facts": {"state": state, "note": "历史终态不追补新义务，不刷新或改写证据"}}]
        return result

    def check(key, role, dependencies, fn, *, required=True):
        row = {"id": key, "status": "PASS", "required": required, "issues": [],
               "depends_on": list(dependencies), "responsibility": role, "facts": {}}
        try:
            row.update(fn() or {})
        except Exception as exc:
            # Isolate unreadable evidence so independent blockers still reach the caller.
            # The exception is exposed; it cannot turn this check into PASS or a fallback.
            # Only a recognized business prerequisite is PENDING; other exceptions keep
            # their original UNKNOWN and stay visible with their real source.
            upstream = next((dep for dep in row["depends_on"]
                             if by_status.get(dep) == "UNKNOWN"), None)
            if _is_prerequisite_error(exc):
                row.update(status="PENDING", issues=[f"{type(exc).__name__}: {exc}"],
                           pending_kind="prerequisite")
            elif _is_own_failure(exc):
                # The check ran and its own read/parse failed: that is its own
                # UNKNOWN, never a dependency or business-prerequisite downgrade.
                row.update(status="UNKNOWN", issues=[f"{type(exc).__name__}: {exc}"])
            else:
                # This check was actually attempted. An unrecognized failure is
                # its own UNKNOWN even when an upstream check also failed.
                row.update(status="UNKNOWN", issues=[f"{type(exc).__name__}: {exc}"])
        by_status[key] = row["status"]
        result["checks"].append(row)
        return row

    by_status: dict[str, str] = {}

    def pending(issues, **facts):
        return {"status": "PENDING" if issues else "PASS", "issues": list(issues), "facts": facts}

    def na(reason):
        return {"status": "NOT_APPLICABLE", "required": False, "facts": {"reason": reason}}

    def identity():
        from .transaction_commit import _assert_task_workspace_identity
        from .version import active_version
        _assert_task_workspace_identity(conn, task_dir, task_id)
        from .frontmatter import parse
        for name in ("task.md", "requirement.md"):
            path = task_dir / name
            if path.is_file():
                meta = parse(path.read_text(encoding="utf-8-sig")) or {}
                if meta.get("task_id") not in (None, "", task_id):
                    raise ValueError(f"TASK_IDENTITY_MISMATCH: {name}")
        if task["base_version"] != active_version(base_root):
            raise ValueError("TASK_CONTRACT_MISMATCH: use supported task migration before mutation")
        return pending([], contract=task["base_version"])
    check("identity", "tp-software-lifecycle", [], identity)
    check("transition", "tp-software-lifecycle", [], lambda: pending(
        [] if state in {"NEW", "ACTIVE"} else [f"INTEGRITY_STATE: {state}; resolve explicit blocker before complete"], state=state))

    events = [dict(row) for row in conn.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id", (task_id,))]
    facts = None
    def route_check():
        nonlocal facts
        facts = orchestration._load_task_facts(task_id, db_path, connection=conn, task_dir=task_dir)
        # Use the caller's explicit Task directory throughout, not a second implicit source.
        route = orchestration.resolve_route(task_id, db_path=db_path, base_root=base_root, _facts=facts, task_dir=task_dir)
        result["route"] = route
        for key in ('workflow_mode', 'mode_source', 'applicable_obligations', 'quick_status'):
            if key in route:
                result[key] = route[key]
        result["effective_level"] = route["effective_level"]
        result["included_stages"] = list(route.get("included_stages") or [])
        issues = [] if (route.get("next_stage") == "complete" and route.get("recommended_action") == "task_complete") else [
            "INTEGRITY_PIPELINE_PENDING: " + str(route.get("blocker") or ",".join(route.get("reason_codes") or []) or route.get("recommended_action"))]
        return pending(issues, next_stage=route.get("next_stage"), action=route.get("recommended_action"),
                       effective_level=route["effective_level"], risk_signals=route.get("risk_signals", []))
    route_row = check("route", "tp-software-lifecycle", ["identity"], route_check)
    if result["route"]:
        route_row["responsibility"] = result["route"].get("next_responsibility") or result["route"].get("role_id") or "tp-integration-engineer"

    def execution_check():
        from .execution import completion_blockers, read_execution
        data = read_execution(conn, task)
        return pending(completion_blockers(conn, task), plan_version=data.get("plan_version"),
                       plan_recorded=data.get("plan") is not None,
                       note="未登记历史步骤不补造；显式计划必须收敛，步骤完成历史不等于证据仍适用")
    check("execution", "tp-software-lifecycle", [], execution_check)

    def work_check():
        from .workitem_cmd import summarize_work_items
        from .work_units import TERMINAL_WORK_STATES
        data = summarize_work_items(conn, task)
        issues = list(data["issues"])
        issues.extend(f"WORK_PENDING: {w['item_id']} ({w['status']})" for w in data["items"] if w["status"] not in TERMINAL_WORK_STATES)
        return pending(issues, items=data["items"], counts=data["counts"])
    check("work", "tp-software-lifecycle", [], work_check)

    def integration_check():
        from .work_units import integration_status
        status = integration_status(conn, task)
        if status["status"] == "NOT_REQUIRED" and not status["issues"]:
            return na("没有采用新 Work 结果契约；不追补旧候选")
        return pending(status["issues"], **{key: value for key, value in status.items() if key != "issues"})
    check("integration_candidate", "tp-software-lifecycle", ["work"], integration_check)

    acceptance = None
    def acceptance_check():
        nonlocal acceptance
        from .yaml_checks import check_acceptance_with_owner
        path = task_dir / "acceptance.md"
        if not path.is_file():
            if quick:
                return na('quick未登记额外AC；保留真实验证及未实测说明')
            raise ValueError("ACCEPTANCE_MISSING: explicit AC or no_acceptance_required declaration is needed")
        acceptance = check_acceptance_with_owner(
            path.read_text(encoding="utf-8-sig"), conn=conn, task_id=task_id, task_dir=task_dir,
            enforce_completion=True, allow_human_pending=False,
        )
        issues = list(acceptance.issues)
        issues.extend(record_first.acceptance_truth_issues(conn, task_id, task_dir))
        result["acceptance_issues"] = list(dict.fromkeys(issues))
        return pending(result["acceptance_issues"], pending_rows=acceptance.pending_rows, verdict_counts=acceptance.verdict_counts)
    check("acceptance", "tp-test-engineer", [], acceptance_check)

    def owner_check():
        if acceptance is None:
            if quick and not (task_dir / 'acceptance.md').is_file():
                return na('没有登记人工验收项；结单同意不表示已人工运行')
            raise ValueError("OWNER_SCOPE_UNKNOWN: acceptance input is unreadable")
        data = event_policies.effective_owner_acceptance(conn, task_id, task_dir=task_dir)
        issues = [f"OWNER_ACCEPTANCE_PENDING: {item['ac']}" for item in acceptance.human_rows if item["verdict"] in {"PENDING", "BLOCKED"}]
        issues.extend(i for i in record_first.acceptance_truth_issues(conn, task_id, task_dir)
                      if "human" in i or "owner" in i or "OWNER" in i or "DEFERRED" in i)
        return pending(issues, declared_acs=[i["ac"] for i in acceptance.human_rows],
                       accepted_acs=data["accepted_acs"], visual_acs=data["visual_acs"],
                       note="仅声明范围的真实人验，不推断数据库操作或未覆盖AC")
    check("owner", "human_owner", ["acceptance"], owner_check)

    def database_check():
        if acceptance is None:
            if quick and not (task_dir / 'acceptance.md').is_file():
                return na('没有数据库操作声明；模式不授予数据库动作权限')
            raise ValueError("DATABASE_SCOPE_UNKNOWN: acceptance input is unreadable")
        issues, items = delivery_contract.database_disposition(task_dir, acceptance)
        return pending(issues, operations=acceptance.database_operations, evidence_items=items)
    check("database", "tp-database-engineer", ["acceptance"], database_check)

    snapshot = None
    binding = None
    subject = ""
    def subject_check():
        nonlocal snapshot, binding, subject
        from .change_set import capture_bound_product, is_ops_subject, same_bound_product_content
        from .digest import compute_verification_subject_digest
        binding = record_first._latest_development_change_set(conn, task_id)
        if not binding or not binding.get("change_set_id") or (not binding.get("repo_roots") and not is_ops_subject(binding["detail"])):
            raise ValueError("CHANGE_SET_REQUIRED: no explicit development product binding")
        subject = compute_verification_subject_digest(task_dir,
            subject_mode=binding["detail"].get("subject_mode", "legacy"))
        snapshot = capture_bound_product(binding["detail"], task_dir, repo_roots=binding["repo_roots"])
        issues = []
        if not same_bound_product_content(binding["detail"], snapshot):
            issues.append("CHANGE_SET_STALE: current product differs from the recorded development candidate")
        try:
            if quick:
                delivery_contract.require_scope_checkpoint(conn, task_id, development_event_id=int(binding['event_id']))
            else:
                delivery_contract.require_full_scope(conn, task_id, binding["detail"], development_event_id=int(binding["event_id"]))
        except ValueError as exc:
            issues.append(str(exc))
        return pending(issues, subject_digest=subject, change_set_id=snapshot["content_digest"],
                       product_schema=snapshot["schema"],
                       **({"ops_subject": snapshot} if is_ops_subject(binding["detail"]) else {}),
                       development_event_id=binding["event_id"])
    check("subject", "tp-development-engineer", ["identity"], subject_check)

    def visual_check():
        if acceptance is None:
            if quick and not (task_dir / 'acceptance.md').is_file():
                return na('未登记必需视觉验收；实际未验边界保留在交付结果')
            raise ValueError("VISUAL_SCOPE_UNKNOWN: acceptance input is unreadable")
        visual = (acceptance.page_verification or {}).get("visual")
        if not isinstance(visual, dict) or visual.get("required") is not True:
            return na("没有登记必需视觉 Manifest；不表示实际页面已验收")
        from .artifact_validation import validate_visual_verification_manifest
        path = str(visual.get("evidence_manifest") or "").strip()
        # Exactly the same missing-manifest Owner alternative as formal Verification.
        missing = not Path(path).is_absolute() and not (task_dir / path).is_file()
        cs = str((snapshot or {}).get("content_digest") or "")
        if missing and cs and record_first._owner_visual_acceptance_covers(
                conn, task_id, task_dir, acceptance, visual, change_set_id=cs, subject_digest=subject):
            return pending([], source="current Owner visual acceptance", acceptance_refs=visual.get("acceptance_refs"))
        validated = validate_visual_verification_manifest(task_dir, path,
            expected_change_set_id=cs, acceptance_ids=set(acceptance.acceptance_ids))
        issues = list(validated.errors)
        if not cs:
            issues.append("VISUAL_SUBJECT_UNKNOWN: product snapshot unavailable")
        return pending(issues, manifest=path, evidence_paths=validated.evidence_paths)
    check("visual", "tp-test-engineer", ["subject", "acceptance", "owner"], visual_check)

    included = result.get("included_stages")
    verification = None
    def verification_check():
        nonlocal verification, subject
        if included is None:
            raise ValueError("VERIFICATION_APPLICABILITY_UNKNOWN: routing could not resolve duties")
        if not set(included) & {"verification", "review"}:
            return na("统一 Runtime 裁剪后无必需 Verification 步骤")
        from .workflow_records import _latest_trusted_verification
        if quick and not any(row['event_type'] == 'VERIFICATION_COMPLETED' for row in events):
            delivery_row = orchestration._delivery_completion_event(facts[1], task_dir, task=facts[0]) if facts else None
            disclosure = orchestration._parse_detail((delivery_row or {}).get('detail_json')).get('unverified_items')
            if delivery_row and disclosure:
                return na('没有执行Verification；真实未实测边界已交付并待Owner明确结单')
            raise ValueError('QUICK_UNVERIFIED_DISCLOSURE_REQUIRED')
        verification, subject, _, _ = _latest_trusted_verification(conn, task_id, task_dir, require_full=not quick)
        return pending([], event_id=int(verification.row["id"]), scope=verification.detail.get("verification_scope", "full"),
                       deferred_checks=verification.detail.get("deferred_checks") or [],
                       reusable=True, note="复用当前范围/主体/原证据仍有效的PASS，不执行测试")
    check("verification", "tp-test-engineer", ["subject", "acceptance", "visual", "database"], verification_check)

    def review_check():
        if included is None:
            raise ValueError("REVIEW_APPLICABILITY_UNKNOWN: routing could not resolve duties")
        if "review" not in included:
            return na("统一 Runtime 未要求代码复审")
        if verification is None:
            raise ValueError("REVIEW_BINDING_UNKNOWN: current verification missing/invalid; do not re-run review speculatively")
        from .workflow_records import _latest_trusted_code_review
        reviewed = _latest_trusted_code_review(conn, task_id, task_dir=task_dir, subject_digest=subject,
            change_set_id=str((snapshot or {}).get("content_digest") or ""), verification_event_id=int(verification.row["id"]))
        return pending([], event_id=int(reviewed.row["id"]), reusable=True)
    check("review", "tp-code-reviewer", ["verification"], review_check)

    def stages_check():
        if included is None or facts is None:
            raise ValueError("STAGE_DUTIES_UNKNOWN: no resolved pipeline")
        stage_events = facts[1]
        if quick:
            development = orchestration._development_change_set_binding(stage_events, task=facts[0])
            return pending([] if development else ['CHANGE_SET_REQUIRED'],
                           steps=[{'stage': 'development', 'event_id': (development or {}).get('event', {}).get('id')}])
        rows = [{"stage": s, "event_id": (orchestration._stage_completion_event(s, stage_events) or {}).get("id")}
                for s in included if s not in {"verification", "review", "delivery"}]
        issues = []
        for row in rows:
            if row["event_id"]:
                continue
            if row["stage"] == "architecture_review":
                gap, review_issues = _architecture_review_gap(conn, task_id, task_dir, stage_events)
                row.update(gap)
                issues.extend(review_issues)
            else:
                issues.append(f"STAGE_RECORD_MISSING: {row['stage']}")
        return pending(issues, steps=rows)
    check("stage_records", "tp-software-lifecycle", ["route"], stages_check)

    def temp_check():
        from .temp_artifacts import records_for_task, summarize_records
        records = records_for_task(task_id=task_id, project_id=task["project_id"])
        return pending(delivery_contract.validate_task_temp_artifacts(records), **summarize_records(records))
    check("temporary_artifacts", "tp-integration-engineer", [], temp_check)

    delivery = None
    def delivery_check():
        nonlocal delivery
        if facts is None or included is None:
            raise ValueError("DELIVERY_APPLICABILITY_UNKNOWN: routing facts unavailable")
        delivery = orchestration._delivery_completion_event(facts[1], task_dir, task=facts[0])
        return pending([] if delivery else ["DELIVERY_NOT_CURRENT: no current READY result; fix prerequisites then converge"],
                       event_id=int(delivery["id"]) if delivery else None, reusable=bool(delivery))
    check("delivery", "tp-integration-engineer", ["work", "integration_candidate", "subject", "acceptance", "database", "verification", "review", "temporary_artifacts"], delivery_check)

    # One Request/Result carries the task-scoped Knowledge decisions and the
    # integration-triggered Memory assessment; no new phase or Memory ledger.
    adopted = bool(delivery and orchestration._parse_detail(delivery.get("detail_json")).get("closeout_schema") == SCHEMA)
    request = orchestration._knowledge_request_for_delivery(events, delivery)
    resolved = None
    def knowledge_check():
        nonlocal resolved
        if quick:
            return na('quick按需使用Knowledge，不生成强制收敛结果')
        if delivery is None:
            return pending(["KNOWLEDGE_INPUT_PENDING: final delivery candidate is not fixed"])
        if request is None:
            return pending(["KNOWLEDGE_ASSESSMENT_NOT_RECORDED: rerun delivery converge to bind Task inputs"]) if adopted else na("旧交付记录未请求 Knowledge；未将空信号认作已完成提炼")
        from .knowledge import convergence
        if adopted and not convergence.current_request(request, events, task_dir, facts[0] if facts else None):
            current_index = convergence.load_index(conn, task_id, task_dir,
                orchestration._parse_detail(delivery.get("detail_json")))
            return pending(["KNOWLEDGE_INPUT_CHANGED_OR_INCOMPLETE: inspect task-inputs then refresh delivery request",
                            *(current_index.get("issues") or [])])
        resolved = orchestration._knowledge_result_for_request(events, request, task_dir, task=facts[0] if facts else None)
        detail = resolved["detail"] if resolved else {}
        return pending([] if resolved else ["KNOWLEDGE_RESULT_MISSING_OR_STALE"],
                       request_event_id=request["event"]["id"], result_event_id=resolved["event"]["id"] if resolved else None,
                       input_digest=detail.get("input_digest"), knowledge_disposition=detail.get("knowledge_disposition"),
                       targets=[item.get("knowledge_ref") for item in detail.get("knowledge_results", []) if item.get("knowledge_ref")])
    check("knowledge", "tp-knowledge", ["delivery"], knowledge_check)
    def memory_check():
        if quick:
            return na('quick按需使用Memory，不生成强制评估事实')
        if not adopted and delivery is not None:
            return na("旧交付记录没有 Memory 收敛契约，不追补或伪造历史评估")
        if delivery is None:
            return {"status": "PENDING", "pending_kind": "dependency", "blocked_by": "delivery",
                    "issues": ["DEPENDENCY_PENDING: delivery", "MEMORY_INPUT_PENDING: final delivery candidate is not fixed"]}
        if resolved is None:
            return {"status": "PENDING", "pending_kind": "dependency", "blocked_by": "knowledge",
                    "issues": ["DEPENDENCY_PENDING: knowledge",
                               "MEMORY_ASSESSMENT_NOT_RECORDED: knowledge convergence has not recorded an assessment yet"]}
        if not resolved["detail"].get("memory_assessment"):
            return {"status": "PENDING", "pending_kind": "registration",
                    "issues": ["MEMORY_ASSESSMENT_NOT_RECORDED: assess each step; persistence is a separate result"]}
        from .knowledge.convergence import memory_status
        root = (facts[0] if facts else {}).get("project_root_path")
        outcome = memory_status(resolved["detail"]["memory_assessment"], Path(root) if root else None)
        return pending([], result_event_id=resolved["event"]["id"], **outcome)
    check("memory", "tp-integration-engineer", ["knowledge"], memory_check)

    by_id = {row["id"]: row for row in result["checks"]}
    for row in result["checks"]:
        if not row["required"] or row["status"] in {"PASS", "NOT_APPLICABLE", "TERMINAL"}:
            continue
        if not row["issues"]:
            row["issues"] = ["required check has no conclusive result"]
        result["blockers"].extend(f"{row['id'].upper()}: {issue}" for issue in row["issues"])
        if row["status"] == "UNKNOWN":
            result["unknowns"].append(row["id"])
            result.setdefault("unknown_sources", []).append(
                {"check_id": row["id"], "issues": list(row["issues"]),
                 "impact": "unconfirmed; cannot be treated as satisfied"})
        unresolved = [dep for dep in row["depends_on"] if by_id.get(dep, {}).get("status") not in {"PASS", "NOT_APPLICABLE", "TERMINAL"}]
        result["next_actions"].append({"check_id": row["id"], "responsibility": row["responsibility"],
                                       "depends_on": unresolved, "actionable_now": not unresolved,
                                       "issues": row["issues"]})
    result["nodes"] = _explain_nodes(result, by_id, included=result.get("included_stages"),
                                     quick=quick, acceptance=acceptance, verification=verification,
                                     route=result.get("route"), task=task, conn=conn)
    current, downstream = [], []
    for node in result["nodes"]:
        if node["status"] in {"CURRENT_GAP", "OWNER_PENDING", "REGISTRATION_PENDING"}:
            current.append({"node": node["id"], "status": node["status"], "issues": node["issues"],
                            "responsibility": node["responsibility"]})
        elif node["status"] in {"NOT_YET_DUE", "BLOCKED_BY_UPSTREAM"}:
            downstream.append({"node": node["id"], "status": node["status"], "issues": node["issues"],
                               "responsibility": node["responsibility"]})
    result["current_stage_blockers"] = current
    result["downstream_closeout_pending"] = downstream
    result["ready"] = not result["blockers"]
    return result


def _node(node_id, title, status, *, issues=None, responsibility=None, facts=None):
    return {"id": node_id, "title": title, "status": status, "issues": list(issues or []),
            "responsibility": responsibility, "facts": facts or {}}


def technical_verification_fact(conn, task_id: str, task_dir: Path) -> dict[str, Any]:
    """Whether a current technical verification exists and is reusable (no full duty)."""
    from .workflow_records import _latest_trusted_verification
    try:
        verified, _, _, _ = _latest_trusted_verification(conn, task_id, task_dir, require_full=False)
    except ValueError as exc:
        return {"reusable": False, "issues": [f"{type(exc).__name__}: {exc}"]}
    return {"reusable": True, "event_id": int(verified.row["id"]),
            "scope": verified.detail.get("verification_scope", "full"),
            "deferred_checks": verified.detail.get("deferred_checks") or []}


def _step_completion_gate(conn, task_row, facts, step) -> None:
    """The read-only subset of the real ``work step --action complete`` gate.

    Mirrors ``execution_cmd.record_step`` for the checks that can be evaluated
    without writing: ACTIVE status, the scoped step authority, the Work/Fix guard
    and open participations. Task-state and plan-version checks are included only
    as far as they are read-only facts. Nothing is advanced here.
    """
    from .security_authority import check_step
    from .work_units import step_guard
    if step["status"] != "ACTIVE":
        raise ValueError(f"STEP_TRANSITION_INVALID: {step['status']} -> complete")
    check_step(conn, task_row["task_id"], step)
    step_guard(conn, task_row, facts, step, "complete")
    if any(p["step_id"] == step["id"] and p["ended_at"] is None for p in facts["participations"]):
        raise ValueError("STEP_HAS_OPEN_PARTICIPATIONS: end or hand off the recorded sessions first")


def step_completion_fact(conn, task, task_dir: Path, *, step_id: str | None = None) -> dict[str, Any]:
    """Read-only step-completion diagnosis using the real completion gate.

    Never advances a step. A WAITING step is not directly completable; a COMPLETED
    step is history. A Fix-linked step keeps the guard's own full-verification
    requirement, so this does not invent a new full duty. ``step_id`` selects the
    actual step being explained (the verification node passes its own planned
    verification step) instead of assuming any current step is VERIFY.
    """
    from .execution_cmd import load_current
    try:
        task_row, facts = load_current(conn, task["task_id"])
    except ValueError as exc:
        return {"applicable": False, "status": "UNKNOWN", "issues": [f"{type(exc).__name__}: {exc}"]}
    if facts.get("plan") is None:
        return {"applicable": False, "status": "NOT_APPLICABLE",
                "issues": ["no explicit plan; legacy routing applies"]}
    if step_id is None:
        step = facts.get("current_step")
    else:
        step = next((s for s in facts["steps"] if s["id"] == step_id), None)
        if step is None:
            return {"applicable": False, "status": "UNKNOWN", "step_id": step_id,
                    "issues": [f"STEP_NOT_IN_PLAN: {step_id}"]}
    if step is None:
        completed = [s["id"] for s in facts["steps"] if s["status"] == "COMPLETED"]
        return {"applicable": False, "status": "NOT_APPLICABLE",
                "completed_step_ids": completed,
                "issues": ["no active step; completed steps are history"]}
    if step["status"] == "COMPLETED":
        return {"applicable": False, "status": "NOT_APPLICABLE", "step_id": step["id"],
                "issues": ["step already completed; do not re-complete history"]}
    if step["status"] == "WAITING":
        return {"applicable": True, "status": "PENDING", "step_id": step["id"],
                "wait_reason": step.get("wait_reason"),
                "issues": ["step is WAITING; resume along its existing condition before completing"]}
    try:
        _step_completion_gate(conn, task_row, facts, step)
    except ValueError as exc:
        return {"applicable": True, "status": "PENDING", "step_id": step["id"],
                "issues": [f"{type(exc).__name__}: {exc}"]}
    return {"applicable": True, "status": "READY", "step_id": step["id"],
            "issues": ["step prerequisites satisfied; complete only after its actual work"]}


def _verification_step(conn, task) -> dict[str, Any]:
    """The actual verification step in plan order, not the first current step.

    A plan may hold several verification steps; the applicable one is the first
    verification-phase step that is not yet completed, else the last one, whose
    completion is history.
    """
    from .execution import read_execution
    try:
        facts = read_execution(conn, task)
    except (ValueError, KeyError, TypeError) as exc:
        return {"step": None, "issues": [f"{type(exc).__name__}: {exc}"]}
    steps = [s for s in facts.get("steps") or [] if s.get("phase") == "verification"]
    if not steps:
        return {"step": None, "issues": []}
    pending = next((s for s in steps if s["status"] != "COMPLETED"), None)
    return {"step": pending or steps[-1], "issues": []}


def _explain_nodes(result, by_id, *, included, quick, acceptance, verification, route, task, conn):
    """Twelve fixed explanation nodes over existing readers; never another gate.

    Statuses come from the same checks/routing this preflight already executed.
    An unconfirmed fact stays UNKNOWN; an unstarted later stage is NOT_YET_DUE and
    never becomes a current blocker. NOT_APPLICABLE follows the resolved mode.
    """
    def status_of(key):
        row = by_id.get(key) or {}
        return row.get("status"), list(row.get("issues") or []), row.get("responsibility")

    def node_for(key, title, responsibility, *, missing_status="CURRENT_GAP"):
        status, issues, owner = status_of(key)
        owner = owner or responsibility
        if status in {"PASS", "TERMINAL"}:
            return _node(key, title, "REUSABLE", responsibility=owner)
        if status == "NOT_APPLICABLE":
            return _node(key, title, "NOT_APPLICABLE", responsibility=owner)
        if status == "UNKNOWN":
            return _node(key, title, "UNKNOWN", issues=issues, responsibility=owner)
        if missing_status == "REGISTRATION_PENDING":
            return _node(key, title, "REGISTRATION_PENDING", issues=issues, responsibility=owner)
        return _node(key, title, missing_status, issues=issues, responsibility=owner)

    stages = set(included or [])
    # The actual routed professional operation, not a node's mere presence in the
    # pipeline: a later obligation is NOT_YET_DUE until routing reaches it. While a
    # step is still open, that step's own phase is the current obligation even if
    # routing already names the following stage.
    alignment = (route or {}).get("plan_route_alignment") or {}
    operation = str(alignment.get("operation_stage") or (route or {}).get("next_stage") or "")
    stage_order = ("requirement", "architecture", "architecture_review", "planning",
                   "development", "verification", "review", "delivery", "complete")

    def rank(stage: str) -> int | None:
        try:
            return stage_order.index(stage)
        except ValueError:
            return None

    from .execution import read_execution
    try:
        plan_steps = list(read_execution(conn, task).get("steps") or [])
    except (ValueError, KeyError, TypeError):
        plan_steps = []
    current_id = alignment.get("current_step")
    current_phase = next((s["phase"] for s in plan_steps if s["id"] == current_id), None)
    if (current_phase and operation != "complete"
            and (rank(operation) is None or rank(current_phase) < rank(operation))):
        operation = current_phase

    def reached(stage: str) -> bool:
        if operation == "complete":
            return True
        here, there = rank(operation), rank(stage)
        return here is not None and there is not None and here >= there

    stage_row = by_id.get("stage_records") or {}
    stage_steps = (stage_row.get("facts") or {}).get("steps") or []

    def stage_node(stage: str) -> dict | None:
        return next((s for s in stage_steps if s.get("stage") == stage), None)

    requirement = stage_node("requirement")
    if "requirement" in stages and requirement is not None:
        nodes = [_node("requirement_scope", "需求/范围",
                       "REUSABLE" if requirement.get("event_id") else "CURRENT_GAP",
                       issues=[] if requirement.get("event_id") else ["STAGE_RECORD_MISSING: requirement"],
                       responsibility="tp-requirement-analyst",
                       facts={"event_id": requirement.get("event_id")})]
    else:
        nodes = [_node("requirement_scope", "需求/范围",
                       "REUSABLE" if quick else "NOT_APPLICABLE",
                       responsibility="tp-requirement-analyst",
                       facts={"note": "quick 模式将需求并入任务；无独立阶段记录"} if quick else {})]

    if "architecture_review" in stages:
        arch = stage_node("architecture_review")
        arch_issues = [i for i in (stage_row.get("issues") or []) if "ARCHITECTURE" in i]
        if arch is None:
            nodes.append(_node("architecture_review", "架构复审", "NOT_YET_DUE",
                               responsibility="tp-software-architect"))
        else:
            nodes.append(_node("architecture_review", "架构复审",
                               "REUSABLE" if not arch_issues else "CURRENT_GAP",
                               issues=arch_issues, responsibility="tp-software-architect",
                               facts={key: arch.get(key) for key in (
                                   "recorded_event_id", "recorded_decision", "status", "localized_scope")
                                   if arch.get(key) is not None}))
    else:
        nodes.append(_node("architecture_review", "架构复审", "NOT_APPLICABLE"))

    nodes.append(node_for("subject", "开发", "tp-development-engineer"))
    nodes.append(node_for("visual", "页面验证", "tp-test-engineer", missing_status="REGISTRATION_PENDING"))
    # Current technical verification: a reusable technical result must not look like
    # a missing full verification. The full duty stays with delivery/closeout.
    technical = technical_verification_fact(conn, result["task_id"], Path(result["task_dir"]))
    if technical["reusable"]:
        nodes.append(_node("verification", "技术验证", "REUSABLE",
                           responsibility="tp-test-engineer",
                           facts={"event_id": technical["event_id"], "scope": technical["scope"]}))
    elif _is_prerequisite_error(technical["issues"][0] if technical["issues"] else ""):
        nodes.append(_node("verification", "技术验证", "CURRENT_GAP", issues=technical["issues"],
                           responsibility="tp-test-engineer"))
    else:
        nodes.append(_node("verification", "技术验证", "UNKNOWN", issues=technical["issues"],
                           responsibility="tp-test-engineer"))
    deferred = list((technical.get("deferred_checks") or []) if technical["reusable"] else [])
    nodes.append(_node("deferred_checks", "延期",
                       "OWNER_DEFERRED" if deferred else "NOT_APPLICABLE",
                       responsibility="human_owner",
                       facts={"count": len(deferred),
                              "note": "只有当前有效验证/正式AC处置中的条目；无正式登记时不宣称不存在用户延期决定"}))
    # The VERIFY node explains the actual verification step, never whichever step
    # happens to be current. A completed verification step stays history.
    located = _verification_step(conn, task)
    verification_step = located["step"]
    if verification_step is None:
        nodes.append(_node("verify_step", "VERIFY", "NOT_APPLICABLE", issues=located["issues"],
                           responsibility="tp-test-engineer",
                           facts={"note": "显式计划中没有验证步骤"} if not located["issues"] else {}))
    elif verification_step["status"] == "COMPLETED":
        nodes.append(_node("verify_step", "VERIFY", "NOT_APPLICABLE",
                           responsibility="tp-test-engineer",
                           facts={"step_id": verification_step["id"],
                                  "note": "步骤已完成，属于历史；不要求再次完成"}))
    elif verification_step["status"] == "PLANNED":
        nodes.append(_node("verify_step", "VERIFY", "NOT_YET_DUE",
                           responsibility="tp-test-engineer",
                           facts={"step_id": verification_step["id"],
                                  "note": "验证步骤尚未开始"}))
    else:
        step = step_completion_fact(conn, task, Path(result["task_dir"]),
                                    step_id=verification_step["id"])
        nodes.append(_node("verify_step", "VERIFY", {
            "READY": "REUSABLE", "PENDING": "CURRENT_GAP", "NOT_APPLICABLE": "NOT_APPLICABLE",
        }.get(step["status"], "UNKNOWN"), issues=step["issues"],
            responsibility="tp-test-engineer",
            facts={key: step[key] for key in ("step_id", "wait_reason") if step.get(key)}))
    # CODE-REVIEW is the current obligation once routing reaches it; before that it
    # is a later obligation, and while verification is unusable it is upstream-blocked.
    review_status, review_issues, review_owner = status_of("review")
    if review_status in {"PASS", "TERMINAL"}:
        nodes.append(_node("review", "CODE-REVIEW", "REUSABLE", responsibility=review_owner or "tp-code-reviewer"))
    elif review_status == "NOT_APPLICABLE":
        nodes.append(_node("review", "CODE-REVIEW", "NOT_APPLICABLE", responsibility="tp-code-reviewer"))
    elif not technical["reusable"] and not reached("review"):
        nodes.append(_node("review", "CODE-REVIEW", "BLOCKED_BY_UPSTREAM", issues=review_issues,
                           responsibility=review_owner or "tp-code-reviewer",
                           facts={"blocked_by": "verification"}))
    elif reached("review"):
        nodes.append(_node("review", "CODE-REVIEW", "CURRENT_GAP", issues=review_issues,
                           responsibility=review_owner or "tp-code-reviewer",
                           facts={"note": "当前路由已到代码复审"}))
    else:
        nodes.append(_node("review", "CODE-REVIEW", "NOT_YET_DUE", issues=review_issues,
                           responsibility=review_owner or "tp-code-reviewer"))
    # AC 汇总是整任务结单义务：只有路由到 complete 时才是当前缺口，之前属于后续义务。
    # A genuine UNKNOWN stays visible at any stage; it is never deferred away.
    acceptance_status, acceptance_issues, acceptance_owner = status_of("acceptance")
    if acceptance_status in {"PASS", "TERMINAL"}:
        nodes.append(_node("acceptance", "AC汇总", "REUSABLE", responsibility=acceptance_owner or "tp-test-engineer"))
    elif acceptance_status == "NOT_APPLICABLE":
        nodes.append(_node("acceptance", "AC汇总", "NOT_APPLICABLE", responsibility="tp-test-engineer"))
    elif acceptance_status == "UNKNOWN":
        nodes.append(_node("acceptance", "AC汇总", "UNKNOWN", issues=acceptance_issues,
                           responsibility=acceptance_owner or "tp-test-engineer"))
    elif operation == "complete":
        nodes.append(node_for("acceptance", "AC汇总", "tp-test-engineer"))
    else:
        nodes.append(_node("acceptance", "AC汇总", "NOT_YET_DUE", issues=acceptance_issues,
                           responsibility=acceptance_owner or "tp-test-engineer",
                           facts={"note": "整任务验收在交付/结单阶段到期；当前专业阶段不受其阻塞"}))
    delivery_status, delivery_issues, delivery_owner = status_of("delivery")
    if delivery_status in {"PASS", "TERMINAL"}:
        nodes.append(_node("delivery", "DELIVER", "REUSABLE", responsibility=delivery_owner or "tp-integration-engineer"))
    elif delivery_status == "NOT_APPLICABLE":
        nodes.append(_node("delivery", "DELIVER", "NOT_APPLICABLE", responsibility="tp-integration-engineer"))
    elif delivery_status == "UNKNOWN":
        nodes.append(_node("delivery", "DELIVER", "UNKNOWN", issues=delivery_issues,
                           responsibility=delivery_owner or "tp-integration-engineer"))
    elif reached("delivery") or operation == "complete":
        nodes.append(_node("delivery", "DELIVER", "CURRENT_GAP", issues=delivery_issues,
                           responsibility=delivery_owner or "tp-integration-engineer",
                           facts={"note": "当前路由已到交付"}))
    else:
        nodes.append(_node("delivery", "DELIVER", "NOT_YET_DUE", issues=delivery_issues,
                           responsibility=delivery_owner or "tp-integration-engineer"))
    if quick:
        nodes.append(_node("knowledge_memory", "Knowledge/Memory", "NOT_APPLICABLE"))
    else:
        k_status, k_issues, _ = status_of("knowledge")
        m_status, m_issues, _ = status_of("memory")
        if "UNKNOWN" in {k_status, m_status}:
            nodes.append(_node("knowledge_memory", "Knowledge/Memory", "UNKNOWN",
                               issues=k_issues + m_issues, responsibility="tp-knowledge"))
        elif k_status in {"PASS", "TERMINAL"} and m_status in {"PASS", "TERMINAL", "NOT_APPLICABLE"}:
            nodes.append(_node("knowledge_memory", "Knowledge/Memory", "REUSABLE",
                               responsibility="tp-knowledge"))
        else:
            nodes.append(_node("knowledge_memory", "Knowledge/Memory", "NOT_YET_DUE",
                               issues=k_issues + m_issues, responsibility="tp-knowledge"))
    nodes.append(_node("closeout", "结单",
                       "NOT_YET_DUE" if result.get("blockers") else "REUSABLE",
                       responsibility="tp-software-lifecycle",
                       facts={"blocker_count": len(result.get("blockers") or [])}))
    return nodes
