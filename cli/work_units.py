# -*- coding: utf-8 -*-
"""Scoped Work results, Fix recovery and Task integration over work_item/task_event.

Bindings describe recorded ownership and scope, not a sandbox or human identity.
No function here merges, commits, launches an agent, runs tests or edits a product.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
from pathlib import Path, PurePosixPath

from . import execution, security_authority as authority

SCHEMA = "tp-spec.work-unit/v1"
EVENT = "WORK_ITEM_RECORDED"
CANDIDATE = "WORK_INTEGRATION_RECORDED"
ACTIONS = {"create", "claim", "release", "retry", "result", "receive"}


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"WORK_FIELD_REQUIRED: {name}")
    return value.strip()


def _strings(value, name, *, required=False):
    return authority.strings(value, name, required=required)


def paths(value):
    result = _strings(value, "paths")
    for value in result:
        if ("\\" in value or PurePosixPath(value).is_absolute() or ":" in value
                or any(part in {"", ".", ".."} for part in value.split("/"))):
            raise ValueError(f"WORK_PATH_INVALID: use repository-relative POSIX paths: {value}")
    return result


def matches(path, patterns):
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _within(child, parents):
    # A literal child can be matched directly. For two patterns, do not guess
    # general glob-language containment: use equality or an explicit subtree.
    if not any(character in child for character in "*?["):
        return matches(child, parents)
    return any(child == parent or (parent.endswith("/**") and child.startswith(parent[:-2])) for parent in parents)


def task_dir(conn, task_id):
    return authority.task_directory(conn, task_id)


def references(conn, task_id, values, *, evidence=False):
    from .evidence import validate_evidence_path
    result = []
    for ref in _strings(values, "evidence_refs" if evidence else "scope_refs", required=True):
        if ref.startswith("event:"):
            try:
                eid = int(ref[6:])
            except ValueError as exc:
                raise ValueError("WORK_REFERENCE_INVALID: " + ref) from exc
            row = conn.execute("SELECT * FROM task_event WHERE task_id=? AND id=?", (task_id, eid)).fetchone()
            if not row:
                raise ValueError("WORK_REFERENCE_NOT_IN_TASK: " + ref)
            result.append({"ref": ref, "sha256": execution.digest(dict(row))})
        else:
            relative = ref.split("#", 1)[0]
            check = validate_evidence_path(task_dir(conn, task_id), relative, require_evidence_dir=evidence)
            if not check.ok:
                raise ValueError("WORK_REFERENCE_INVALID: " + check.error)
            result.append({"ref": ref, **check.item})
    return result


def check_references(conn, task_id, items, *, evidence=False):
    if not isinstance(items, list) or any(not isinstance(item, dict) or not isinstance(item.get("ref"), str) for item in items):
        raise ValueError("WORK_REFERENCE_RECORD_INVALID")
    current = references(conn, task_id, [item["ref"] for item in items], evidence=evidence)
    if current != items:
        raise ValueError("WORK_EVIDENCE_CHANGED: recorded source/evidence no longer matches")


def append(conn, task, action, payload, *, actor, agent="", item=None):
    from .execution_cmd import append_event
    body = {"action": action, **payload}
    return append_event(conn, task, CANDIDATE if action == "candidate" else EVENT,
        actor=actor, agent=agent, item=item, summary=body.get("summary") or f"Work {action}",
        producer="workitem", payload={"work_schema": SCHEMA, "work_payload": body,
                                     "work_digest": execution.digest(body)},
        result_status="COMPLETED" if action in {"result", "receive", "candidate"} else "RECORDED")


def trusted(row):
    row = dict(row)
    detail = execution.detail_of(row)
    if (row.get("event_type") not in {EVENT, CANDIDATE} or not execution._trusted(row, detail, "workitem")
            or detail.get("work_schema") != SCHEMA or not isinstance(detail.get("work_payload"), dict)
            or detail.get("work_digest") != execution.digest(detail["work_payload"])):
        return None
    body = detail["work_payload"]
    if not isinstance(body.get("action"), str) or body["action"] not in (ACTIONS if row["event_type"] == EVENT else {"candidate"}):
        return None
    action = body["action"]
    if action == "candidate":
        if not (isinstance(body.get("receipts"), dict) and isinstance(body.get("repo_roots"), list)
                and body["repo_roots"] and isinstance(body.get("change_set"), dict)
                and isinstance(body.get("change_set_id"), str) and isinstance(body.get("subject_digest"), str)
                and isinstance(body.get("evidence_items"), list) and isinstance(body.get("resolutions"), list)):
            return None
    elif not isinstance(row.get("work_item_id"), str) or not row["work_item_id"]:
        return None
    if action == "create":
        spec = body.get("spec")
        if not isinstance(spec, dict) or not isinstance(spec.get("kind"), str) or spec["kind"] not in {"WORK", "FIX"}:
            return None
        if (any(not execution._string_list(spec.get(k)) for k in ("roles", "paths", "ac_refs", "depends_on", "scope_refs"))
                or any(not isinstance(spec.get(k), str) or not spec[k] for k in ("step_id", "scope", "repo_root", "target_root"))
                or not isinstance(spec.get("isolation"), dict) or not isinstance(spec.get("security_context"), dict)
                or not isinstance(spec.get("shared_paths"), dict)):
            return None
    if action == "claim" and (type(body.get("attempt")) is not int or body["attempt"] < 1):
        return None
    if action == "result":
        result = body.get("result")
        if (not isinstance(result, dict) or not isinstance(result.get("artifact"), dict)
                or not isinstance(result["artifact"].get("kind"), str)
                or result["artifact"]["kind"] not in {"snapshot", "patch", "commit"}
                or any(not isinstance(result.get(k), list) for k in ("changed_paths", "outputs", "evidence_items"))
                or any(not isinstance(output, dict) or not isinstance(output.get("path"), str) for output in result["outputs"])
                or result.get("output_digest") != execution.digest(result["outputs"])):
            return None
    if action == "receive" and type(body.get("result_event_id")) is not int:
        return None
    return body


def project_units(rows):
    """Replay only registered Work facts. Legacy rows never acquire invented metadata."""
    units, candidates, issues = {}, [], []
    for raw in rows:
        row = dict(raw)
        if row.get("event_type") not in {EVENT, CANDIDATE}:
            continue
        body = trusted(row)
        if body is None:
            issues.append(f"WORK_FACT_INVALID:{row['id']}")
            continue
        action, wid = body["action"], row.get("work_item_id")
        if action == "candidate":
            candidates.append({"event_id": row["id"], "created_at": row["created_at"], **body})
            continue
        if action == "create":
            if wid in units or not isinstance(body.get("spec"), dict):
                issues.append(f"WORK_CREATE_INVALID:{row['id']}")
                continue
            units[wid] = {"item_id": wid, "spec": body["spec"], "create_event_id": row["id"],
                          "attempt": 0, "result": None, "receipt": None, "history": [],
                          "waiting_step_id": body["spec"].get("step_id"), "recorded_state": "PENDING"}
        unit = units.get(wid)
        if unit is None:
            issues.append(f"WORK_BINDING_INVALID:{row['id']}")
            continue
        record = {"event_id": row["id"], "created_at": row["created_at"],
                  "actor": row.get("actor_role"), "agent": row.get("actor_agent"), **body}
        permitted = {"PENDING": {"create", "claim"}, "ACTIVE": {"release", "result"}, "COMPLETED": {"receive", "retry"}}
        if action not in permitted[unit["recorded_state"]] or (action == "claim" and body["attempt"] != unit["attempt"] + 1):
            issues.append(f"WORK_TRANSITION_INVALID:{row['id']}")
            continue
        if action in {"result", "release"} and (row.get("actor_role"), row.get("actor_agent")) != (unit.get("owner_role"), unit.get("owner_agent")):
            issues.append(f"WORK_OWNER_INVALID:{row['id']}")
            continue
        unit["history"].append(record)
        if action == "claim":
            unit.update(attempt=body.get("attempt"), recorded_state="ACTIVE", owner_role=row.get("actor_role"),
                        owner_agent=row.get("actor_agent"))
        elif action in {"release", "retry"}:
            unit.update(result=None, receipt=None, recorded_state="PENDING", owner_role=None, owner_agent=None)
            if body.get("step_id"):
                unit["waiting_step_id"] = body["step_id"]
        elif action == "result":
            unit.update(result=record, receipt=None, recorded_state="COMPLETED")
        elif action == "receive":
            if not unit["result"] or body.get("result_event_id") != unit["result"]["event_id"]:
                issues.append(f"WORK_RECEIPT_INVALID:{row['id']}")
                continue
            unit["receipt"] = record
    return {"schema": SCHEMA, "units": units, "candidates": candidates, "issues": issues}


def read(conn, task_id):
    return project_units(execution.read_events(conn, task_id))


def checked_item(conn, task_id, item_id):
    item = conn.execute("SELECT * FROM work_item WHERE task_id=? AND item_id=?", (task_id, item_id)).fetchone()
    if not item:
        raise ValueError("WORK_ITEM_NOT_IN_TASK: " + item_id)
    return dict(item)


def dependencies(conn, task_id, values, *, self_id=None):
    values = _strings(values, "depends_on")
    for value in values:
        if value == self_id:
            raise ValueError("WORK_SELF_DEPENDENCY: " + value)
        checked_item(conn, task_id, value)
    return values


def require_dependencies(conn, task_id, item):
    facts = read(conn, task_id)
    pending = []
    for dependency in json.loads(item.get("depends_on_json") or "[]"):
        row = checked_item(conn, task_id, dependency)
        unit = facts["units"].get(dependency)
        if row["status"] != "COMPLETED" or (unit and not unit["receipt"]):
            pending.append(dependency)
    if pending:
        raise ValueError("WORK_DEPENDENCIES_PENDING: " + ", ".join(pending))


def coordinator(facts, actor, agent):
    owner = facts.get("coordinator") or {}
    if not owner or actor != owner.get("role") or (owner.get("agent") and agent != owner["agent"]):
        raise ValueError("WORK_COORDINATOR_REQUIRED: use the recorded Task coordinator; role strings are not authentication")


def normalize_spec(conn, task, facts, raw, *, item_id, kind="WORK", issue=None):
    from .execution_cmd import role_ids
    from .yaml_checks import check_acceptance_yaml
    raw = authority.obj(raw, {"scope", "scope_refs", "step_id", "roles", "paths", "ac_refs", "depends_on",
        "repo_root", "target_root", "isolation", "shared_paths", "security_context"}, "Work spec")
    if not facts.get("plan"):
        raise ValueError("WORK_PLAN_REQUIRED: adopt an explicit execution plan before scoped Work")
    step = next((s for s in facts["steps"] if s["id"] == raw.get("step_id")), None)
    previous = read(conn, task["task_id"])["units"]
    replay = item_id in previous or (kind == "FIX" and any(u["spec"].get("issue_key") == issue for u in previous.values()))
    if not step or (step["status"] == "COMPLETED" and not replay):
        raise ValueError("WORK_STEP_UNAVAILABLE: use an unfinished explicit step")
    if not replay and kind == "FIX" and (not facts["current_step"] or facts["current_step"]["id"] != step["id"]):
        raise ValueError("FIX_CURRENT_STEP_REQUIRED: a repair belongs to the current parent step")
    scope = _text(raw.get("scope"), "scope")
    scope_refs = _strings(raw.get("scope_refs"), "scope_refs", required=True)
    references(conn, task["task_id"], scope_refs)
    allowed_paths = paths(raw.get("paths", []))
    if step.get("paths") and any(not _within(p, step["paths"]) for p in allowed_paths):
        raise ValueError("WORK_OUTSIDE_PARENT_PATHS: child paths exceed the explicit step scope")
    acs = _strings(raw.get("ac_refs", []), "ac_refs")
    acceptance = check_acceptance_yaml((task_dir(conn, task["task_id"]) / "acceptance.md").read_text(encoding="utf-8-sig"))
    if set(acs) - set(acceptance.acceptance_ids):
        raise ValueError("WORK_AC_NOT_IN_TASK: " + ", ".join(sorted(set(acs) - set(acceptance.acceptance_ids))))
    if step.get("ac_refs") and set(acs) - set(step["ac_refs"]):
        raise ValueError("WORK_OUTSIDE_PARENT_AC")
    roles = _strings(raw.get("roles"), "roles", required=True)
    if set(roles) - role_ids() or (kind == "WORK" and set(roles) - set(step["roles"])):
        raise ValueError("WORK_ROLE_NOT_PLANNED: normal Work uses parent roles; Fix declares repair participants")
    root = task_dir(conn, task["task_id"]).parents[2]
    repo = Path(raw.get("repo_root") or root).expanduser().resolve()
    target = Path(raw.get("target_root") or root).expanduser().resolve()
    if not repo.is_dir() or not target.is_dir():
        raise ValueError("WORK_REPOSITORY_UNAVAILABLE")
    from .delivery_contract import load_repository_scope
    known = load_repository_scope(conn, task["task_id"])["repo_roots"] or [str(root.resolve())]
    if str(target) not in {str(Path(p).resolve()) for p in known}:
        raise ValueError("WORK_TARGET_OUTSIDE_TASK: bind the actual parent repository scope first")
    isolation = authority.obj(raw.get("isolation", {"mode": "sequential"}), {"mode", "reference"}, "isolation")
    if isolation.get("mode") not in {"sequential", "declared"}:
        raise ValueError("WORK_ISOLATION_INVALID: sequential or declared; neither asserts host enforcement")
    if isolation["mode"] == "declared":
        _text(isolation.get("reference"), "isolation.reference")
    shared = raw.get("shared_paths", {})
    if not isinstance(shared, dict):
        raise ValueError("WORK_SHARED_PATHS_INVALID")
    for path, owner in shared.items():
        paths([path]); _text(owner, "shared path owner")
        if not _within(path, allowed_paths):
            raise ValueError("WORK_SHARED_PATH_OUTSIDE_SCOPE")
        if owner != item_id:
            checked_item(conn, task["task_id"], owner)
    ctx = authority.normalize_context(raw.get("security_context") or {})
    ctx.update(paths=allowed_paths, ac_refs=acs)
    authority.check_effect(conn, task["task_id"], ctx)
    if ctx["effect_scope"] not in authority.READ_EFFECTS and not allowed_paths:
        raise ValueError("WORK_PATHS_REQUIRED: implementation Work needs explicit allowed paths")
    return {"kind": kind, "issue_key": issue, "step_id": step["id"], "scope": scope, "scope_refs": scope_refs,
        "roles": roles, "paths": allowed_paths, "ac_refs": acs,
        "depends_on": dependencies(conn, task["task_id"], raw.get("depends_on", []), self_id=item_id),
        "repo_root": str(repo), "target_root": str(target), "isolation": isolation,
        "shared_paths": shared, "security_context": ctx}


def create(conn, task, facts, *, item_id, title, spec, actor, agent):
    from .execution_cmd import record_step
    coordinator(facts, actor, agent)
    data = read(conn, task["task_id"])
    existing = data["units"].get(item_id)
    if spec["kind"] == "FIX":
        same = next((u for u in data["units"].values() if u["spec"].get("issue_key") == spec["issue_key"]), None)
        if same:
            existing = same
    if existing:
        if existing["spec"] != spec:
            raise ValueError("WORK_SPEC_CHANGED: do not reuse an issue/Work identity for different scope")
        return {"item_id": existing["item_id"], "event_id": existing["create_event_id"], "replayed": True}
    if conn.execute("SELECT 1 FROM work_item WHERE item_id=?", (item_id,)).fetchone():
        raise ValueError("WORK_ID_EXISTS: work_item IDs are globally unique; use a Task-prefixed ID")
    from . import db as dbmod
    now = dbmod.now_iso()
    conn.execute("INSERT INTO work_item (item_id,task_id,title,status,depends_on_json,allowed_paths_json,acceptance_refs_json,created_at,updated_at) VALUES (?,?,?,'PENDING',?,?,?,?,?)",
        (item_id, task["task_id"], title, json.dumps(spec["depends_on"]), json.dumps(spec["paths"]), json.dumps(spec["ac_refs"]), now, now))
    eid = append(conn, task, "create", {"spec": spec, "summary": title}, actor=actor, agent=agent, item=item_id)
    authority.append(conn, task["task_id"], authority.WORK, {"work_item_id": item_id, "context": spec["security_context"]},
                     actor=actor, summary="Work scope binding; not approval", item_id=item_id)
    if spec["kind"] == "FIX":
        step = facts["current_step"]
        if step["status"] == "ACTIVE":
            record_step(conn, task, facts, step_id=step["id"], plan_version=facts["plan_version"], action="wait",
                actor=actor, summary="等待当前范围 Fix Work；父流程不回退", wait_reason=title,
                expected_next=spec["roles"][0], waiting_items=[item_id])
    return {"item_id": item_id, "event_id": eid, "replayed": False}


def claim_guard(conn, task, item, unit, actor, agent):
    if task["current_state"] == "BLOCKED":
        raise ValueError("TASK_BLOCKED: resolve the existing task wait before implementation")
    require_dependencies(conn, task["task_id"], item)
    authority.check_work(conn, task["task_id"], item["item_id"])
    if not unit:
        return
    spec = unit["spec"]
    if actor not in spec["roles"]:
        raise ValueError("WORK_ROLE_MISMATCH")
    references(conn, task["task_id"], spec["scope_refs"])
    state = execution.read_execution(conn, task)
    step = next((s for s in state["steps"] if s["id"] == unit["waiting_step_id"]), None)
    if not step or step["status"] not in {"ACTIVE", "WAITING"}:
        raise ValueError("WORK_PARENT_NOT_CURRENT: start the parent step first")
    for other in conn.execute("SELECT * FROM work_item WHERE task_id=? AND status='ACTIVE' AND item_id<>?", (task["task_id"], item["item_id"])):
        other_unit = read(conn, task["task_id"])["units"].get(other["item_id"])
        if not other_unit:
            raise ValueError("WORK_ISOLATION_UNKNOWN: active legacy Work has no workspace binding")
        other_spec = other_unit["spec"]
        if spec["repo_root"] != other_spec["repo_root"]:
            continue
        if spec["isolation"]["mode"] == "sequential" or other_spec["isolation"]["mode"] == "sequential":
            raise ValueError("WORK_SEQUENTIAL_WAIT: " + other["item_id"])
        if any(authority._overlap(a, b) for a in spec["paths"] for b in other_spec["paths"]):
            raise ValueError("WORK_SHARED_PATH_BUSY: serialize shared files or use genuinely isolated workspaces")


def output_records(root, values):
    from .change_set import _path_record
    root = Path(root).resolve()
    result = []
    for path in paths(values):
        if any(c in path for c in "*?["):
            raise ValueError("WORK_RESULT_EXACT_PATH_REQUIRED")
        # A symlink is recorded as a symlink, never followed outside the bound root.
        if not (root / path).parent.resolve().is_relative_to(root):
            raise ValueError("WORK_RESULT_PATH_ESCAPES_REPOSITORY")
        result.append(_path_record(root, path, tracked=True))
    return result


def prepare_result(conn, task, item, unit, raw):
    raw = authority.obj(raw, {"summary", "changed_paths", "evidence_refs", "artifact", "limitations"}, "Work result")
    summary = _text(raw.get("summary"), "result.summary")
    changed = paths(raw.get("changed_paths", []))
    spec = unit["spec"]
    if any(not matches(path, spec["paths"]) for path in changed):
        raise ValueError("WORK_RESULT_OUTSIDE_SCOPE")
    for path in changed:
        if any(matches(path, [pattern]) and owner != item["item_id"] for pattern, owner in spec["shared_paths"].items()):
            raise ValueError("WORK_SHARED_PATH_NOT_OWNED: " + path)
    if changed and spec["security_context"]["effect_scope"] in authority.READ_EFFECTS:
        raise ValueError("WORK_INVESTIGATION_CANNOT_DELIVER_PRODUCT_CHANGE")
    evidence = references(conn, task["task_id"], raw.get("evidence_refs"), evidence=True)
    artifact = authority.obj(raw.get("artifact", {"kind": "snapshot"}), {"kind", "ref"}, "artifact")
    if not isinstance(artifact.get("kind"), str) or artifact["kind"] not in {"snapshot", "patch", "commit"}:
        raise ValueError("WORK_ARTIFACT_INVALID")
    if artifact["kind"] == "patch":
        artifact = {**artifact, "evidence": references(conn, task["task_id"], [_text(artifact.get("ref"), "artifact.ref")], evidence=True)}
        if len(artifact["evidence"]) != 1 or "path" not in artifact["evidence"][0]:
            raise ValueError("WORK_PATCH_FILE_REQUIRED: an event locator is not a patch")
        from .change_set import _run_git, ChangeSetError
        patch_path = str(task_dir(conn, task["task_id"]) / artifact["evidence"][0]["path"])
        try:
            # Forward numstat reports a rename's destination only. Reversing
            # the statistics (not applying the Patch) also checks its source.
            stats = [_run_git(Path(spec["repo_root"]), "apply", "--numstat", "-z", *direction, "--", patch_path)
                     for direction in ((), ("--reverse",))]
        except ChangeSetError as exc:
            raise ValueError("WORK_PATCH_INVALID: " + str(exc)) from exc
        touched = [part.split("\t", 2)[-1] for stat in stats for part in stat.split("\0") if part]
        if not touched or set(touched) - set(changed):
            raise ValueError("WORK_PATCH_SCOPE_MISMATCH: patch paths must be included in declared changed_paths")
    if artifact["kind"] == "commit":
        from .change_set import _run_git
        ref = _text(artifact.get("ref"), "artifact.ref")
        if ref.startswith("-"):
            raise ValueError("WORK_COMMIT_INVALID")
        artifact = {"kind": "commit", "ref": str(_run_git(Path(spec["repo_root"]), "rev-parse", "--verify", ref + "^{commit}")).strip()}
        head = str(_run_git(Path(spec["repo_root"]), "rev-parse", "HEAD")).strip()
        if artifact["ref"] != head or str(_run_git(Path(spec["repo_root"]), "status", "--porcelain", "--", *changed)).strip():
            raise ValueError("WORK_COMMIT_NOT_CURRENT_OUTPUT: use a workspace snapshot or the actual clean HEAD")
    outputs = output_records(spec["repo_root"], changed)
    return {"summary": summary, "changed_paths": changed, "outputs": outputs, "output_digest": execution.digest(outputs),
            "evidence_items": evidence, "evidence_refs": [e["ref"] for e in evidence], "artifact": artifact,
            "limitations": _strings(raw.get("limitations", []), "limitations"),
            "verification_scope": "declared Work result only; not Task PASS or automatic proof of unreported changes"}


def require_closed_sessions(conn, task, item_id):
    from .work_session_cmd import _open_sessions
    if any(row.get("work_item_id") == item_id for row in _open_sessions(conn, task["task_id"])):
        raise ValueError("WORK_SESSIONS_OPEN: close or hand off actual Work participations first")


def validate_result(conn, task_id, unit, *, source_output=False):
    if not unit["result"]:
        raise ValueError("WORK_RESULT_REQUIRED")
    body = unit["result"]["result"]
    check_references(conn, task_id, body["evidence_items"], evidence=True)
    if body["artifact"]["kind"] == "patch":
        check_references(conn, task_id, body["artifact"]["evidence"], evidence=True)
    if source_output and output_records(unit["spec"]["repo_root"], body["changed_paths"]) != body["outputs"]:
        raise ValueError("WORK_OUTPUT_CHANGED: source workspace no longer matches the reported result")


def candidate_binding(events):
    """Adapt an integration record to the existing Change Set consumer contract."""
    for event in reversed(list(events)):
        if event.get("event_type") != CANDIDATE:
            continue
        body = trusted(event)
        if body is None:
            raise ValueError("WORK_CANDIDATE_INVALID")
        return {"event": event, "event_id": int(event["id"]), "detail": body,
                "change_set_id": body["change_set_id"], "repo_roots": body["repo_roots"]}
    return None


def integration_status(conn, task, *, check_content=True, required_items=None):
    """Final checks require all units; a step resumption requires only its repairs.

    Both check all received inputs and the same actual Task product snapshot.
    A partial candidate is never sufficient to close a Task with unfinished Work.
    """
    data = read(conn, task["task_id"])
    if not data["units"]:
        return {"status": "NOT_REQUIRED", "issues": data["issues"], "candidate": None}
    candidate = data["candidates"][-1] if data["candidates"] else None
    required = set(data["units"]) if required_items is None else set(required_items)
    issues = list(data["issues"])
    issues.extend("WORK_ITEM_NOT_IN_TASK: " + wid for wid in sorted(required - data["units"].keys()))
    for wid, unit in data["units"].items():
        item = checked_item(conn, task["task_id"], wid)
        if item["status"] != unit["recorded_state"]:
            issues.append("WORK_ROW_FACT_MISMATCH: " + wid)
        if wid in required and not unit["receipt"]:
            issues.append("WORK_RESULT_NOT_RECEIVED: " + wid)
    if not candidate:
        issues.append("WORK_INTEGRATION_REQUIRED")
    else:
        receipts = {wid: u["receipt"]["event_id"] for wid, u in data["units"].items() if u["receipt"]}
        if receipts != candidate.get("receipts"):
            issues.append("WORK_CANDIDATE_INPUT_CHANGED")
        if check_content:
            try:
                from .change_set import capture_change_set, same_bound_product_content
                from .digest import compute_verification_subject_digest
                check_references(conn, task["task_id"], candidate["evidence_items"], evidence=True)
                for resolution in candidate["resolutions"]:
                    check_references(conn, task["task_id"], resolution["evidence_items"], evidence=True)
                for unit in data["units"].values():
                    if unit["receipt"]:
                        validate_result(conn, task["task_id"], unit)
                snapshot = capture_change_set(candidate["repo_roots"])
                if not same_bound_product_content(candidate, snapshot):
                    issues.append("WORK_CANDIDATE_PRODUCT_CHANGED")
                if candidate["subject_digest"] != compute_verification_subject_digest(task_dir(conn, task["task_id"])):
                    issues.append("WORK_CANDIDATE_SUBJECT_CHANGED")
            except (ValueError, OSError, RuntimeError) as exc:
                issues.append(str(exc))
    return {"status": "STALE" if candidate and issues else "MISSING" if not candidate else "CURRENT" if check_content else "RECORDED",
            "issues": issues, "candidate": candidate,
            "note": "Record-only integration; no merge/push/deployment or Task quality PASS is implied."}


def record_candidate(conn, task, facts, raw, *, actor, agent):
    from .change_set import capture_change_set
    from .record_first import _compact_change_set
    from .delivery_contract import load_repository_scope
    from .digest import compute_verification_subject_digest
    coordinator(facts, actor, agent)
    raw = authority.obj(raw, {"summary", "evidence_refs", "resolutions"}, "integration")
    data = read(conn, task["task_id"])
    if data["issues"]:
        raise ValueError("; ".join(data["issues"]))
    if not data["units"]:
        raise ValueError("WORK_INTEGRATION_EMPTY")
    # Tests/Review may themselves be Work still waiting on this repair. Record
    # the received subset now; final preflight still requires every necessary
    # Work and a candidate including all receipts. Never auto-complete them.
    if not any(unit["receipt"] for unit in data["units"].values()):
        raise ValueError("WORK_RESULT_NOT_RECEIVED: receive an actual result before integration")
    roots = load_repository_scope(conn, task["task_id"])["repo_roots"]
    if not roots:
        raise ValueError("WORK_PARENT_CHANGE_SET_REQUIRED: record the existing Task repository binding first")
    expected = {}
    receipts = {}
    for wid, unit in data["units"].items():
        item = checked_item(conn, task["task_id"], wid)
        if item["status"] != unit["recorded_state"]:
            raise ValueError("WORK_ROW_FACT_MISMATCH: " + wid)
        if not unit["receipt"]:
            continue
        validate_result(conn, task["task_id"], unit)
        authority.check_work(conn, task["task_id"], wid)
        receipts[wid] = unit["receipt"]["event_id"]
        for item in unit["result"]["result"]["outputs"]:
            expected.setdefault((unit["spec"]["target_root"], item["path"]), []).append((wid, item))
    resolutions = raw.get("resolutions", [])
    if not isinstance(resolutions, list):
        raise ValueError("WORK_RESOLUTIONS_INVALID")
    resolved = {}
    for value in resolutions:
        value = authority.obj(value, {"repo_root", "path", "owner", "reason", "evidence_refs"}, "resolution")
        key = (str(Path(value.get("repo_root") or roots[0]).resolve()), paths([value.get("path")])[0])
        if key not in expected or key in resolved or value.get("owner") not in {w for w, _ in expected[key]}:
            raise ValueError("WORK_CONFLICT_OWNER_INVALID")
        resolved[key] = {"repo_root": key[0], "path": key[1], "owner": value["owner"],
            "reason": _text(value.get("reason"), "resolution.reason"),
            "evidence_items": references(conn, task["task_id"], value.get("evidence_refs"), evidence=True)}
    integrated = []
    for key, values in sorted(expected.items()):
        root, path = key
        if root not in roots:
            raise ValueError("WORK_TARGET_OUTSIDE_TASK: " + root)
        actual = output_records(root, [path])[0]
        distinct = {execution.digest(value) for _, value in values}
        if (len(distinct) > 1 or actual != values[0][1]) and key not in resolved:
            raise ValueError("WORK_INTEGRATION_CONFLICT: explicit coordinator disposition required for " + path)
        integrated.append({"repo_root": root, **actual})
    evidence = references(conn, task["task_id"], raw.get("evidence_refs"), evidence=True)
    snapshot = capture_change_set(roots)
    outstanding = [row["item_id"] for row in conn.execute(
        "SELECT item_id,status FROM work_item WHERE task_id=? ORDER BY item_id", (task["task_id"],))
        if row["status"] != "COMPLETED" or (row["item_id"] in data["units"] and row["item_id"] not in receipts)]
    payload = {"summary": _text(raw.get("summary"), "integration.summary"), "receipts": receipts,
        "outstanding_work_items": outstanding,
        "integrated_outputs": integrated, "resolutions": list(resolved.values()), "evidence_items": evidence,
        "repo_roots": roots, "change_set_id": snapshot["content_digest"], "change_set": _compact_change_set(snapshot),
        "subject_digest": compute_verification_subject_digest(task_dir(conn, task["task_id"])), "effect_scope": "record_only"}
    previous = data["candidates"][-1] if data["candidates"] else {}
    if all(previous.get(k) == v for k, v in payload.items()):
        return {"event_id": previous["event_id"], "change_set_id": payload["change_set_id"], "replayed": True}
    eid = append(conn, task, "candidate", payload, actor=actor, agent=agent)
    return {"event_id": eid, "change_set_id": payload["change_set_id"], "replayed": False}


def step_guard(conn, task, facts, step, action):
    data = read(conn, task["task_id"])
    relevant = [u for u in data["units"].values() if u["waiting_step_id"] == step["id"]]
    if data["issues"]:
        raise ValueError("; ".join(data["issues"]))
    if action in {"resume", "complete"}:
        fixes = [u for u in relevant if u["spec"]["kind"] == "FIX"]
        needed = relevant if action == "complete" else fixes
        if any(not u["receipt"] for u in needed):
            raise ValueError("WORK_RESULT_NOT_RECEIVED: receive required child results before resuming/completing parent")
        if fixes:
            status = integration_status(conn, task, required_items=[u["item_id"] for u in needed])
            if status["issues"]:
                raise ValueError("; ".join(status["issues"]))
        if action == "complete" and fixes:
            last_receipt = max(u["receipt"]["event_id"] for u in fixes)
            from .workflow_records import _latest_trusted_verification, _latest_trusted_code_review
            if step["phase"] in {"verification", "review"}:
                verification, subject, snapshot, _ = _latest_trusted_verification(conn, task["task_id"], task_dir(conn, task["task_id"]))
                if step["phase"] == "review":
                    review = _latest_trusted_code_review(conn, task["task_id"], task_dir=task_dir(conn, task["task_id"]),
                        subject_digest=subject, change_set_id=snapshot["content_digest"], verification_event_id=int(verification.row["id"]))
            elif step["phase"] == "delivery":
                from .orchestration import _delivery_completion_event
                delivery = _delivery_completion_event(execution.read_events(conn, task["task_id"]),
                    task_dir(conn, task["task_id"]), task=task)
                if not delivery or int(delivery["id"]) <= last_receipt:
                    raise ValueError("FIX_DELIVERY_RECHECK_REQUIRED: receive current delivery facts after the fix")
    return relevant
