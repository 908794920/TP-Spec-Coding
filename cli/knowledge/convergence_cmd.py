"""Formal task learning commands; no LLM, automatic Memory edit or full-vault scan."""
from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
import re
import sqlite3
import sys
import uuid
from pathlib import Path

from . import convergence as learning


def _read_json(path):
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8-sig")
    return json.loads(text)


def _events(conn, task_id):
    return [dict(row) for row in conn.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id", (task_id,))]


def _request(conn, task_id, request_id):
    from .commands import _task_convergence_request
    trusted = _task_convergence_request(conn, task_id, request_id)
    return {"event": dict(trusted.row), "detail": dict(trusted.detail)}


def _prior_result(conn, task_id, result_id):
    from cli import event_policies
    rows = event_policies.load_trusted_governance_events(conn, task_id,
        event_type="KNOWLEDGE_CONVERGENCE_RESULT", actor="tp-knowledge")
    item = next((row for row in rows if int(row.row["id"]) == result_id), None)
    if item is None:
        raise ValueError("reuse_result_event_id must name a trusted result from this Task")
    req = _request(conn, task_id, item.detail["request_event_id"])
    if not learning.valid_result(item.detail, req):
        raise ValueError("reused result has no valid input coverage and receipts")
    return item.detail


def _expand_reuse(conn, task_id, raw, index):
    """Reuse is explicit and dependency-bound; no heuristic topic equivalence."""
    value, reused, cache = copy.deepcopy(raw), {}, {}
    hashes = {item["id"]: item["digest"] for item in index["items"]}
    if not isinstance(value, dict):
        raise ValueError("assessment must be an object")
    for section in ("coverage", "knowledge", "memory"):
        rows = (value.get("memory") or {}).get("items") if section == "memory" and isinstance(value.get("memory"), dict) else value.get(section)
        if not isinstance(rows, list):
            continue  # The common validator reports the missing field.
        for position, entry in enumerate(rows):
            if not isinstance(entry, dict) or "reuse_result_event_id" not in entry:
                continue
            result_id = entry["reuse_result_event_id"]
            if type(result_id) is not int or result_id <= 0:
                raise ValueError("reuse_result_event_id must be a positive integer")
            if result_id not in cache:
                cache[result_id] = _prior_result(conn, task_id, result_id)
            detail = cache[result_id]
            key = "input_id" if section == "coverage" else "id"
            old_items = detail["assessment"][section]
            if section == "memory":
                old_items = old_items["items"]
            old = next((item for item in old_items if item.get(key) == entry.get(key)), None)
            if old is None:
                raise ValueError("reuse names an unknown assessment item")
            deps = {old["input_id"]: old["digest"]} if section == "coverage" else old["input_digests"]
            if any(hashes.get(key) != fingerprint for key, fingerprint in deps.items()):
                raise ValueError("REUSE_INPUT_CHANGED: re-evaluate only the affected judgment")
            rows[position] = copy.deepcopy(old)
            if section == "knowledge":
                result = next(item for item in detail["knowledge_results"] if item["id"] == old["id"])
                reused[old["id"]] = {"result": result, "event_id": result_id,
                                     "retrieval_context": detail["retrieval_context"]}
    return value, reused


def _retrieval_context(cfg):
    from .common import resolve_knowledge_project
    resolved = resolve_knowledge_project(cfg, require=True)
    if not resolved.get("resolved"):
        raise ValueError("Knowledge project registry/binding is missing")
    db = cfg.paths.knowledge_projection_db
    if not db.is_file():
        raise ValueError("Knowledge projection missing; resolve the environment before convergence")
    conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT value FROM build_meta WHERE key='projection_subject'").fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        raise ValueError("Knowledge projection has no recorded source identity")
    return learning.digest({"project": resolved["project_id"], "shared": resolved["shared_ids"],
        "projection_subject": row[0], "retrieval": cfg.knowledge_retrieval,
        "registry": hashlib.sha256(cfg.paths.knowledge_registry.read_bytes()).hexdigest(),
        "root_identity": str(cfg.paths.knowledge_physical_root.resolve())})


def _candidate_sources(candidate, index, request):
    indexed = {item["id"]: item for item in index["items"]}
    locators = []
    for key in candidate["input_ids"]:
        if key == "task":
            ref = "task.md"
        elif key == "delivery":
            ref = "event:" + str(request["detail"]["delivery_event_id"])
        else:
            ref = indexed[key].get("ref", key)
        if ref not in locators:
            locators.append(ref)
    return locators


def _canonical(cfg, candidate, receipts, task_id, source_refs):
    from .commands import _resolve_exact_canonical_note
    from .lint import lint_canonical_note
    from cli.delivery_contract import validate_canonical_binding
    disposition, ref = candidate["disposition"], candidate.get("knowledge_ref")
    if disposition == "NO_DURABLE_INSIGHT":
        return None, None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", ref):
        raise ValueError("knowledge_ref must be an exact canonical ID, not a path or pattern")
    if disposition in {"DUPLICATE", "UPDATED"} and ref not in {
            value for receipt in receipts for value in receipt.get("matched_canonical_refs", [])}:
        raise ValueError(f"{disposition} requires an exact canonical search hit")
    note = _resolve_exact_canonical_note(cfg, ref)
    from .common import resolve_knowledge_project
    resolved = resolve_knowledge_project(cfg, require=True)
    if str((note.get("frontmatter") or {}).get("project") or "") not in {resolved["project_id"], *resolved["shared_ids"]}:
        raise ValueError("canonical target is outside current project + registered shared")
    receipt = {"canonical_id": ref, "path": note["rel_path"], "sha256": note["sha256"]}
    if disposition in {"CREATED", "UPDATED"}:
        lint = lint_canonical_note(cfg, note)
        if lint.get("status") != "PASS":
            raise ValueError("canonical lint failed: " + json.dumps(lint.get("violations"), ensure_ascii=False))
        errors = validate_canonical_binding(note.get("frontmatter") or {}, task_id=task_id,
                                            evidence_paths=source_refs, source_refs=[])
        if errors:
            raise ValueError("canonical Task/evidence binding invalid: " + "; ".join(errors))
        receipt["lint"] = lint
    return note, receipt


def cmd_inputs(args):
    from cli import db as dbmod, workflow_controls
    from .commands import _emit
    conn = None
    try:
        path = dbmod.resolve_db_path(args.db, task_id=args.task)
        conn = dbmod.connect_readonly(path)
        conn.execute("BEGIN")
        task = conn.execute("SELECT * FROM task WHERE task_id=?", (args.task,)).fetchone()
        if task is None:
            raise ValueError("Task not found")
        events = _events(conn, args.task)
        request = _request(conn, args.task, args.request_event_id) if args.request_event_id else None
        deliveries = [row for row in events if workflow_controls.trusted_event_detail(row,
            event_type="DELIVERY_RESULT", producer="delivery_converge", actor="tp-integration-engineer")]
        delivery = learning.detail_of(deliveries[-1]) if deliveries else {}
        index = learning.load_index(conn, args.task, Path(args.task_dir).resolve(), delivery)
        if request is None and deliveries:
            from cli.orchestration import _knowledge_request_for_delivery
            request = _knowledge_request_for_delivery(events, deliveries[-1])
        saved = (request or {}).get("detail", {}).get("input_index", {})
        from cli import orchestration
        facts = orchestration._load_task_facts(args.task, path, connection=conn, task_dir=Path(args.task_dir))
        orchestration.resolve_route(args.task, db_path=path, _facts=facts, task_dir=Path(args.task_dir))
        current_delivery = orchestration._delivery_completion_event(facts[1], Path(args.task_dir), task=facts[0])
        response = {"schema": learning.SCHEMA, "read_only": True, "task_id": args.task,
            "task_state": task["current_state"], "request_event_id": (request or {}).get("event", {}).get("id"),
            "request_current": bool(current_delivery and request and current_delivery["id"] == request["detail"]["delivery_event_id"] and saved == index and not index["issues"]),
            "input_index": index, "delta": learning.index_diff(saved, index),
            "source_authority": "输入/来源不等于已读、已理解或人工授权；未记录历史不补造。",
            "previous_results": []}
        hashes = {item["id"]: item["digest"] for item in index["items"]}
        for row in reversed(events):
            detail = learning.detail_of(row)
            if row["event_type"] != "KNOWLEDGE_CONVERGENCE_RESULT" or detail.get("learning_schema") != learning.SCHEMA:
                continue
            response["previous_results"].append({"event_id": row["id"], "input_digest": detail.get("input_digest"),
                "candidates": [{"id": item["id"], "inputs_unchanged": bool(item.get("input_digests")) and
                    all(hashes.get(key) == value for key, value in item.get("input_digests", {}).items())}
                    for item in detail.get("knowledge_results", [])],
                "note": "仅依赖指纹提示；复用仍核验可信来源、定向检索版本和精确目标"})
            if len(response["previous_results"]) == 5:
                break  # Recent navigation only; explicit reuse can name any same-Task result.
        item_id = getattr(args, "item", None)
        if item_id:
            item = next((row for row in index["items"] if row["id"] == item_id), None)
            if item is None:
                raise ValueError("item is not in current task-inputs")
            if item["kind"] == "event":
                row = next(row for row in events if row["id"] == item["event_id"])
                response["selected_input"] = {**item, "content": learning._event_content(row)}
            elif item["kind"] == "work":
                row = conn.execute("SELECT * FROM work_item WHERE task_id=? AND item_id=?", (args.task, item["work_item_id"])).fetchone()
                response["selected_input"] = {**item, "content": dict(row)}
            elif item["id"] == "task":
                response["selected_input"] = {**item, "content": learning.scope_content(task)}
            elif item["id"] == "delivery":
                response["selected_input"] = {**item, "content": learning.delivery_content(delivery)}
            else:
                response["selected_input"] = item  # Files/citations are read using the returned exact ref.
        _emit(response)
        return 0
    except Exception as exc:
        _emit({"schema": learning.SCHEMA, "status": "FAIL", "read_only": True, "error": str(exc)})
        return 1
    finally:
        if conn is not None:
            conn.close()


def cmd_converge(args):
    from cli import db as dbmod, orchestration, record_first, recording, event_contract
    from cli.version import active_version
    from .commands import _cfg, _emit, _search_receipt
    from .common import resolve_knowledge_project
    from .projection import update_canonical_note_projection
    conn, external_effects = None, []
    try:
        task_dir = Path(args.task_dir).resolve()
        if not task_dir.is_dir():
            raise ValueError("task directory not found")
        path = dbmod.resolve_db_path(args.db, task_id=args.task)
        conn = dbmod.connect(path)
        task, events = orchestration._load_task_facts(args.task, path, connection=conn, task_dir=task_dir)
        if task["current_state"] in record_first.TERMINAL_STATES:
            from cli.closeout import terminal_result
            _emit(terminal_result(conn, task))
            return 0
        request = _request(conn, args.task, args.request_event_id)
        if request["detail"].get("learning_schema") != learning.SCHEMA:
            raise ValueError("old request uses legacy flags; rerun delivery converge to adopt Task learning")

        def check_current(dbconn):
            facts, rows = orchestration._load_task_facts(args.task, path, connection=dbconn, task_dir=task_dir)
            if facts["current_state"] not in {"NEW", "ACTIVE"} or facts.get("_retired"):
                raise ValueError("Task cannot accept learning in its current state")
            orchestration.resolve_route(args.task, db_path=path, _facts=(facts, rows), task_dir=task_dir)
            delivery = orchestration._delivery_completion_event(rows, task_dir, task=facts)
            if delivery is None or int(delivery["id"]) != request["detail"]["delivery_event_id"]:
                raise ValueError("current READY delivery differs; refresh only stale prerequisites")
            if not learning.current_request(request, rows, task_dir, facts):
                raise ValueError("LEARNING_INPUT_CHANGED: inspect task-inputs and rerun delivery converge")
            return facts, rows

        task, events = check_current(conn)
        if not getattr(args, "assessment", None):
            raise ValueError("new Task learning requires --assessment FILE|- (coverage + knowledge + memory)")
        if any(getattr(args, key, None) for key in ("query", "source", "disposition", "knowledge_ref", "reason_code")):
            raise ValueError("--assessment replaces legacy query/source/disposition flags; do not mix")
        index = request["detail"]["input_index"]
        raw, reused = _expand_reuse(conn, args.task, _read_json(args.assessment), index)
        assessment = learning.validate_assessment(raw, index)
        assessment_digest = learning.digest(assessment)
        project_root = Path(task["project_root_path"]).resolve()
        memory = learning.memory_readback(assessment["memory"], project_root)
        cfg = _cfg(args)
        # Task-scoped effect never inherits a global fallback or excludes shared
        # scopes while claiming that they were searched. General search is unchanged.
        cfg = replace(cfg, knowledge_retrieval={**cfg.knowledge_retrieval, "include_shared": True, "global_fallback": False})
        resolved = resolve_knowledge_project(cfg, require=True)
        if resolved.get("project_id") != task["project_id"] or cfg.paths.workspace_root.resolve() != project_root:
            raise ValueError("Knowledge workspace/project does not match Runtime project")
        retrieval_context = _retrieval_context(cfg)

        def replay(dbconn):
            rows = _events(dbconn, args.task)
            current = orchestration._knowledge_result_for_request(rows, request, task_dir, task=task)
            if current and current["detail"].get("assessment_digest") == assessment_digest and current["detail"].get("retrieval_context") == _retrieval_context(cfg):
                detail = current["detail"]
                for item in detail["knowledge_results"]:
                    if item.get("canonical_readback"):
                        _, readback = _canonical(cfg, item, item["query_receipts"], args.task, _candidate_sources(item, index, request))
                        if readback != item["canonical_readback"]:
                            return None
                if memory != detail.get("memory_assessment"):
                    return None
                return {"schema": learning.SCHEMA, "status": "PASS", "task_id": args.task,
                    "request_event_id": args.request_event_id, "result_event_id": current["event"]["id"],
                    "input_digest": index["digest"], "replayed": True, "facts_committed": False,
                    "memory": learning.memory_status(memory, project_root)}
            return None

        previous = replay(conn)
        if previous:
            _emit(previous)
            return 0
        results, notes, query_cache = [], [], {}
        for item in assessment["knowledge"]:
            reuse = reused.get(item["id"])
            if reuse:
                if reuse["retrieval_context"] != retrieval_context:
                    raise ValueError("REUSE_SEARCH_CHANGED: rerun targeted queries for this candidate")
                receipts = reuse["result"]["query_receipts"]
            else:
                receipts = []
                for query in item["queries"]:
                    if query not in query_cache:
                        effect = {"effect": "targeted_search", "query_hash": learning.digest(query), "status": "ATTEMPTED"}
                        external_effects.append(effect)
                        query_cache[query] = _search_receipt(cfg, query)
                        effect["status"] = "PASS"
                    receipts.append(query_cache[query])
            note, readback = _canonical(cfg, item, receipts, args.task, _candidate_sources(item, index, request))
            if reuse and readback != reuse["result"].get("canonical_readback"):
                raise ValueError("REUSE_TARGET_CHANGED: re-evaluate the changed canonical target")
            result = {**item, "query_receipts": receipts, "canonical_readback": readback}
            if reuse:
                result["reused_from_result_event_id"] = reuse["event_id"]
                if reuse["result"].get("index_receipt"):
                    result["index_receipt"] = reuse["result"]["index_receipt"]
            results.append(result)
            notes.append(None if reuse else note)
        # All arguments/coverage/canonical claims are valid before any exact-index write.
        check_current(conn)
        for item, note in zip(results, notes):
            if note and item["disposition"] in {"CREATED", "UPDATED"}:
                effect = {"effect": "exact_canonical_index", "canonical_id": item["knowledge_ref"], "status": "ATTEMPTED"}
                external_effects.append(effect)
                item["index_receipt"] = update_canonical_note_projection(cfg, note)
                effect["status"] = "PASS"
        final_context = _retrieval_context(cfg)
        now, flush_id = dbmod.now_iso(), "KNOWLEDGE-CONVERGE-" + uuid.uuid4().hex
        written = {}
        primary = next((item for disp in ("CREATED", "UPDATED", "DUPLICATE", "NO_DURABLE_INSIGHT")
                        for item in results if item["disposition"] == disp))
        source_refs = request["detail"]["source_refs"]
        source_items = [{"type": "local_file", "path": item["ref"], "sha256": item["digest"],
                         "hash_mode": item.get("hash_mode", "bytes")}
                        for item in index["items"] if item["id"].startswith("file:")]

        def recheck(dbconn):
            check_current(dbconn)
            previous = replay(dbconn)
            if previous:
                raise recording.RequestReplay(previous)
            if _retrieval_context(cfg) != final_context or learning.memory_readback(assessment["memory"], project_root) != memory:
                raise ValueError("LEARNING_TARGET_CHANGED: re-read changed targets before recording")
            for item in results:
                if item.get("canonical_readback"):
                    _, readback = _canonical(cfg, item, item["query_receipts"], args.task, _candidate_sources(item, index, request))
                    if readback != item["canonical_readback"]:
                        raise ValueError("LEARNING_CANONICAL_CHANGED: target changed during convergence")

        def writer(dbconn, transaction_id=""):
            recheck(dbconn)
            detail = {"transaction_id": transaction_id, "flush_id": flush_id, "schema_version": active_version(),
                "task_id": args.task, "actor_role": "tp-knowledge", "created_at": now,
                "request_event_id": args.request_event_id, "change_set_id": request["detail"]["change_set_id"],
                "learning_schema": learning.SCHEMA, "input_digest": index["digest"],
                "assessment_digest": assessment_digest, "assessment": assessment,
                "knowledge_disposition": primary["disposition"], "knowledge_ref": primary.get("knowledge_ref"),
                "knowledge_results": results, "query_receipts": [r for item in results for r in item["query_receipts"]],
                "source_refs": source_refs, "source_items": source_items, "memory_assessment": memory,
                "retrieval_context": final_context, "reason_code": "TASK_INPUTS_ASSESSED"}
            detail = event_contract.add_event_semantics(detail, event_type="KNOWLEDGE_CONVERGENCE_RESULT",
                operation="KNOWLEDGE_CONVERGE", result_status="COMPLETED", producer="knowledge_task_converge",
                reason_code=detail["reason_code"])
            if not learning.valid_result(detail, request):
                raise ValueError("invalid Task learning result")
            cur = dbconn.execute("INSERT INTO task_event (task_id,event_type,from_stage,to_stage,actor_role,reason_code,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (args.task, "KNOWLEDGE_CONVERGENCE_RESULT", "delivery", "delivery", "tp-knowledge",
                 "TASK_INPUTS_ASSESSED", "Task learning: " + primary["disposition"], json.dumps(detail, ensure_ascii=False), active_version(), now))
            written["result_event_id"] = int(cur.lastrowid)
            dbconn.execute("UPDATE task SET updated_at=? WHERE task_id=?", (now, args.task))

        receipt = record_first._write_with_projection(conn, task_dir, task, operation="knowledge_task_converge",
            target_state=task["current_state"], owner_after=task["owner_role"], flush_id=flush_id,
            writer=writer, before_prepare=recheck, summary="Task knowledge and memory assessed")
        _emit({"schema": learning.SCHEMA, "status": "PASS", "task_id": args.task,
            "request_event_id": args.request_event_id, **written, "input_digest": index["digest"],
            "knowledge_disposition": primary["disposition"], "knowledge_results": results,
            "memory": learning.memory_status(memory, project_root), **receipt})
        return 0
    except Exception as exc:
        _emit({"schema": learning.SCHEMA, "status": "FAIL", "error": f"{type(exc).__name__}: {exc}",
            "external_effects": external_effects,
            "note": "Knowledge index/telemetry and Runtime are separate stores; no canonical/Memory content was written by this command. Inspect/reconcile an interrupted Runtime write before retrying."})
        return 1
    finally:
        if conn is not None:
            conn.close()
