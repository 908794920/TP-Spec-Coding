"""Read-only explanation of the current verification step, using existing gates."""
from __future__ import annotations

import json
from pathlib import Path

from . import closeout, event_policies, execution, record_first, work_units


def collect(conn, task, directory: Path, *, db_path: str, base_root=None):
    plan = execution.read_execution(conn, task)
    step = next((s for s in plan["steps"] if s["status"] != "COMPLETED"), None)
    if not step or step["phase"] != "verification":
        return {"read_only": True, "applicable": False,
                "reason": "No current explicit verification step; use workflow routing."}
    report = closeout.collect(conn, task, directory, db_path=db_path, base_root=base_root)
    task_id = task["task_id"]
    current = []

    def check(key, action, fn):
        row = {"id": key, "status": "SATISFIED", "issues": [], "next_action": action}
        try:
            row["facts"] = fn() or {}
        except Exception as exc:
            row.update(status="UNMET", issues=[f"{type(exc).__name__}: {exc}"])
        current.append(row)

    for row in report["checks"]:
        if row["id"] in {"identity", "subject", "visual", "integration_candidate"}:
            current.append({**row, "status": "SATISFIED" if row["status"] in {"PASS", "NOT_APPLICABLE"} else "UNMET",
                            "next_action": {"identity": "Resolve workspace/contract identity.",
                                "subject": "Bind the actual current full product scope.",
                                "visual": "Record the actual candidate-bound page witness or visual manifest; do not accept whole technical ACs.",
                                "integration_candidate": "Receive/rebind current Work results without replacing old evidence."}[row["id"]]})

    def visual_declaration():
        from .yaml_checks import check_acceptance_with_owner
        path = directory / "acceptance.md"
        if not path.is_file():
            return {"required": False}
        value = check_acceptance_with_owner(path.read_text(encoding="utf-8-sig"), conn=conn,
            task_id=task_id, task_dir=directory, enforce_completion=False,
            allow_human_pending=True, require_visual_evidence=True)
        issues = [issue for issue in value.issues if issue.startswith("page_verification.visual")]
        if issues:
            raise ValueError("VISUAL_VERIFICATION_INVALID: " + "; ".join(issues))
        return {"note": "Same visual declaration gate as full verify; pending technical ACs are not accepted here."}
    check("verification_declaration", "Resolve the declared visual coverage only.", visual_declaration)

    def step_authority():
        from . import security_authority
        from .execution_cmd import load_current
        load_current(conn, task_id)
        security_authority.check_step(conn, task_id, step)
    check("step_authority", "Resolve the scoped step authority issue; a plan is not permission.", step_authority)

    def authority():
        from . import security_authority
        from .change_set import capture_bound_product
        development = record_first._latest_development_change_set(conn, task_id)
        context = {"effect_scope": "regression"}
        if development:
            snapshot = capture_bound_product(development["detail"], directory, repo_roots=development["repo_roots"])
            context["paths"] = security_authority.changed_paths(snapshot)
        security_authority.check_effect(conn, task_id,
            security_authority.normalize_context(context), task_dir=directory)
    check("verification_authority", "Resolve the scoped authority issue; a plan is not permission.", authority)

    latest = conn.execute("SELECT * FROM task_event WHERE task_id=? AND event_type='VERIFICATION_COMPLETED' ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
    historical = {}
    if latest:
        try:
            detail = json.loads(latest["detail_json"] or "{}")
            if not isinstance(detail, dict):
                detail = {}
        except (TypeError, ValueError):
            detail = {}
        from .evidence import validate_evidence_path
        mismatches = []
        items = detail.get("evidence_items") or []
        if not isinstance(items, list):
            mismatches.append({"error": "Invalid historical evidence list"})
            items = []
        for item in items:
            if not isinstance(item, dict):
                mismatches.append({"error": "Invalid evidence item in historical event"})
                continue
            checked = validate_evidence_path(directory, item, require_evidence_dir=True)
            if not checked.ok or checked.sha256 != item.get("sha256"):
                mismatches.append({"path": item.get("path"), "recorded_sha256": item.get("sha256"),
                                   "current_sha256": checked.sha256, "error": checked.error})
        historical = {"event_id": latest["id"], "scope": detail.get("verification_scope", "full"),
                      "decision": detail.get("decision"), "subject_current": event_policies.verification_subject_matches(detail, directory),
                      "evidence_mismatches": mismatches,
                      "checks": detail.get("checks", []), "deferred_checks": detail.get("deferred_checks", []),
                      "note": "History alone does not establish current PASS; see full_verification. Re-record only evidence actually revalidated for reuse."}

    def full_verification():
        from .workflow_records import _latest_trusted_verification
        verified, _, _, _ = _latest_trusted_verification(conn, task_id, directory)
        return {"event_id": verified.row["id"], "reusable": True,
                "deferred_checks": verified.detail.get("deferred_checks", [])}
    check("full_verification", "Actual test executor records full verification with applicable technical evidence, page witness and exact deferred checks; no invented execution.", full_verification)

    def completion():
        if step["status"] != "ACTIVE":
            raise ValueError(f"STEP_TRANSITION_INVALID: {step['status']} -> complete")
        work_units.step_guard(conn, task, plan, step, "complete")
        return {"note": "Read-only evaluation; no step advanced."}
    check("step_completion", "Complete only this step after its prerequisites; do not start the next step without authorization.", completion)

    def participants():
        if any(p["step_id"] == step["id"] and p["ended_at"] is None for p in plan["participations"]):
            raise ValueError("STEP_HAS_OPEN_PARTICIPATIONS")
    check("participants", "End or hand off actual open sessions before completing this step.", participants)
    following = next(iter(plan["steps"][plan["steps"].index(step) + 1:]), None)
    for condition in current:
        condition["applies_to"] = "step_completion" if condition["id"] in {"step_authority", "step_completion", "participants"} else "full_verification_record"
    return {"read_only": True, "applicable": True, "step_id": step["id"],
            "next_planned_step": following, "current_conditions": current,
            "ready_to_complete_step": all(c["status"] == "SATISFIED" for c in current if c["applies_to"] == "step_completion"),
            "latest_verification": historical,
            "later_stage_conditions": [{**r, "applies_to": "workflow_routing_and_closeout" if r["id"] == "stage_records" else "delivery_or_closeout", "blocks_current_step": False}
                for r in report["checks"] if r["id"] not in {"identity", "subject", "visual", "integration_candidate", "verification"}],
            "next_step_boundary": "The planned next step and workflow routing are distinct. Stale architecture review may still reroute after VERIFY completes. This check neither starts any review nor accepts its result.",
            "limits": "Registered facts only; not a new test or user acceptance. Later-stage failures do not become verification-step gates. Proposed evidence must still pass task verify validation."}
