# -*- coding: utf-8 -*-
"""Video export, inspection and delivery facts on the existing Task ledger."""
from __future__ import annotations

import json
from pathlib import Path
import uuid

from . import db, execution, recording, video_policy as policy, work_units
from .digest import compute_verification_subject_digest
from .evidence import validate_evidence_path
from .task_coordinator import task_domain

EXPORT = "VIDEO_EXPORT_RECORDED"
QC = "VIDEO_QC_RECORDED"
DELIVERY = "VIDEO_DELIVERY_RECORDED"
OPERATIONS = {"video-export": EXPORT, "video-qc": QC, "video-delivery": DELIVERY}
ACTORS = {
    EXPORT: {policy.PRODUCER, policy.EDITOR},
    QC: policy.ROLES,
    DELIVERY: {policy.PRODUCER},
}
FIX_CHECK_ALIASES = {
    "voice": "audio", "dialogue": "audio", "bgm": "audio", "sfx": "audio", "music": "audio", "sound": "audio",
    "picture": "visual",
}


def trusted(row):
    row = dict(row)
    detail = execution.detail_of(row)
    body = detail.get("video_payload")
    if (row.get("actor_role") not in ACTORS.get(row.get("event_type"), set())
            or not execution._trusted(row, detail, "video_records")
            or detail.get("schema_version") != row.get("workflow_version")
            or detail.get("domain") != "video"
            or not isinstance(body, dict) or detail.get("video_digest") != execution.digest(body)):
        return None
    return {**body, "event_id": row["id"], "actor": row["actor_role"],
            "agent": row["actor_agent"], "created_at": row["created_at"]}


def _records(rows, event_type):
    for row in reversed(rows):
        if row["event_type"] == event_type:
            record = trusted(row)
            if record is None:
                raise ValueError(f"VIDEO_FACT_INVALID: {row['id']} ({event_type})")
            yield record


def _evidence(task_dir, ref):
    checked = validate_evidence_path(task_dir, ref, require_evidence_dir=True)
    if not checked.ok:
        raise ValueError(f"VIDEO_EVIDENCE_INVALID: {checked.error}")
    if isinstance(ref, dict) and ref != checked.item:
        raise ValueError(f"VIDEO_EVIDENCE_CHANGED: {checked.path}")
    return checked.item


