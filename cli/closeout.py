# -*- coding: utf-8 -*-
"""Read-only closeout diagnostics over existing Runtime facts, not another workflow.

Each check owns only its evidence/applicability diagnostic. Routing, professional
results, acceptance, Work and temporary-artifact policies remain their own sources.
Unknown required facts are not permission to complete. No repair or cleanup here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import delivery_contract, event_policies, orchestration, record_first

SCHEMA = "tp-spec.closeout/v1"


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


def collect(conn, task, task_dir: Path, *, db_path: str, base_root=None) -> dict[str, Any]:
    task = dict(task)
    task_id, state = task["task_id"], str(task["current_state"])
    result: dict[str, Any] = {"schema": SCHEMA, "task_id": task_id, "state": state,
        "ready": False, "already_terminal": state in record_first.TERMINAL_STATES,
        "checks": [], "blockers": [], "unknowns": [], "acceptance_issues": [], "route": None,
        "next_actions": [], "read_only": True,
        "consistency": "one SQLite read snapshot; files are rechecked, not filesystem-locked",
        "coverage_note": "检查已登记的步骤、范围、AC、人验、数据库操作、证据、Work、临时工件及收敛结果；未知项不会视为通过，不证明未登记业务或真实运行效果。"}
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
            row.update(status="UNKNOWN", issues=[f"{type(exc).__name__}: {exc}"])
        result["checks"].append(row)
        return row

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
        data = summarize_work_items(conn, task)
        issues = list(data["issues"])
        issues.extend(f"WORK_PENDING: {w['item_id']} ({w['status']})" for w in data["items"] if w["status"] != "COMPLETED")
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
        from .yaml_checks import check_acceptance_yaml
        path = task_dir / "acceptance.md"
        if not path.is_file():
            raise ValueError("ACCEPTANCE_MISSING: explicit AC or no_acceptance_required declaration is needed")
        acceptance = check_acceptance_yaml(path.read_text(encoding="utf-8-sig"), enforce_completion=True, allow_human_pending=False)
        issues = list(acceptance.issues)
        issues.extend(record_first.acceptance_truth_issues(conn, task_id, task_dir))
        result["acceptance_issues"] = list(dict.fromkeys(issues))
        return pending(result["acceptance_issues"], pending_rows=acceptance.pending_rows, verdict_counts=acceptance.verdict_counts)
    check("acceptance", "tp-test-engineer", [], acceptance_check)

    def owner_check():
        if acceptance is None:
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
            raise ValueError("DATABASE_SCOPE_UNKNOWN: acceptance input is unreadable")
        issues, items = delivery_contract.database_disposition(task_dir, acceptance)
        return pending(issues, operations=acceptance.database_operations, evidence_items=items)
    check("database", "tp-database-engineer", ["acceptance"], database_check)

    snapshot = None
    binding = None
    subject = ""
    def subject_check():
        nonlocal snapshot, binding, subject
        from .change_set import capture_change_set, same_bound_product_content
        from .digest import compute_verification_subject_digest
        subject = compute_verification_subject_digest(task_dir)
        binding = record_first._latest_development_change_set(conn, task_id)
        if not binding or not binding.get("repo_roots") or not binding.get("change_set_id"):
            raise ValueError("CHANGE_SET_REQUIRED: no explicit development product binding")
        snapshot = capture_change_set(binding["repo_roots"])
        issues = []
        if not same_bound_product_content(binding["detail"], snapshot):
            issues.append("CHANGE_SET_STALE: current product differs from the recorded development candidate")
        try:
            delivery_contract.require_full_scope(conn, task_id, binding["detail"], development_event_id=int(binding["event_id"]))
        except ValueError as exc:
            issues.append(str(exc))
        return pending(issues, subject_digest=subject, change_set_id=snapshot["content_digest"],
                       development_event_id=binding["event_id"])
    check("subject", "tp-development-engineer", ["identity"], subject_check)

    def visual_check():
        if acceptance is None:
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
        nonlocal verification
        if included is None:
            raise ValueError("VERIFICATION_APPLICABILITY_UNKNOWN: routing could not resolve duties")
        if not set(included) & {"verification", "review"}:
            return na("统一 Runtime 裁剪后无必需 Verification 步骤")
        from .workflow_records import _latest_trusted_verification
        verification, _, _, _ = _latest_trusted_verification(conn, task_id, task_dir)
        return pending([], event_id=int(verification.row["id"]), scope=verification.detail.get("verification_scope", "full"),
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
        rows = [{"stage": s, "event_id": (orchestration._stage_completion_event(s, stage_events) or {}).get("id")}
                for s in included if s not in {"verification", "review", "delivery"}]
        return pending([f"STAGE_RECORD_MISSING: {r['stage']}" for r in rows if not r["event_id"]], steps=rows)
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
        if delivery is None:
            return pending(["KNOWLEDGE_INPUT_PENDING: final delivery candidate is not fixed"])
        if request is None:
            return pending(["KNOWLEDGE_ASSESSMENT_NOT_RECORDED: rerun delivery converge to bind Task inputs"]) if adopted else na("旧交付记录未请求 Knowledge；未将空信号认作已完成提炼")
        from .knowledge import convergence
        if adopted and not convergence.current_request(request, events, task_dir, facts[0] if facts else None):
            return pending(["KNOWLEDGE_INPUT_CHANGED_OR_INCOMPLETE: inspect task-inputs then refresh delivery request"])
        resolved = orchestration._knowledge_result_for_request(events, request, task_dir, task=facts[0] if facts else None)
        detail = resolved["detail"] if resolved else {}
        return pending([] if resolved else ["KNOWLEDGE_RESULT_MISSING_OR_STALE"],
                       request_event_id=request["event"]["id"], result_event_id=resolved["event"]["id"] if resolved else None,
                       input_digest=detail.get("input_digest"), knowledge_disposition=detail.get("knowledge_disposition"),
                       targets=[item.get("knowledge_ref") for item in detail.get("knowledge_results", []) if item.get("knowledge_ref")])
    check("knowledge", "tp-knowledge", ["delivery"], knowledge_check)
    def memory_check():
        if not adopted and delivery is not None:
            return na("旧交付记录没有 Memory 收敛契约，不追补或伪造历史评估")
        if not resolved or not resolved["detail"].get("memory_assessment"):
            return {"status": "UNKNOWN", "issues": ["MEMORY_ASSESSMENT_NOT_RECORDED: assess each step; persistence is a separate result"]}
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
        unresolved = [dep for dep in row["depends_on"] if by_id.get(dep, {}).get("status") not in {"PASS", "NOT_APPLICABLE", "TERMINAL"}]
        result["next_actions"].append({"check_id": row["id"], "responsibility": row["responsibility"],
                                       "depends_on": unresolved, "actionable_now": not unresolved,
                                       "issues": row["issues"]})
    result["ready"] = not result["blockers"]
    return result
