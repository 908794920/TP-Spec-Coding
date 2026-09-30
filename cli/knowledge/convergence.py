"""Task-scoped learning bindings over the existing Request/Result ledger.

The index is an inventory, not an assertion that an agent read or understood it.
Assessments are declared professional judgments; receipts prove local readback and
actual targeted retrieval, not human identity or arbitrary business semantics.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

SCHEMA = "tp-spec.task-learning/v1"
DISPOSITIONS = {"CREATED", "UPDATED", "DUPLICATE", "NO_DURABLE_INSIGHT"}
FILES = {
    "task.md": "requirement", "requirement.md": "requirement",
    "requirement-knowledge.md": "requirement", "requirement-clarifications.md": "decision",
    "requirement-decisions.md": "decision", "requirement-test-guide.md": "testing",
    "acceptance.md": "acceptance", "implementation.md": "implementation",
    "architecture-review.md": "review", "codex-review.md": "review",
}
EVENTS = {
    "FACT", "DECISION", "OBSERVATION", "NOTE", "REWORK", "SCOPE_CHANGE",
    "VERIFICATION_COMPLETED", "REVIEW_COMPLETED", "OWNER_ACCEPTANCE_DECISION",
    "EXECUTION_PLAN_RECORDED", "EXECUTION_STEP_RECORDED", "WORK_SESSION_UPDATED",
    "WORK_SESSION_ENDED", "HUMAN_AUTHORITY_RECORDED", "SECURITY_PROPOSAL_RECORDED",
    "SECURITY_WORK_BOUND", "SECURITY_EVIDENCE_RECORDED",
    "WORK_ITEM_RECORDED", "WORK_INTEGRATION_RECORDED",
}
# Bookkeeping is not another learning input. Meaningful findings/decisions/results,
# including unsuccessful attempts, remain bound and can be classified superseded.
PAYLOAD_FIELDS = {
    "phase", "milestone_id", "knowledge_signals", "memory_candidates", "delivery_signals",
    "summary", "scope", "scope_refs", "steps", "assessment", "coordinator", "effective_level", "findings", "decisions", "result", "evidence",
    "evidence_items", "evidence_refs", "source_refs", "artifact", "decision", "reason",
    "reason_code", "plan", "step_id", "session_id", "review_kind", "findings_count",
    "security_payload", "work_payload", "acs", "mode", "residual_risk", "verification_scope",
    "security_changes", "effect_scope", "allowed_paths", "blocker_kind", "recovery_condition",
}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def detail_of(row) -> dict:
    try:
        value = json.loads(dict(row).get("detail_json") or "{}")
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _reference_entries(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"source_refs", "scope_refs", "evidence", "evidence_refs", "evidence_items", "acceptance_evidence_items"}:
                for ref in child if isinstance(child, list) else [child]:
                    if isinstance(ref, str):
                        yield ref, path + (key,)
                    elif isinstance(ref, dict) and isinstance(ref.get("path"), str):
                        yield ref["path"], path + (key, "path")
            elif key == "artifact" and isinstance(child, str):
                yield child, path + (key,)
            elif isinstance(child, (dict, list)):
                yield from _reference_entries(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _reference_entries(child, path + (str(index),))


def _references(value):
    return (ref for ref, _ in _reference_entries(value))


def _locator_fields(task, rows):
    """仅正式生产者的准确字段是导航；不改变事件内容或证据契约。"""
    from cli import execution, event_contract
    from cli.work_session_cmd import pair_work_sessions, _REASON_CODES

    fields = {}
    projected = execution.project_execution(task, rows)
    for plan in projected["plan_history"]:
        fields[plan["event_id"]] = {("detail", "plan", "assessment", "source_refs"),
                                    ("detail", "plan", "scope_refs")}
    for activity in projected["timeline"]:
        if activity["event_type"] in {execution.STEP, "WORK_SESSION_UPDATED", "WORK_SESSION_ENDED"}:
            fields[activity["event_id"]] = {("detail", "evidence_refs")}

    # 旧无计划END确实由同一writer接受locator，不要求补造新执行schema。
    # 有现代绑定字段却缺schema的损坏记录，不能借此退回旧契约。
    by_id = {row["id"]: row for row in rows}
    modern = {"execution_schema", "step_id", "plan_version", "transaction_id"}
    for pair in pair_work_sessions(rows)["pairs"]:
        start, end = by_id[pair["start_event_id"]], by_id[pair["end_event_id"]]
        first, last = detail_of(start), detail_of(end)
        if any(modern & detail.keys() or detail.get("producer") != "work_session"
               or event_contract.validate_event_semantics(row["event_type"], detail)
               for row, detail in ((start, first), (end, last))):
            continue
        if execution._valid_boundary(last) and last.get("reason") in _REASON_CODES:
            fields[end["id"]] = {("detail", "evidence_refs")}
    return fields


def _event_content(row: dict) -> dict | None:
    kind, detail = row.get("event_type"), detail_of(row)
    if kind not in EVENTS:
        return None
    if kind == "WORK_ITEM_RECORDED" and (detail.get("work_payload") or {}).get("action") == "claim":
        return None  # A repeated claim is bookkeeping; results/failures retain real learning inputs.
    if kind == "FACT" and (detail.get("producer") != "record-first"
                            or str(detail.get("operation")).upper() != "CHECKPOINT"):
        return None
    if kind in {"EXECUTION_STEP_RECORDED", "WORK_SESSION_UPDATED", "WORK_SESSION_ENDED"}:
        if not any(detail.get(k) for k in ("findings", "decisions", "result", "evidence_refs", "memory_candidates")):
            return None  # A start/wait/end timestamp alone isn't a new insight.
    return {"event_type": kind, "actor_role": row.get("actor_role"),
            "work_item_id": row.get("work_item_id"), "phase": row.get("to_stage"),
            "summary": row.get("summary") or "",
            "evidence": [row["evidence_path"]] if row.get("evidence_path") else [],
            "detail": {key: detail[key] for key in sorted(PAYLOAD_FIELDS) if key in detail}}


def scope_content(task) -> dict:
    return {key: dict(task).get(key) for key in ("task_id", "project_id", "title", "risk_level", "flow_level")}


def delivery_content(delivery: dict) -> dict:
    return {key: delivery.get(key) for key in ("change_set_id", "delivery_status", "reason", "residual_risks",
            "delivery_mode", "applicability", "evidence", "acceptance_evidence_items", "repo_snapshot")}


def _historical_learning_result(ref: str, events: dict) -> dict | None:
    """只核对同Task历史绑定；不求当前PASS，也不递归构建学习索引。"""
    from cli import event_contract, workflow_controls

    if not re.fullmatch(r"event:[1-9][0-9]*", ref):
        return None
    row = events.get(int(ref[6:]))
    if row is None:
        return None
    detail = workflow_controls.trusted_event_detail(row,
        event_type="KNOWLEDGE_CONVERGENCE_RESULT", producer="knowledge_task_converge", actor="tp-knowledge")
    if (detail is None or detail.get("learning_schema") != SCHEMA
            or detail.get("result_status") != "COMPLETED"
            or event_contract.validate_event_semantics(row["event_type"], detail)):
        return None
    request_id = detail.get("request_event_id")
    request = events.get(request_id) if type(request_id) is int and request_id > 0 else None
    if request is None:
        return None
    saved = workflow_controls.trusted_event_detail(request,
        event_type="KNOWLEDGE_CONVERGENCE_REQUEST", producer="delivery_converge", actor="tp-integration-engineer")
    if (saved is None or saved.get("learning_schema") != SCHEMA
            or saved.get("result_status") != "PENDING"
            or event_contract.validate_event_semantics(request["event_type"], saved)
            or detail.get("change_set_id") != saved.get("change_set_id")
            or not valid_result(detail, {"event": request, "detail": saved})):
        return None
    return detail


def build_index(task, events, work_items, task_dir: Path, delivery: dict) -> dict:
    """Read only this Task's known artifacts and explicitly referenced evidence.

    No rglob, Knowledge scan, other-Task search or generated view as a second truth.
    Exact duplicate event content shares its first ID; arbitrary new notes/decisions
    remain inputs, but neither their text nor role labels create authority.
    """
    from cli.digest import _normalize_subject_part, compute_text_artifact_digest
    from cli.evidence import validate_evidence_path

    task = dict(task)
    events = [dict(row) for row in events if row["task_id"] == task["task_id"]]
    events_by_id = {row["id"]: row for row in events}
    locator_fields = _locator_fields(task, events)
    items, issues, contents = [], [], {}
    refs = {name for name in FILES if (task_dir / name).exists()}
    strict_refs = set(refs)
    locator_refs, event_items = {}, {}
    if "task.md" not in refs:
        issues.append("TASK_SOURCE_MISSING: task.md")

    def add(key, kind, content, **navigation):
        contents[key] = content
        items.append({"id": key, "kind": kind, "digest": digest(content), **navigation})

    add("task", "scope", scope_content(task))
    seen_events = set()
    qualified_sources = {}
    for value in events:
        row = dict(value)
        if row.get("task_id") != task["task_id"]:
            continue
        content = _event_content(row)
        if content is None:
            continue
        fingerprint = digest(content)
        # 内容去重不丢弃来源不同的严格引用；仅完整来源/契约相同的重复
        # 可以复用已验证的locator资格（重复END不会再次被会话配对接受）。
        source = digest({**{key: value for key, value in row.items() if key not in {"id", "detail_json"}},
                         "detail": detail_of(row)})
        allowed_fields = locator_fields.get(row["id"], ())
        if allowed_fields:
            qualified_sources[source] = allowed_fields
        else:
            allowed_fields = qualified_sources.get(source, ())
        locators = []
        for ref, field in _reference_entries(content):
            normalized = ref.replace("\\", "/").strip()
            if (field in allowed_fields
                    and (PurePosixPath(normalized).is_absolute() or PureWindowsPath(normalized).is_absolute())):
                locators.append({"ref": ref, "field": ".".join(field),
                    "status": "UNRESOLVED_LOCATOR", "read_status": "NOT_READ",
                    "reason": "outside Task-relative input contract; target was not accessed"})
            else:
                refs.add(ref)
                if field in allowed_fields and not normalized.startswith(("https://", "http://")):
                    locator_refs.setdefault(ref, []).append((fingerprint, field))
                else:
                    strict_refs.add(ref)  # 强制出现独立保留，不被同目标导航引用消掉。
        if fingerprint in seen_events:
            continue
        seen_events.add(fingerprint)
        add(f"event:{row['id']}", "event", content, event_id=int(row["id"]),
            event_type=row["event_type"], role=row.get("actor_role"), work_item_id=row.get("work_item_id"),
            **({"source_locators": sorted(locators, key=lambda item: (item["field"], item["ref"]))} if locators else {}))
        event_items[fingerprint] = items[-1]

    for value in work_items:
        row = dict(value)
        if row.get("task_id") != task["task_id"]:
            continue
        content = {key: row.get(key) for key in ("item_id", "title", "status", "owner_role", "owner_agent",
                    "depends_on_json", "allowed_paths_json", "acceptance_refs_json")}
        add("work:" + row["item_id"], "work", content, work_item_id=row["item_id"])

    closeout = delivery_content(delivery)
    add("delivery", "delivery", closeout)
    delivery_refs = set(_references(closeout))
    refs.update(delivery_refs)
    strict_refs.update(delivery_refs)
    strict_event_refs = {str(ref).replace("\\", "/").strip() for ref in strict_refs}

    def unresolved_locator(raw, reason, read_status):
        if raw in strict_refs or raw not in locator_refs:
            return False
        for fingerprint, field in locator_refs[raw]:
            navigation = event_items[fingerprint].setdefault("source_locators", [])
            locator = {"ref": raw, "field": ".".join(field), "status": "UNRESOLVED_LOCATOR",
                       "read_status": read_status, "reason": reason}
            if locator not in navigation:
                navigation.append(locator)
        return True

    for raw in sorted(refs):
        ref = str(raw).replace("\\", "/").strip()
        if ref.startswith("event:"):
            if ref not in contents:
                historical = (_historical_learning_result(ref, events_by_id)
                              if raw in locator_refs and ref not in strict_event_refs else None)
                if historical is None:
                    issues.append(f"UNRESOLVED_EVENT_SOURCE: {ref}")
                else:
                    for fingerprint, field in locator_refs[raw]:
                        navigation = event_items[fingerprint].setdefault("source_locators", [])
                        locator = {"ref": raw, "field": ".".join(field), "status": "EXCLUDED_FROM_LEARNING",
                            "event_type": "KNOWLEDGE_CONVERGENCE_RESULT",
                            "request_event_id": historical["request_event_id"],
                            "reason": "trusted historical result binding checked; not a learning input or current PASS"}
                        if locator not in navigation:
                            navigation.append(locator)
            continue
        # A remote citation is navigable provenance, never evidence of a fetch.
        if ref.startswith(("https://", "http://")):
            add("citation:" + ref, "citation", ref, ref=ref)
            continue
        # A fragment navigates within a file; it is not part of its disk name.
        # Index the actual bytes without claiming to validate the named anchor.
        ref = ref.split("#", 1)[0]
        try:
            checked = validate_evidence_path(task_dir, ref, require_evidence_dir=False)
        except OSError as exc:
            if unresolved_locator(raw, f"relative locator access/read failed: {exc}", "READ_FAILED"):
                continue
            raise
        if not checked.ok:
            read_status = "READ_FAILED" if checked.error.startswith("evidence file is not readable:") else "NOT_READ"
            if unresolved_locator(raw, checked.error, read_status):
                continue
            issues.append(f"SOURCE_UNAVAILABLE: {ref}: {checked.error}")
            continue
        ref = str(checked.path)
        if ref in {"status.yaml", "events.jsonl"} or ref.startswith("generated/"):
            continue  # Use canonical inputs and DB events, not expanded projections.
        key = "file:" + ref
        if key in contents:
            continue
        try:
            raw_bytes = (task_dir / ref).read_bytes()
        except OSError as exc:
            if unresolved_locator(raw, f"relative locator body read failed: {exc}", "READ_FAILED"):
                continue
            raise
        # Only the existing runtime-owned guide fields are normalized. Acceptance
        # outcomes and actual Task/requirement text remain learning inputs.
        if ref == "requirement-test-guide.md":
            hash0 = compute_text_artifact_digest(_normalize_subject_part(ref, raw_bytes.decode("utf-8-sig")))
            mode = "guide-content"
        else:
            hash0 = hashlib.sha256(raw_bytes).hexdigest()
            mode = "bytes"
        contents[key] = {"path": ref, "sha256": hash0}
        items.append({"id": key, "kind": FILES.get(ref, "evidence"), "ref": ref,
                      "digest": hash0, "hash_mode": mode})
    for item in event_items.values():
        if "source_locators" in item:
            item["source_locators"].sort(key=lambda locator: (locator["field"], locator["ref"]))
    items.sort(key=lambda item: item["id"])
    index = {"schema": SCHEMA, "task_id": task["task_id"], "items": items, "issues": sorted(set(issues))}
    index["digest"] = digest(index)
    return index


def load_index(conn, task_id: str, task_dir: Path, delivery: dict) -> dict:
    task = conn.execute("SELECT * FROM task WHERE task_id=?", (task_id,)).fetchone()
    if task is None:
        raise ValueError(f"task not found: {task_id}")
    events = conn.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
    works = conn.execute("SELECT * FROM work_item WHERE task_id=? ORDER BY item_id", (task_id,)).fetchall()
    return build_index(task, events, works, task_dir, delivery)


def current_request(request: dict, events, task_dir, task) -> bool:
    if not task_dir or task is None:
        return False
    detail = request["detail"]
    saved = detail.get("input_index")
    if detail.get("learning_schema") != SCHEMA or not isinstance(saved, dict):
        return False
    delivery = next((detail_of(row) for row in events if int(row.get("id") or 0) == detail.get("delivery_event_id")), None)
    if not delivery:
        return False
    if any(detail.get(key) != delivery.get(key) for key in
           ("change_set_id", "verification_event_id", "review_event_id", "applicability")):
        return False
    try:
        current = build_index(task, events, task.get("_knowledge_work_items", []), task_dir, delivery)
        return not current["issues"] and current == saved
    except (ValueError, OSError, TypeError):
        return False


def index_diff(old: dict, new: dict) -> dict:
    previous = {item["id"]: item["digest"] for item in old.get("items", [])}
    current = {item["id"]: item["digest"] for item in new.get("items", [])}
    return {"added": sorted(current.keys() - previous.keys()), "removed": sorted(previous.keys() - current.keys()),
            "changed": sorted(key for key in current.keys() & previous.keys() if current[key] != previous[key]),
            "unchanged": sorted(key for key in current.keys() & previous.keys() if current[key] == previous[key])}


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} requires concrete text")
    return value.strip()


def dependencies(item: dict, hashes: dict) -> dict:
    ids = item.get("input_ids")
    if (not isinstance(ids, list) or not ids or any(not isinstance(key, str) or key not in hashes for key in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("input_ids must name unique, current indexed inputs")
    return {key: hashes[key] for key in sorted(ids)}


def validate_assessment(value: dict, index: dict) -> dict:
    """Validate declarations and exact coverage before any search/index/Runtime write."""
    if not isinstance(value, dict) or value.get("schema") != SCHEMA or value.get("input_digest") != index["digest"]:
        raise ValueError("ASSESSMENT_INPUT_MISMATCH: use the current task-inputs digest")
    if index["issues"]:
        raise ValueError("LEARNING_INPUT_INCOMPLETE: " + "; ".join(index["issues"]))
    result = json.loads(json.dumps(value))
    hashes = {item["id"]: item["digest"] for item in index["items"]}
    coverage = result.get("coverage")
    if not isinstance(coverage, list):
        raise ValueError("coverage must be a list of actual per-input assessments")
    seen = set()
    for item in coverage:
        if not isinstance(item, dict):
            raise ValueError("coverage item must be an object")
        key = item.get("input_id")
        if not isinstance(key, str) or key not in hashes or key in seen or item.get("digest") != hashes[key]:
            raise ValueError("coverage must bind each current input exactly once")
        seen.add(key)
        _text(item.get("summary"), "coverage.summary")
        if item.get("classification") not in {"CURRENT", "TEMPORARY", "SUPERSEDED", "NO_DURABLE_INSIGHT"}:
            raise ValueError("coverage.classification is required")
        if item.get("classification") == "SUPERSEDED":
            replacement = item.get("superseded_by")
            if replacement == key or replacement not in hashes:
                raise ValueError("superseded coverage must reference a different current input")
    if seen != hashes.keys():
        raise ValueError("INPUT_COVERAGE_MISSING: " + ", ".join(sorted(hashes.keys() - seen)))
    candidates = result.get("knowledge")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("knowledge requires actual decisions, including no-value/search reasons")
    seen, covered, targets = set(), set(), set()
    for item in candidates:
        if not isinstance(item, dict):
            raise ValueError("knowledge candidate must be an object")
        key = _text(item.get("id"), "knowledge.id")
        if key in seen:
            raise ValueError("duplicate knowledge.id")
        seen.add(key)
        item["input_digests"] = dependencies(item, hashes)
        covered.update(item["input_ids"])
        if item.get("disposition") not in DISPOSITIONS:
            raise ValueError("invalid knowledge disposition")
        _text(item.get("reason"), "knowledge.reason")
        queries = item.get("queries")
        if not isinstance(queries, list) or not queries or any(not isinstance(q, str) or not q.strip() for q in queries):
            raise ValueError("each knowledge decision needs targeted queries")
        item["queries"] = [query.strip() for query in queries]
        ref = item.get("knowledge_ref")
        if item["disposition"] == "NO_DURABLE_INSIGHT":
            if ref:
                raise ValueError("NO_DURABLE_INSIGHT must not bind a canonical target")
        else:
            _text(ref, "knowledge_ref")
            if ref in targets:
                raise ValueError("combine decisions for the same canonical target")
            targets.add(ref)
    if covered != hashes.keys():
        raise ValueError("KNOWLEDGE_INPUT_COVERAGE_MISSING")
    memory = result.get("memory")
    if not isinstance(memory, dict) or not isinstance(memory.get("items"), list):
        raise ValueError("memory assessment is required, separately from persistence")
    _text(memory.get("summary"), "memory.summary")
    if not memory["items"]:
        _text(memory.get("no_items_reason"), "memory.no_items_reason")
    seen = set()
    for item in memory["items"]:
        if not isinstance(item, dict):
            raise ValueError("memory item must be an object")
        key = _text(item.get("id"), "memory.id")
        if key in seen:
            raise ValueError("duplicate memory.id")
        seen.add(key)
        item["input_digests"] = dependencies(item, hashes)
        _text(item.get("reason"), "memory.reason")
        kind, outcome = item.get("kind"), item.get("disposition")
        if kind not in {"RULE", "FACT", "PROCEDURE", "TEMPORARY", "SUPERSEDED"}:
            raise ValueError("invalid memory kind")
        if outcome not in {"SAVED", "COVERED", "SKIPPED", "NOT_PERSISTED", "RETAINED_IN_TASK"}:
            raise ValueError("invalid memory disposition")
        if kind in {"TEMPORARY", "SUPERSEDED"} and outcome not in {"SKIPPED", "RETAINED_IN_TASK"}:
            raise ValueError("temporary/superseded decisions must not become permanent rules")
        if outcome in {"SAVED", "COVERED"}:
            _text(item.get("target"), "memory.target")
            _text(item.get("excerpt"), "memory.excerpt")
            _text(item.get("scope"), "memory.scope")
            if kind == "RULE" and item.get("authorization_source") not in item["input_ids"]:
                raise ValueError("RULE requires a bound authorization_source, not an actor label")
            if kind in {"FACT", "PROCEDURE"}:
                _text(item.get("rediscovery_cost"), "memory.rediscovery_cost")
            if kind == "PROCEDURE" and type(item.get("created")) is not bool:
                raise ValueError("PROCEDURE requires created=true/false")
        if outcome == "NOT_PERSISTED":
            _text(item.get("responsibility"), "memory.responsibility")
            _text(item.get("recovery_condition"), "memory.recovery_condition")
    return result


def _memory_path(project_root: Path, target: str) -> Path:
    relative = target.split("#", 1)[0].replace("\\", "/")
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or ":" in relative:
        raise ValueError("memory target must be a project-relative path")
    if relative != "AGENTS.md" and not relative.startswith(".tp-spec/memory/"):
        raise ValueError("memory target must be root AGENTS.md or project Memory/Skill")
    resolved = (project_root / relative).resolve()
    if not resolved.is_relative_to(project_root.resolve()):
        raise ValueError("memory target resolves outside the current project")
    return resolved


def memory_readback(memory: dict, project_root: Path) -> dict:
    """Read back caller-written targets; never edit AGENTS/Memory or grant writes."""
    result = json.loads(json.dumps(memory))
    for item in result["items"]:
        if item["disposition"] not in {"SAVED", "COVERED"}:
            continue
        path = _memory_path(project_root, item["target"])
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig").replace("\r\n", "\n")
        if item["excerpt"].replace("\r\n", "\n") not in text:
            raise ValueError(f"MEMORY_READBACK_MISMATCH: {item['id']}")
        if item["kind"] == "PROCEDURE" and item.get("created"):
            import yaml
            from cli import frontmatter
            parts = frontmatter.split(text)
            front = yaml.safe_load(parts[0]) if parts else {}
            if not isinstance(front, dict) or front.get("status") != "candidate":
                raise ValueError("new Procedure must remain candidate; one success is not promotion")
        item["target_sha256"] = hashlib.sha256(raw).hexdigest()
    return result


def memory_status(memory: dict, project_root: Path | None = None) -> dict:
    warnings = []
    for item in memory.get("items", []):
        missing = item.get("disposition") == "NOT_PERSISTED"
        if project_root and item.get("disposition") in {"SAVED", "COVERED"}:
            try:
                path = _memory_path(project_root, item["target"])
                missing = hashlib.sha256(path.read_bytes()).hexdigest() != item.get("target_sha256")
            except (ValueError, OSError):
                missing = True
        if missing:
            warnings.append({"id": item["id"], "kind": item["kind"], "status": "NOT_PERSISTED_OR_CHANGED",
                "reason": item["reason"], "target": item.get("target"),
                "responsibility": item.get("responsibility") or "tp-integration-engineer",
                "recovery_condition": item.get("recovery_condition") or "核对来源与目标，仅在授权范围内恢复；当前已知约束继续遵守"})
    return {"status": "ASSESSED_WITH_UNPERSISTED" if warnings else "ASSESSED",
            "summary": memory.get("summary", ""), "warnings": warnings}


def valid_result(detail: dict, request: dict) -> bool:
    """Fail on a missing assessment, forged receipt shape or incomplete binding."""
    from cli.delivery_contract import validate_receipt_payload
    try:
        if detail.get("learning_schema") != SCHEMA:
            return False
        assessment = validate_assessment(detail["assessment"], request["detail"]["input_index"])
        if detail.get("assessment_digest") != digest(assessment):
            return False
        if not isinstance(detail.get("retrieval_context"), str) or len(detail["retrieval_context"]) != 64:
            return False
        results = detail["knowledge_results"]
        if not isinstance(results, list) or len(results) != len(assessment["knowledge"]):
            return False
        for candidate, result in zip(assessment["knowledge"], results):
            if any(result.get(key) != candidate.get(key) for key in ("id", "disposition", "knowledge_ref", "input_digests")):
                return False
            receipts = result.get("query_receipts")
            if not isinstance(receipts, list) or len(receipts) != len(candidate["queries"]):
                return False
            if any(validate_receipt_payload("search", receipt, expected_query=query)
                   for receipt, query in zip(receipts, candidate["queries"])):
                return False
            if candidate["disposition"] in {"DUPLICATE", "UPDATED"}:
                if candidate["knowledge_ref"] not in {ref for r in receipts for ref in r.get("matched_canonical_refs", [])}:
                    return False
            if candidate["disposition"] != "NO_DURABLE_INSIGHT":
                readback = result.get("canonical_readback")
                if (not isinstance(readback, dict) or readback.get("canonical_id") != candidate["knowledge_ref"]
                        or not readback.get("path") or len(str(readback.get("sha256") or "")) != 64):
                    return False
                if candidate["disposition"] in {"CREATED", "UPDATED"}:
                    index_receipt = result.get("index_receipt") or {}
                    if ((readback.get("lint") or {}).get("status") != "PASS"
                            or index_receipt.get("schema") != "tp-spec.knowledge-index-exact/v1"
                            or index_receipt.get("status") != "PASS"
                            or any(index_receipt.get(key) != readback.get(key) for key in ("canonical_id", "path", "sha256"))):
                        return False
        primary = next(item for disposition in ("CREATED", "UPDATED", "DUPLICATE", "NO_DURABLE_INSIGHT")
                       for item in results if item["disposition"] == disposition)
        if detail.get("knowledge_disposition") != primary["disposition"] or detail.get("knowledge_ref") != primary.get("knowledge_ref"):
            return False
        if detail.get("query_receipts") != [receipt for item in results for receipt in item["query_receipts"]]:
            return False
        if detail.get("source_refs") != request["detail"].get("source_refs"):
            return False
        if detail.get("input_digest") != request["detail"]["input_index"]["digest"]:
            return False
        expected_sources = [{"type": "local_file", "path": item["ref"], "sha256": item["digest"],
                             "hash_mode": item.get("hash_mode", "bytes")}
                            for item in request["detail"]["input_index"]["items"] if item["id"].startswith("file:")]
        if detail.get("source_items") != expected_sources:
            return False
        memory = detail["memory_assessment"]
        if any(memory.get(key) != value for key, value in assessment["memory"].items() if key != "items"):
            return False
        for actual, claimed in zip(memory["items"], assessment["memory"]["items"]):
            if any(actual.get(key) != value for key, value in claimed.items()):
                return False
            if actual["disposition"] in {"SAVED", "COVERED"} and not actual.get("target_sha256"):
                return False
        return len(memory["items"]) == len(assessment["memory"]["items"]) and memory.get("summary") == assessment["memory"]["summary"]
    except (ValueError, TypeError, KeyError, AttributeError):
        return False