def _read_json(task_dir, ref):
    item = _evidence(task_dir, ref)
    try:
        raw = json.loads((task_dir / item["path"]).read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise ValueError(f"VIDEO_JSON_INVALID: {item['path']}") from exc
    if _evidence(task_dir, item) != item:
        raise ValueError(f"VIDEO_EVIDENCE_CHANGED: {item['path']}")
    return raw, item


def _text(value, field):
    return work_units._text(value, field)


def _strings(value, field):
    return work_units._strings(value, field)


def _workspace(conn, task):
    row = conn.execute("SELECT root_path FROM project WHERE project_id=?", (task["project_id"],)).fetchone()
    if row is None or not row["root_path"]:
        raise ValueError("VIDEO_WORKSPACE_UNAVAILABLE")
    return Path(row["root_path"]).resolve(strict=True)


def _export_files(conn, task, export, root, paths, *, check_content=True):
    units = work_units.read(conn, task["task_id"])
    if units["issues"]:
        raise ValueError("; ".join(units["issues"]))
    selected_outputs = {}
    selected_work = {item["work_item"] for item in export["selected"] if item.get("work_item")}
    if selected_work - export["receipts"].keys():
        raise ValueError("VIDEO_SELECTED_WORK_RECEIPT_REQUIRED")
    for wid, eid in export["receipts"].items():
        unit = units["units"].get(wid)
        if (not unit or not unit["receipt"] or unit["receipt"]["event_id"] != eid
                or work_units.checked_item(conn, task["task_id"], wid)["status"] != "COMPLETED"):
            raise ValueError(f"VIDEO_WORK_RECEIPT_NOT_CURRENT: {wid}")
        if check_content:
            work_units.validate_result(conn, task["task_id"], unit)
        selected = [item for item in export["selected"] if item.get("work_item") == wid]
        if not selected:
            continue
        work_root = work_units.media_work_root(conn, task["task_id"], unit)
        recorded = unit["result"]["result"]["outputs"]
        for item in selected:
            expected = next((output for output in recorded if work_root / output["path"] == root / item["path"]), None)
            if expected is None:
                raise ValueError(f"VIDEO_SELECTED_WORK_OUTPUT_MISMATCH: {wid} / {item['path']}")
            selected_outputs.setdefault(item["path"], []).append((work_root, unit, expected))

    def check_path(path, resolved):
        for work_root, unit, _ in selected_outputs.get(path, []):
            work_units.check_media_output_path(work_root, resolved, unit)

    files = policy.media_files(root, paths, hash_content=check_content, check_work_path=check_path)
    for file in files:
        for _, unit, expected in selected_outputs.get(file["path"], []):
            if any(file[key] != expected[key] for key in file.keys() - {"path"}):
                raise ValueError(f"VIDEO_SELECTED_WORK_OUTPUT_MISMATCH: {unit['item_id']} / {file['path']}")
    return files


def _prepare_export(conn, task, task_dir, manifest):
    raw, evidence = _read_json(task_dir, manifest)
    raw = work_units.authority.obj(raw, {"version", "media_root", "main", "attachments", "selected", "receipts",
        "affected", "required_checks", "independent_review_required"}, "video manifest")
    version = _text(raw.get("version"), "version")
    media_root = _text(raw.get("media_root"), "media_root")
    root = policy.media_root(_workspace(conn, task), media_root)
    main = _text(raw.get("main"), "main")
    attachments = work_units.paths(raw.get("attachments", []))
    selected = raw.get("selected", [])
    if not isinstance(selected, list):
        raise ValueError("VIDEO_SELECTED_INVALID: expected a list")
    selection = []
    for item in selected:
        item = work_units.authority.obj(item, {"path", "role", "version", "work_item"}, "selected asset")
        entry = {key: _text(item.get(key), key) for key in ("path", "role", "version")}
        if "work_item" in item:
            entry["work_item"] = _text(item["work_item"], "work_item")
        selection.append(entry)
    receipts = raw.get("receipts", {})
    if not isinstance(receipts, dict) or any(not wid.strip() or type(eid) is not int or eid < 1
                                            for wid, eid in receipts.items()):
        raise ValueError("VIDEO_RECEIPTS_INVALID: map each required Work ID to its exact receipt event")
    required_checks = _strings(raw.get("required_checks", []), "required_checks")
    independent = raw.get("independent_review_required", False)
    if type(independent) is not bool:
        raise ValueError("VIDEO_INDEPENDENT_REVIEW_INVALID: expected boolean")
    paths = list(dict.fromkeys([main, *attachments, *(item["path"] for item in selection)]))
    body = {"version": version, "media_root": media_root, "main": main, "attachments": attachments,
            "selected": selection, "receipts": receipts, "evidence": evidence,
            "affected": _strings(raw.get("affected", []), "affected"),
            "required_checks": required_checks, "independent_review_required": independent}
    body["files"] = _export_files(conn, task, body, root, paths)
    if not body["files"][0]["size"]:
        raise ValueError(f"VIDEO_EXPORT_EMPTY: {main}")
    return body


def current_export(conn, task, task_dir, *, rows=None, check_content=True):
    from .transaction_commit import _assert_task_workspace_identity
    _assert_task_workspace_identity(conn, task_dir, task["task_id"])
    rows = execution.read_events(conn, task["task_id"]) if rows is None else rows
    export = next(_records(rows, EXPORT), None)
    if export is None:
        raise ValueError("VIDEO_EXPORT_REQUIRED: record an actual export manifest")
    _evidence(task_dir, export["evidence"])
    root = policy.media_root(_workspace(conn, task), export["media_root"])
    expected = export["files"]
    current = _export_files(conn, task, export, root, [file["path"] for file in expected], check_content=check_content)
    if not check_content:
        expected = [{k: file[k] for k in ("path", "size")} for file in expected]
    if expected != current:
        raise ValueError("VIDEO_MEDIA_CHANGED: the selected export or assets no longer match")
    return export


def media_binding(conn, task, task_dir, *, expected_event=None, rows=None, check_content=True):
    export = current_export(conn, task, task_dir, rows=rows, check_content=check_content)
    if expected_event is not None and expected_event != export["event_id"]:
        raise ValueError(f"VIDEO_EXPORT_SELECTION_STALE: selected #{expected_event}, current #{export['event_id']}")
    return _binding(task, task_dir, export)


def _prepare_qc(conn, task, task_dir, payload, actor, agent):
    binding = media_binding(conn, task, task_dir, expected_event=payload["export_event"])
    raw, item = _read_json(task_dir, payload["report"])
    raw = work_units.authority.obj(raw, {"kind", "coverage", "unchecked", "findings", "source_refs"}, "video QC")
    kind = raw.get("kind")
    if kind not in ("technical", "self", "independent"):
        raise ValueError("VIDEO_QC_KIND_INVALID: use technical, self or independent")
    coverage = _strings(raw.get("coverage", []), "coverage")
    unchecked = _strings(raw.get("unchecked", []), "unchecked")
    if not coverage or set(coverage) & set(unchecked):
        raise ValueError("VIDEO_QC_COVERAGE_INVALID: record actual checked and separate unchecked items")
    if kind == "independent":
        export = current_export(conn, task, task_dir, check_content=False)
        units = work_units.read(conn, task["task_id"])["units"]
        contributors = [export["agent"], *(units[wid]["result"]["agent"] for wid in export["receipts"])]
        participants = execution.read_execution(conn, task)["participations"]
        if (actor != policy.REVIEWER or not agent or any(not value or value == agent for value in contributors)
                or not any(p["role"] == actor and p["agent"] == agent for p in participants)):
            raise ValueError("VIDEO_QC_INDEPENDENCE_UNCONFIRMED: record actual independent participation and production identities")
    from .execution_cmd import validate_refs
    sources = validate_refs(conn, task["task_id"], raw.get("source_refs", []))
    return {**binding, "kind": kind, "coverage": coverage, "unchecked": unchecked,
            "findings": _strings(raw.get("findings", []), "findings"), "source_refs": sources,
            "decision": payload["decision"], "evidence": item}


def _qc_status(rows, task_dir, export, binding, *, after=0):
    selected, records, issues = {}, [], []
    independent = None
    for qc in _records(rows, QC):
        if qc["event_id"] <= after or any(qc.get(key) != value for key, value in binding.items()):
            continue
        _evidence(task_dir, qc["evidence"])
        records.append(qc)
        for key in qc["coverage"]:
            selected.setdefault(key, qc["decision"])
        if qc["kind"] == "independent" and independent is None:
            independent = qc["decision"]
    issues.extend(f"VIDEO_QC_UNRESOLVED: {key} ({decision})" for key, decision in selected.items() if decision != "PASS")
    issues.extend(f"VIDEO_QC_COVERAGE_MISSING: {key}" for key in export["required_checks"] if key not in selected)
    if export["independent_review_required"] and independent != "PASS":
        issues.append("VIDEO_INDEPENDENT_QC_REQUIRED")
    if after and not records:
        issues.append("VIDEO_FIX_RECHECK_REQUIRED: record QC after receiving the repair")
    return records, issues


def _delivery_prerequisites(conn, task, task_dir, *, rows=None, check_content=True):
    from . import event_policies, record_first, yaml_checks
    rows = execution.read_events(conn, task["task_id"]) if rows is None else rows
    export = current_export(conn, task, task_dir, rows=rows, check_content=check_content)
    binding = _binding(task, task_dir, export)
    qcs, issues = _qc_status(rows, task_dir, export, binding)
    owner_events = {}
    acceptance = task_dir / "acceptance.md"
    if not acceptance.is_file():
        issues.append("VIDEO_ACCEPTANCE_SCOPE_MISSING")
    else:
        text = acceptance.read_text(encoding="utf-8-sig")
        owner = event_policies.effective_owner_acceptance(conn, task["task_id"], task_dir=task_dir, media=binding)
        owner_events = {ac: item["_event_id"] for ac, item in owner["by_ac"].items()}
        checked = yaml_checks.check_acceptance_yaml(
            text, enforce_completion=True, allow_human_pending=False, owner_visual_acs=set(owner["visual_acs"]))
        issues.extend(checked.issues)
        issues.extend(record_first.acceptance_truth_issues(conn, task["task_id"], task_dir, owner=owner))
        results = {}
        for qc in qcs:
            for result in qc.get("ac_results", []):
                results.setdefault(result["ac"], result)
        from .task_cmd import _acceptance_table_rows
        for ac, row in _acceptance_table_rows(text).items():
            if row["witness"] == "human" and row["verdict"] not in {"N/A", "NOT_REQUIRED", "DEFERRED_ACCEPTED", "OWNER_WAIVED"} and ac not in owner["accepted_acs"]:
                issues.append(f"VIDEO_OWNER_ACCEPTANCE_PENDING: {ac}")
            if row["witness"] in {"technical", "verification"} and row["verdict"] == "PASS":
                result = results.get(ac, {})
                if result.get("verdict") != "PASS" or result["evidence"]["path"] != row["evidence"]:
                    issues.append(f"VIDEO_TECHNICAL_AC_NOT_CURRENT: {ac}")
                else:
                    _evidence(task_dir, result["evidence"])
    return {**binding, "qc_event_ids": [qc["event_id"] for qc in qcs],
            "owner_event_ids": owner_events}, list(dict.fromkeys(issues))


def _binding(task, task_dir, export):
    manifest = execution.digest(export)
    scope = compute_verification_subject_digest(task_dir, scope="technical")
    return {"media_export_event_id": export["event_id"], "media_manifest_digest": manifest,
            "subject_digest": execution.digest([task["task_id"], export["event_id"], manifest, scope]),
            "subject_scope": "media"}


def _fix_check_scope(labels, recognized):
    return {FIX_CHECK_ALIASES.get(label, label) for label in labels} & recognized


def check_step(conn, task, step, action, needed, fixes):
    for unit in needed:
        work_units.validate_result(conn, task["task_id"], unit, source_output=True)
    if action != "complete":
        return
    task_dir = work_units.task_dir(conn, task["task_id"])
    rows = execution.read_events(conn, task["task_id"])
    if step["phase"] == "media_quality":
        export = current_export(conn, task, task_dir, rows=rows)
        binding = _binding(task, task_dir, export)
        qcs, issues = _qc_status(rows, task_dir, export, binding)
        if fixes:
            last_receipt = max(unit["receipt"]["event_id"] for unit in fixes)
            recognized = {"audio", "visual", *export["required_checks"]}
            declared = _fix_check_scope(export["affected"], recognized)
            required = set(declared)
            unbound = [asset for asset in export["selected"] if "work_item" not in asset]
            root = policy.media_root(_workspace(conn, task), export["media_root"]) if unbound else None
            for unit in fixes:
                wid = unit["item_id"]
                labels = [asset["role"] for asset in export["selected"] if asset.get("work_item") == wid]
                if unbound and export["receipts"].get(wid) == unit["receipt"]["event_id"]:
                    work_root = work_units.media_work_root(conn, task["task_id"], unit)
                    outputs = {work_root / output["path"] for output in unit["result"]["result"]["outputs"]}
                    labels.extend(asset["role"] for asset in unbound if root / asset["path"] in outputs)
                scope = _fix_check_scope(labels, recognized)
                if not scope and not declared:
                    issues.append(f"VIDEO_FIX_SCOPE_REQUIRED: {wid}; declare affected checks in a new export")
                required.update(scope)
            checked = {check for qc in qcs if qc["event_id"] > last_receipt and qc["decision"] == "PASS"
                       for check in qc["coverage"]}
            missing = required - checked
            if missing:
                issues.append(f"VIDEO_FIX_RECHECK_REQUIRED: record current {', '.join(sorted(missing))} QC after the repair")
        if any(u["result"]["result"]["outputs"] and export["receipts"].get(u["item_id"]) != u["receipt"]["event_id"]
               for u in fixes):
            issues.append("VIDEO_FIX_EXPORT_REQUIRED: bind the received repair to the current export")
        if issues:
            raise ValueError("; ".join(issues))
    if step["phase"] == "delivery":
        _, issues = delivery_current(conn, task, task_dir, rows=rows)
        if issues:
            raise ValueError("; ".join(issues))


def delivery_current(conn, task, task_dir, *, rows=None, check_content=True):
    rows = execution.read_events(conn, task["task_id"]) if rows is None else rows
    latest = next(_records(rows, DELIVERY), None)
    binding, issues = _delivery_prerequisites(conn, task, task_dir, rows=rows, check_content=check_content)
    if not latest or latest["status"] != "READY" or any(latest.get(key) != value for key, value in binding.items()):
        issues.append("VIDEO_DELIVERY_NOT_CURRENT: record READY for the current export and QC")
    if latest:
        for item in latest["evidence_items"]:
            _evidence(task_dir, item)
    return latest, issues


def record(operation, *, task_id, task_dir, actor, summary, payload, request_id=None, agent="", db_path=None):
    from . import record_first
    from .execution_cmd import append_event
    from .transaction_commit import _assert_task_workspace_identity
    kind = OPERATIONS[operation]
    task_dir = record_first._task_dir(task_dir)
    conn = db.connect(db.resolve_db_path(db_path, task_id=task_id))
    try:
        task = record_first._load(conn, task_id)
        if task_domain(conn, task) != "video":
            raise ValueError("VIDEO_OPERATION_NOT_APPLICABLE")
        if actor not in ACTORS[kind]:
            raise ValueError(f"VIDEO_ACTOR_INVALID: {actor} / {operation}")
        summary = _text(summary, "summary")
        request = recording.LogicalRequest(task_id, task_dir, operation,
            {"actor": actor, "agent": agent, "summary": summary, **payload}, request_id)
        _assert_task_workspace_identity(conn, task_dir, task_id)
        replay = request.replay(conn)
        if replay is not None:
            return replay
        if task["current_state"] not in ("NEW", "ACTIVE"):
            raise ValueError(f"VIDEO_TASK_NOT_ACTIVE: {task['current_state']}")
        phase = {EXPORT: payload.get("phase"), QC: "media_quality", DELIVERY: "delivery"}[kind]
        if kind == EXPORT:
            policy.validate_phase_actor("video", phase, actor)
        now = db.now_iso()
        flush_id = f"{operation.upper()}-{uuid.uuid4().hex}"

        def prepare(connection):
            if kind == EXPORT:
                return _prepare_export(connection, task, task_dir, payload["manifest"]), {}
            if kind == QC:
                body = _prepare_qc(connection, task, task_dir, payload, actor, agent)
                updates = {}
                if payload["ac_results"]:
                    text, results, _ = record_first._prepare_ac_results(
                        task_dir, payload["ac_results"], payload["decision"], conn=connection, task_id=task_id)
                    body["ac_results"] = results
                    updates["acceptance.md"] = text
                return body, updates
            status = payload["status"]
            if status == "READY":
                body, issues = _delivery_prerequisites(connection, task, task_dir)
                if issues:
                    raise ValueError("; ".join(issues))
            else:
                body = {key: payload[key] for key in ("recovery_condition", "blocker_kind", "responsibility")}
                for key, value in body.items():
                    _text(value, key)
            body.update(status=status, residual_risks=payload["residual_risks"],
                        unverified=payload["unverified"],
                        evidence_items=[_evidence(task_dir, ref) for ref in payload["evidence"]])
            return body, {}

        body, artifacts = prepare(conn)
        response = {"task_id": task_id, "request_id": request.request_id, "domain": "video",
                    "flush_id": flush_id, "phase": phase, "summary": summary, "actor": actor,
                    "state": "ACTIVE", "replayed": False}

        def recheck(connection):
            request.reject_duplicate(connection)
            if prepare(connection) != (body, artifacts):
                raise ValueError("VIDEO_INPUT_CHANGED: re-read current media, evidence and scope")

        def writer(connection, transaction_id=""):
            state = task["current_state"]
            if state == "NEW":
                connection.execute(
                    "INSERT INTO task_event(task_id,event_type,from_state,to_state,from_stage,to_stage,actor_role,summary,detail_json,workflow_version,created_at) VALUES(?, 'STATE', 'NEW', 'ACTIVE', ?, ?, ?, ?, ?, ?, ?)",
                    (task_id, task["current_stage"], phase, actor, "task activated",
                     record_first._detail("ACTIVATE", flush_id, transaction_id=transaction_id, phase=phase),
                     task["base_version"], now))
            outcome = body.get("status") or body.get("decision") or "RECORDED"
            payload_fields = {"domain": "video", "phase": phase, "video_payload": body,
                              "video_digest": execution.digest(body), "flush_id": flush_id}
            if body.get("evidence"):
                payload_fields["evidence"] = [body["evidence"]["path"]]
            if outcome in {"PASS", "FAIL", "NEEDS_FIX"}:
                payload_fields["decision"] = outcome
            eid = append_event(connection, task, kind, actor=actor, agent=agent, summary=summary,
                payload=payload_fields, producer="video_records", now=now, transaction_id=transaction_id,
                result_status="BLOCKED" if outcome == "BLOCKED" else "RECORDED")
            response.update(event_id=eid, result=body, facts_committed=True)
            detail = execution.detail_of(connection.execute("SELECT * FROM task_event WHERE id=?", (eid,)).fetchone())
            detail["logical_request"] = request.detail(response)
            connection.execute("UPDATE task_event SET detail_json=?, evidence_path=? WHERE id=?",
                               (json.dumps(detail, ensure_ascii=False), (body.get("evidence") or {}).get("path"), eid))
            connection.execute("UPDATE task SET current_state='ACTIVE', current_stage=?, updated_at=? WHERE task_id=?",
                               (phase, now, task_id))

        result = record_first._write_with_projection(conn, task_dir, task, operation=operation, target_state="ACTIVE",
            owner_after=actor, flush_id=flush_id, writer=writer, summary=summary, before_prepare=recheck,
            artifact_texts=artifacts)
        return result if result.get("replayed") else {**response, **result}
    finally:
        conn.close()


def route(conn, task, rows, task_dir, role_map):
    from . import event_policies, waiting
    from .orchestration import _role_display
    state = task["current_state"]
    facts = task.get("_progress_facts", {}).get("execution") or execution.read_execution(
        conn, task, rows=rows, retired=bool(task.get("_retired")))
    current, following = facts["current_step"], facts["next_step"]
    stage, actor, action, blocker, reason = "intake", policy.PRODUCER, "work_plan", "", "VIDEO_PLAN_REQUIRED"
    media = {"status": "NOT_RECORDED"}
    wait = {}
    confirmation = {}
    if facts["terminal"]:
        stage, actor, action, reason = None, None, None, "TASK_TERMINAL"
        try:
            export = next(_records(rows, EXPORT), None)
            delivery = next(_records(rows, DELIVERY), None)
            if export:
                media = {"status": "HISTORICAL", "version": export["version"], "event_id": export["event_id"],
                         "main": export["main"], "recorded_at": export["created_at"], "hashes_rechecked": False,
                         "delivery_status": delivery["status"] if delivery else "NOT_RECORDED"}
        except (ValueError, KeyError, TypeError) as exc:
            media = {"status": "UNCONFIRMED", "issues": [str(exc)]}
    elif facts["issues"]:
        stage, actor, action, reason = None, policy.PRODUCER, "inspect", "EXECUTION_FACTS_INVALID"
        blocker = "; ".join(facts["issues"])
    elif state == "BLOCKED":
        wait = waiting.active_wait(rows, state)
        stage, actor, action, reason = (task["current_stage"], wait.get("responsibility") or policy.PRODUCER,
                                         "await_resolution", "VIDEO_TASK_BLOCKED")
        blocker = wait.get("condition") or wait.get("reason") or "VIDEO_TASK_BLOCKED"
        if wait.get("kind") == "permission":
            binding, confirmed = waiting.video_permission_confirmation(task["task_id"], rows, wait)
            if confirmed:
                action = "task_resume"
            else:
                action, reason = "await_confirmation", "VIDEO_PERMISSION_REQUIRED"
                confirmation = {"confirmation_required": True, "confirmation_reason": reason,
                                "confirmation_binding": binding}
    elif current and current["status"] == "WAITING":
        stage, actor, action, reason = (current["phase"], current.get("expected_next_actor") or policy.PRODUCER,
                                         "work_step_resume", "VIDEO_STEP_WAITING")
        blocker = current["wait_reason"]
        units = work_units.read(conn, task["task_id"])["units"]
        waiting_items = [wid for wid in current["waiting_work_items"] if not units.get(wid, {}).get("receipt")]
        if waiting_items:
            actor, action, reason = current.get("expected_next_actor") or policy.PRODUCER, "workitem", "VIDEO_FIX_PENDING"
            wait = {"work_item_ids": waiting_items, "responsibility": actor, "condition": blocker}
    elif current:
        stage, actor, action, reason = current["phase"], current["roles"][0], "dispatch_role", "VIDEO_STEP_ACTIVE"
    elif following:
        stage, actor, action, reason = following["phase"], following["roles"][0], "work_step_start", "VIDEO_STEP_PLANNED"

    if task_dir is not None and not facts["terminal"]:
        try:
            export = current_export(conn, task, task_dir, rows=rows, check_content=False)
            media = {"status": "RECORDED", "version": export["version"], "event_id": export["event_id"],
                     "main": export["main"], "recorded_at": export["created_at"], "hashes_rechecked": False}
            delivery, issues = delivery_current(conn, task, task_dir, rows=rows, check_content=False)
            qcs, _ = _qc_status(rows, task_dir, export, _binding(task, task_dir, export))
            media.update(qc=[{key: qc[key] for key in ("event_id", "actor", "kind", "decision", "coverage", "unchecked")}
                             for qc in qcs], delivery_status=delivery["status"] if delivery else "NOT_RECORDED",
                         delivery_event_id=delivery["event_id"] if delivery else None, issues=issues)
            if delivery and delivery["status"] == "BLOCKED":
                media.update({key: delivery[key] for key in ("blocker_kind", "recovery_condition", "responsibility")})
        except (ValueError, OSError, KeyError, TypeError) as exc:
            issues = [str(exc)]
            media.update(issues=issues)
            if not str(exc).startswith("VIDEO_EXPORT_REQUIRED"):
                media["status"] = "UNCONFIRMED"
        pending_owner = [issue for issue in issues if issue.startswith("VIDEO_OWNER_ACCEPTANCE_PENDING:")]
        if facts["plan"] and not current and not following and not blocker:
            if issues:
                stage, actor, action, reason = "delivery", policy.PRODUCER, "task_delivery_converge", "VIDEO_DELIVERY_PENDING"
                blocker = "; ".join(issues)
            else:
                stage, actor, action, reason = "complete", policy.PRODUCER, "task_complete", "VIDEO_DELIVERY_RECORDED"
        elif current and current["phase"] == "delivery" and not blocker:
            if not issues:
                action, reason = "work_step_complete", "VIDEO_DELIVERY_RECORDED"
            elif media.get("delivery_status") == "BLOCKED":
                actor = media["responsibility"]
                action, reason, blocker = "await_resolution", "VIDEO_DELIVERY_BLOCKED", media["recovery_condition"]
        if stage == "delivery" and pending_owner and not any(issue.startswith("VIDEO_QC_") for issue in issues):
            actor, action, reason = "human_owner", "await_owner_acceptance", "VIDEO_OWNER_ACCEPTANCE_PENDING"
            blocker = "; ".join(pending_owner)
    display = _role_display(role_map, actor) if actor else {}
    return {"task_id": task["task_id"], "domain": "video", "workflow_mode": None, "mode_source": None,
            "current_state": state, "current_phase": task["current_stage"], "effective_level": None,
            "included_stages": list(dict.fromkeys(step["phase"] for step in facts["steps"])),
            "applicable_obligations": {"delivery": True, "acceptance": "declared"},
            "next_stage": stage, "role_id": actor, "next_responsibility": actor, "role_display": display,
            "skill_path": (role_map.get(actor) or {}).get("skill_path"), "recommended_action": action,
            "reason_codes": [reason], "reason": reason, "blocker": blocker or None,
            "decision": "BOUNDARY_REACHED" if blocker else "NO_ACTION" if not action else "NEXT_STAGE",
            "requires_human": actor == "human_owner", "confirmation_required": False, "required_effects": [], **confirmation,
            "context": {"execution": facts, "media": media, "waiting": wait}, "media": media}


def closeout(conn, task, task_dir, rows, *, mode, base_root=None):
    from . import closeout as shared, delivery_contract, event_policies, orchestration, temp_artifacts
    from .transaction_commit import _assert_task_workspace_identity
    from .version import active_version
    result = {"schema": shared.SCHEMA, "task_id": task["task_id"], "domain": mode["domain"],
              "state": task["current_state"], "workflow_mode": None, "ready": False, "already_terminal": False,
              "checks": [], "blockers": [], "unknowns": [], "acceptance_issues": [],
              "route": None, "next_actions": [], "read_only": True}
    if task["current_state"] in execution.TERMINAL:
        return {**result, **shared.terminal_result(conn, task)}
    if mode["issues"]:
        result["blockers"] = list(mode["issues"])
        return result
    _assert_task_workspace_identity(conn, task_dir, task["task_id"])
    if task["base_version"] != active_version(base_root):
        result["blockers"].append("TASK_CONTRACT_MISMATCH")
        return result
    role_map = {row["workflow_role"]: row for row in orchestration.load_role_catalog(base_root)["roles"]}
    result["route"] = route(conn, {**task, "_retired": event_policies.is_task_retired(conn, task["task_id"])},
                            rows, task_dir, role_map)
    readiness = []
    if task["current_state"] not in ("NEW", "ACTIVE") or result["route"]["reason"] == "TASK_TERMINAL":
        readiness.append("VIDEO_TASK_NOT_ACTIVE")
    if not execution.read_execution(conn, task, rows=rows)["plan"]:
        readiness.append("VIDEO_PLAN_REQUIRED")
    readiness.extend(execution.completion_blockers(conn, task))
    temp_records = temp_artifacts.records_for_task(task_id=task["task_id"], project_id=task["project_id"])
    try:
        delivery, issues = delivery_current(conn, task, task_dir, rows=rows)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        delivery, issues = None, [str(exc)]
    if delivery and not issues:
        result["media_delivery"] = {key: delivery[key] for key in (
            "event_id", "media_export_event_id", "media_manifest_digest", "subject_digest")}
    for label, issues, facts in (
            ("execution", readiness, {}),
            ("media_delivery", issues, {"event_id": delivery["event_id"] if delivery else None}),
            ("temporary_artifacts", delivery_contract.validate_task_temp_artifacts(temp_records),
             temp_artifacts.summarize_records(temp_records)),
    ):
        result["checks"].append({"id": label, "status": "PENDING" if issues else "PASS", "issues": issues,
                                 "required": True, "depends_on": [], "responsibility": policy.PRODUCER, "facts": facts})
        result["blockers"].extend(issues)
        if issues:
            result["next_actions"].append({"check_id": label, "issues": issues, "responsibility": policy.PRODUCER,
                                           "depends_on": [], "actionable_now": True})
    result["ready"] = not result["blockers"]
    return result
