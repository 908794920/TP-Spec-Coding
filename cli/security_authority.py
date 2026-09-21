# -*- coding: utf-8 -*-
"""Scoped security-change authority on the existing task_event ledger.

This checks registered declarations and local source attribution, not human
identity or arbitrary diff semantics. Findings, tools and stored prose cannot
mint a grant. Unrelated work and read-only investigation remain available.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
from pathlib import Path, PurePosixPath
from datetime import datetime
import re
from typing import Any
import uuid

from . import db as dbmod, event_contract, event_policies
from .evidence import validate_evidence_path
from .version import active_version
from .workflow_controls import trusted_event_detail

SCHEMA = "tp-spec.security-authority/v1"
SOURCE = "HUMAN_AUTHORITY_RECORDED"
PROPOSAL = "SECURITY_PROPOSAL_RECORDED"
WORK = "SECURITY_WORK_BOUND"
OBSERVATION = "SECURITY_EVIDENCE_RECORDED"
DECISION = "SCOPE_CHANGE"
EFFECTS = {"implementation", "regression", "review_blocker", "read_only", "isolated_poc", "record_only"}
READ_EFFECTS = {"read_only", "isolated_poc", "record_only"}
DISCOVERY_SOURCES = {"HUMAN_REQUIREMENT", "HUMAN_APPROVAL", "AGENT", "REVIEW", "SCANNER", "TEST", "TOOL", "DOCUMENT"}
IDENTITY_LIMIT = "LOCAL_ATTESTATION_ONLY: source bytes and declared human provenance are checked; no host signature or human authentication"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def text(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"SECURITY_INPUT_INVALID: {name} must be a non-empty string")
    return value.strip()


def obj(value, allowed, name):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(f"SECURITY_INPUT_INVALID: invalid/unknown {name} fields")
    return value


def strings(value, name, *, required=False):
    if not isinstance(value, list) or (required and not value):
        raise ValueError(f"SECURITY_INPUT_INVALID: {name} must be a {'non-empty ' if required else ''}list")
    values = [text(v, name) for v in value]
    if len(set(values)) != len(values):
        raise ValueError(f"SECURITY_INPUT_INVALID: duplicate {name}")
    return sorted(values)


def identifier(value, name):
    result = text(value, name)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", result):
        raise ValueError(f"SECURITY_INPUT_INVALID: invalid {name}")
    return result


def normalize_scopes(values):
    if not isinstance(values, list) or not values:
        raise ValueError("SECURITY_SCOPE_REQUIRED: at least one concrete scope unit")
    result, seen = [], set()
    for raw in values:
        row = obj(raw, {"id", "paths", "ac_refs", "before", "after", "conditions"}, "scope")
        sid = identifier(row.get("id"), "scope.id")
        if sid in seen:
            raise ValueError("SECURITY_INPUT_INVALID: duplicate scope.id")
        paths = strings(row.get("paths", []), "scope.paths")
        for path in paths:
            if (path.startswith("/") or "\\" in path or ":" in path or any(c in path for c in "*?[")
                    or ".." in PurePosixPath(path).parts or path in {".", "./"}):
                raise ValueError("SECURITY_PATH_INVALID: use literal repo-relative files/directories, no globs")
        paths = sorted({PurePosixPath(p).as_posix().rstrip("/") for p in paths})
        acs = strings(row.get("ac_refs", []), "scope.ac_refs")
        if not paths and not acs:
            raise ValueError("SECURITY_SCOPE_REQUIRED: paths or exact requirement/AC refs")
        result.append({"id": sid, "paths": paths, "ac_refs": acs,
                       **{key: text(row.get(key), "scope." + key) for key in ("before", "after", "conditions")}})
        seen.add(sid)
    return sorted(result, key=lambda s: s["id"])


def scope_digest(scope):
    # Titles/IDs cannot turn the same declared behaviour into a new approval.
    return digest({k: v for k, v in scope.items() if k != "id"})


def task_directory(conn, task_id):
    row = conn.execute("SELECT p.root_path FROM task t JOIN project p ON p.project_id=t.project_id WHERE t.task_id=?", (task_id,)).fetchone()
    if not row or not row["root_path"]:
        raise ValueError("SECURITY_TASK_UNBOUND: task has no project workspace")
    return Path(row["root_path"]) / ".tp-spec" / "tasks" / task_id


def evidence_item(task_dir, ref):
    check = validate_evidence_path(task_dir, ref, require_evidence_dir=True)
    if not check.ok:
        raise ValueError("SECURITY_EVIDENCE_INVALID: " + check.error)
    if isinstance(ref, dict) and check.sha256 != ref.get("sha256"):
        raise ValueError("SECURITY_SOURCE_CHANGED: source evidence bytes no longer match")
    return check.item


def read_json_evidence(task_dir, ref):
    item = evidence_item(task_dir, ref)
    raw = (Path(task_dir) / item["path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != item["sha256"]:
        raise ValueError("SECURITY_SOURCE_CHANGED: evidence changed during read")
    return json.loads(raw.decode("utf-8-sig")), item


def append(conn, task_id, event_type, payload, *, actor, summary, transaction_id=None, item_id=None):
    producer = "task_scope_change" if event_type == DECISION else "security_authority"
    now = dbmod.now_iso()
    detail = {"security_schema": SCHEMA, "security_payload": payload, "security_digest": digest(payload),
              "transaction_id": transaction_id or uuid.uuid4().hex, "producer": producer,
              "schema_version": active_version(), "task_id": task_id, "actor_role": actor, "created_at": now}
    if event_type == DECISION:
        detail.update(scope_id=payload["proposal_id"], summary=summary)
    detail = event_contract.add_event_semantics(detail, event_type=event_type,
        operation="SCOPE_CHANGE" if event_type == DECISION else "RECORD", result_status="RECORDED", producer=producer)
    cursor = conn.execute("INSERT INTO task_event (task_id,event_type,actor_role,work_item_id,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (task_id, event_type, actor, item_id, summary, json.dumps(detail, ensure_ascii=False), active_version(), now))
    conn.execute("UPDATE task SET updated_at=? WHERE task_id=?", (now, task_id))
    return int(cursor.lastrowid)


def project(events, task_id, task_dir=None):
    """Read-only projection. Old events are history, never implicit new grants."""
    state = {"schema": SCHEMA, "task_id": task_id, "sources": {}, "proposals": {}, "versions": {},
             "decisions": [], "work": {}, "observations": [], "identity_limit": IDENTITY_LIMIT}
    for event0 in events:
        event = dict(event0)
        et = event.get("event_type")
        if et not in {SOURCE, PROPOSAL, WORK, DECISION, OBSERVATION}:
            continue
        try:
            detail = json.loads(event.get("detail_json") or "{}")
        except (ValueError, TypeError):
            if et == DECISION:
                continue  # Legacy scope notes do not provide security authority.
            raise ValueError("SECURITY_RECORD_INVALID: unreadable registered event")
        if et == DECISION and (not isinstance(detail, dict) or "security_schema" not in detail):
            continue
        producer = "task_scope_change" if et == DECISION else "security_authority"
        payload = detail.get("security_payload") if isinstance(detail, dict) else None
        if (event.get("task_id") != task_id or not isinstance(payload, dict)
                or detail.get("security_schema") != SCHEMA or detail.get("security_digest") != digest(payload)
                or not event_policies.event_allowed_for_producer(et, producer)
                or trusted_event_detail(event, event_type=et, producer=producer, actor=event.get("actor_role")) is None
                or event_contract.validate_event_semantics(et, detail)):
            raise ValueError(f"SECURITY_RECORD_INVALID: event {event.get('id')}")
        try:
            if et == SOURCE:
                if normalize_source(payload["body"], task_id) != payload["body"] or not isinstance(payload["evidence"], dict):
                    raise ValueError("source structure")
            elif et == PROPOSAL:
                pid = identifier(payload["proposal_id"], "proposal_id")
                if type(payload["version"]) is not int or payload["version"] < 1:
                    raise ValueError("proposal version")
                _, _, body = normalize_proposal({"proposal_id": pid, "expected_version": payload["version"] - 1, **payload["body"]})
                if body != payload["body"]:
                    raise ValueError("proposal structure")
            elif et == DECISION:
                if payload["decision"] not in {"APPROVE", "REJECT", "DEFER"} or type(payload["human_event_id"]) is not int:
                    raise ValueError("decision structure")
                strings(payload["scope_ids"], "decision scope", required=True)
                if not isinstance(payload["approved_scope"], dict) or type(payload["proposal_version"]) is not int:
                    raise ValueError("decision binding")
                identifier(payload["proposal_id"], "proposal_id")
                text(payload["proposal_digest"], "proposal_digest")
            elif et in {WORK, OBSERVATION}:
                normalize_context(payload["context"])
                if et == WORK:
                    text(payload["work_item_id"], "work_item_id")
                elif payload["purpose"] != "investigation_only" or not isinstance(payload["evidence"], list):
                    raise ValueError("observation structure")
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"SECURITY_RECORD_INVALID: event {event.get('id')}: {exc}") from exc
        value = {**payload, "event_id": event["id"], "recorded_at": event["created_at"]}
        if et == SOURCE:
            state["sources"][event["id"]] = value
        elif et == PROPOSAL:
            pid = payload["proposal_id"]
            history = state["versions"].setdefault(pid, {})
            if payload["version"] != len(history) + 1 or payload["proposal_digest"] != digest(payload["body"]):
                raise ValueError("SECURITY_RECORD_INVALID: proposal version/digest")
            history[payload["version"]] = value
            state["proposals"][pid] = value
        elif et == DECISION:
            state["decisions"].append(value)
        elif et == OBSERVATION:
            state["observations"].append(value)
        else:
            state["work"][payload["work_item_id"]] = value
    state["task_dir"] = str(task_dir) if task_dir is not None else None
    return state


def read(conn, task_id, task_dir=None):
    rows = conn.execute("SELECT * FROM task_event WHERE task_id=? AND event_type IN (?,?,?,?,?) ORDER BY id",
                        (task_id, SOURCE, PROPOSAL, WORK, DECISION, OBSERVATION)).fetchall()
    return project(rows, task_id, task_dir if task_dir is not None else task_directory(conn, task_id))


def normalize_source(raw, task_id):
    raw = obj(raw, {"schema", "task_id", "origin", "kind", "channel", "message_id", "occurred_at", "statement", "binding"}, "human source")
    if (raw.get("schema") != "tp-spec.human-authority/v1" or raw.get("task_id") != task_id
            or raw.get("origin") != "human" or raw.get("kind") not in {"HUMAN_REQUIREMENT", "HUMAN_APPROVAL"}):
        raise ValueError("SECURITY_HUMAN_SOURCE_REQUIRED: original human statement, not agent/tool/generated content")
    body = {key: text(raw.get(key), key) for key in ("schema", "task_id", "origin", "kind", "channel", "message_id", "occurred_at", "statement")}
    try:
        occurred = datetime.fromisoformat(body["occurred_at"])
        if occurred.utcoffset() is None:
            raise ValueError("timezone required")
    except ValueError as exc:
        raise ValueError("SECURITY_HUMAN_TIME_REQUIRED: original message time with timezone") from exc
    if raw["kind"] == "HUMAN_REQUIREMENT":
        binding = obj(raw.get("binding"), {"scopes"}, "requirement binding")
        body["binding"] = {"scopes": normalize_scopes(binding.get("scopes"))}
    else:
        binding = obj(raw.get("binding"), {"proposal_id", "proposal_version", "proposal_digest", "decision", "scope_ids"}, "approval binding")
        if type(binding.get("proposal_version")) is not int or binding["proposal_version"] < 1:
            raise ValueError("SECURITY_INPUT_INVALID: proposal_version must be a positive integer")
        if binding.get("decision") not in {"APPROVE", "REJECT", "DEFER"}:
            raise ValueError("SECURITY_INPUT_INVALID: decision must be APPROVE|REJECT|DEFER")
        if not re.fullmatch(r"[0-9a-f]{64}", str(binding.get("proposal_digest", ""))):
            raise ValueError("SECURITY_INPUT_INVALID: invalid proposal_digest")
        body["binding"] = {**binding, "proposal_id": identifier(binding.get("proposal_id"), "proposal_id"),
                           "scope_ids": strings(binding.get("scope_ids"), "scope_ids", required=True)}
    return body


def source_valid(state, source):
    try:
        if not state.get("task_dir"):
            return False
        raw, _ = read_json_evidence(state["task_dir"], source["evidence"])
        return normalize_source(raw, state["task_id"]) == source["body"]
    except (ValueError, OSError, KeyError, TypeError):
        return False


def prepare_source(conn, task_id, task_dir, ref, *, attested):
    if not attested:
        raise ValueError("SECURITY_HUMAN_ATTESTATION_REQUIRED: importer must check the original human message; actor name is insufficient")
    raw, item = read_json_evidence(task_dir, ref)
    body = normalize_source(raw, task_id)
    state = read(conn, task_id, task_dir)
    for prior in state["sources"].values():
        if (prior["body"]["channel"], prior["body"]["message_id"]) == (body["channel"], body["message_id"]):
            if prior["body"] != body:
                raise ValueError("SECURITY_HUMAN_SOURCE_CONFLICT: the same human message cannot be rebound")
            if not source_valid(state, prior):
                raise ValueError("SECURITY_SOURCE_CHANGED: restore the original source evidence")
            return None, prior["event_id"]
    return {"body": body, "evidence": item, "verification": "LOCAL_ATTESTATION_ONLY"}, None


def normalize_proposal(raw):
    raw = obj(raw, {"proposal_id", "expected_version", "title", "discovery", "observable_change", "scopes",
                   "risk", "no_change_impact", "compatibility", "cost", "alternatives", "recommendation",
                   "existing_authority", "restoration"}, "proposal")
    pid = identifier(raw.get("proposal_id"), "proposal_id")
    expected = raw.get("expected_version")
    if type(expected) is not int or expected < 0 or type(raw.get("observable_change")) is not bool:
        raise ValueError("SECURITY_INPUT_INVALID: expected_version integer >= 0 and observable_change boolean required")
    discovery = obj(raw.get("discovery"), {"source", "evidence", "facts", "inferences"}, "discovery")
    if discovery.get("source") not in DISCOVERY_SOURCES:
        raise ValueError("SECURITY_INPUT_INVALID: invalid discovery source (not an authority grant)")
    body = {key: text(raw.get(key), key) for key in ("title", "risk", "no_change_impact", "compatibility", "cost", "alternatives", "recommendation")}
    body.update(observable_change=raw["observable_change"], scopes=normalize_scopes(raw.get("scopes")),
                discovery={"source": discovery["source"], "evidence": strings(discovery.get("evidence"), "discovery.evidence", required=True),
                           "facts": text(discovery.get("facts"), "discovery.facts"), "inferences": text(discovery.get("inferences"), "discovery.inferences")})
    if not body["observable_change"] and any(s["before"] != s["after"] for s in body["scopes"]):
        raise ValueError("SECURITY_BEHAVIOR_CONFLICT: differing before/after cannot be declared unobservable")
    auth = raw.get("existing_authority", [])
    if not isinstance(auth, list) or any(type(e) is not int or e < 1 for e in auth) or len(set(auth)) != len(auth):
        raise ValueError("SECURITY_INPUT_INVALID: existing_authority must contain unique human source event IDs")
    body["existing_authority"] = sorted(auth)
    if raw.get("restoration") is not None:
        restore = obj(raw["restoration"], {"human_event_id", "scope_id", "evidence", "reason"}, "restoration")
        if type(restore.get("human_event_id")) is not int:
            raise ValueError("SECURITY_INPUT_INVALID: restoration needs original human requirement event")
        body["restoration"] = {**restore, "scope_id": identifier(restore.get("scope_id"), "restoration.scope_id"),
            "evidence": strings(restore.get("evidence"), "restoration.evidence", required=True), "reason": text(restore.get("reason"), "restoration.reason")}
    return pid, expected, body


def prepare_proposal(conn, task_id, task_dir, raw):
    pid, expected, body = normalize_proposal(raw)
    state = read(conn, task_id, task_dir)
    prior = state["proposals"].get(pid)
    if prior and prior["body"] == body:
        return None, prior["event_id"]
    if prior:
        old_ids = {scope_digest(s): s["id"] for version in state["versions"][pid].values() for s in version["body"]["scopes"]}
        if any(scope_digest(s) in old_ids and old_ids[scope_digest(s)] != s["id"] for s in body["scopes"]):
            raise ValueError("SECURITY_SCOPE_RENAME: preserve scope IDs and their decision history")
    if expected != (prior or {}).get("version", 0):
        raise ValueError("SECURITY_PROPOSAL_CHANGED: reread the latest version")
    from .execution_cmd import validate_refs
    validate_refs(conn, task_id, body["discovery"]["evidence"])
    for ref in body["discovery"]["evidence"]:
        if ref.startswith("evidence/"):
            evidence_item(task_dir, ref)
    for hid in body["existing_authority"]:
        src = state["sources"].get(hid)
        if not src or src["body"]["kind"] != "HUMAN_REQUIREMENT" or not source_valid(state, src):
            raise ValueError("SECURITY_HUMAN_SOURCE_REQUIRED: existing_authority must reference valid same-Task HUMAN_REQUIREMENT")
    for other_id, history in state["versions"].items():
        if other_id != pid and ({scope_digest(s) for s in body["scopes"]} & {scope_digest(s) for v in history.values() for s in v["body"]["scopes"]}):
            raise ValueError(f"SECURITY_PROPOSAL_DUPLICATE: reuse {other_id}; renaming does not change the recorded decision")
    if "restoration" in body:
        restore = body["restoration"]
        src = state["sources"].get(restore["human_event_id"])
        old = next((s for s in (src or {}).get("body", {}).get("binding", {}).get("scopes", []) if s["id"] == restore["scope_id"]), None)
        if not old or not source_valid(state, src) or any(
            s["paths"] != old["paths"] or s["ac_refs"] != old["ac_refs"] or s["after"] != old["after"] or s["conditions"] != old["conditions"] for s in body["scopes"]):
            raise ValueError("SECURITY_RESTORATION_UNPROVEN: restore the exact original approved semantics, not substitute hardening")
        for ref in restore["evidence"]:
            evidence_item(task_dir, ref)
    return {"proposal_id": pid, "version": expected + 1, "proposal_digest": digest(body), "body": body}, None


def prepare_decision(conn, task_id, task_dir, *, proposal_id, version, proposal_digest, decision, scope_ids, human_event_id):
    state = read(conn, task_id, task_dir)
    proposal = state["proposals"].get(proposal_id)
    if not proposal or proposal["version"] != version or proposal["proposal_digest"] != proposal_digest:
        raise ValueError("SECURITY_PROPOSAL_CHANGED: decision must bind the latest exact proposal version/digest")
    ids = strings(scope_ids, "approved_scope", required=True)
    if set(ids) - {s["id"] for s in proposal["body"]["scopes"]} or decision not in {"APPROVE", "REJECT", "DEFER"}:
        raise ValueError("SECURITY_DECISION_SCOPE_INVALID")
    binding = {"proposal_id": proposal_id, "proposal_version": version, "proposal_digest": proposal_digest,
               "decision": decision, "scope_ids": ids}
    source = state["sources"].get(human_event_id)
    if not source or source["body"]["kind"] != "HUMAN_APPROVAL" or not source_valid(state, source) or source["body"]["binding"] != binding:
        raise ValueError("SECURITY_HUMAN_BINDING_MISMATCH: same-Task source, proposal, digest, decision and exact scope are required")
    payload = {**binding, "human_event_id": human_event_id,
               "approved_scope": {s["id"]: scope_digest(s) for s in proposal["body"]["scopes"] if s["id"] in ids}}
    relevant = [d for d in state["decisions"] if d["proposal_id"] == proposal_id and set(ids) & set(d["scope_ids"])]
    source_time = datetime.fromisoformat(source["body"]["occurred_at"])
    if relevant and any(_decision_order(state, d)[:2] > (source_time, human_event_id) for d in relevant):
        raise ValueError("SECURITY_DECISION_SUPERSEDED: an older source cannot restore superseded approval")
    exact = next((d for d in reversed(relevant) if all(d.get(k) == v for k, v in payload.items())), None)
    if exact:
        return None, exact["event_id"]
    return payload, None


def _decision_order(state, decision):
    source = state["sources"].get(decision["human_event_id"])
    if source is None:
        raise ValueError("SECURITY_RECORD_INVALID: decision source event missing")
    return datetime.fromisoformat(source["body"]["occurred_at"]), source["event_id"], decision["event_id"]


def scope_status(state, proposal, unit):
    sid, fingerprint = unit["id"], scope_digest(unit)
    # Latest decision for this scope ID wins, including reject/defer. Never
    # search backwards for an older PASS after a newer non-approval.
    decisions = [d for d in state["decisions"] if d["proposal_id"] == proposal["proposal_id"] and sid in d["scope_ids"]]
    if decisions:
        latest = max(decisions, key=lambda d: _decision_order(state, d))
        source = state["sources"].get(latest["human_event_id"])
        binding = {k: latest[k] for k in ("proposal_id", "proposal_version", "proposal_digest", "decision", "scope_ids")}
        old = state["versions"].get(proposal["proposal_id"], {}).get(latest["proposal_version"])
        if (not source or not source_valid(state, source) or source["body"].get("binding") != binding
                or not old or old["proposal_digest"] != latest["proposal_digest"]):
            return {"status": "SOURCE_INVALID", "decision_event_id": latest["event_id"]}
        if latest["decision"] != "APPROVE":
            return {"status": latest["decision"], "decision_event_id": latest["event_id"]}
        if latest["approved_scope"].get(sid) == fingerprint:
            return {"status": "APPROVED", "decision_event_id": latest["event_id"], "human_event_id": source["event_id"]}
        return {"status": "STALE_APPROVAL", "decision_event_id": latest["event_id"]}
    if not proposal["body"]["observable_change"]:
        return {"status": "NO_BEHAVIOR_CHANGE"}
    for hid in proposal["body"]["existing_authority"]:
        source = state["sources"].get(hid)
        if source and source_valid(state, source) and any(scope_digest(s) == fingerprint for s in source["body"]["binding"].get("scopes", [])):
            return {"status": "ALREADY_AUTHORIZED", "human_event_id": hid}
    restore = proposal["body"].get("restoration")
    if restore:
        source = state["sources"].get(restore["human_event_id"])
        if source and source_valid(state, source):
            original = next((s for s in source["body"]["binding"].get("scopes", []) if s["id"] == restore["scope_id"]), None)
            if original and all(unit[k] == original[k] for k in ("paths", "ac_refs", "after", "conditions")):
                try:
                    for ref in restore["evidence"]:
                        evidence_item(state["task_dir"], ref)
                    return {"status": "RESTORE_AUTHORIZED", "human_event_id": source["event_id"]}
                except (OSError, ValueError):
                    return {"status": "RESTORATION_EVIDENCE_INVALID"}
    return {"status": "PENDING_APPROVAL"}


ALLOWED = {"APPROVED", "ALREADY_AUTHORIZED", "NO_BEHAVIOR_CHANGE", "RESTORE_AUTHORIZED"}


def registered_scopes(state, proposal):
    """Keep removed scope IDs enforceable without retaining them as current work.

    Dropping a rejected unit from a newer proposal is not a human approval of
    its implementation. Reintroduce its original ID for an explicit decision.
    """
    units = {}
    for version in state["versions"].get(proposal["proposal_id"], {}).values():
        for unit in version["body"]["scopes"]:
            units[unit["id"]] = unit
    return list(units.values())


def summary(state):
    proposals = []
    for p in state["proposals"].values():
        units = [{**s, **scope_status(state, p, s)} for s in p["body"]["scopes"]]
        proposals.append({"proposal_id": p["proposal_id"], "version": p["version"], "proposal_digest": p["proposal_digest"],
            "title": p["body"]["title"], "event_id": p["event_id"], "discovery": p["body"]["discovery"], "scopes": units,
            "removed_scopes": [{**s, **scope_status(state, p, s)} for s in registered_scopes(state, p)
                               if s["id"] not in {unit["id"] for unit in units}],
            "status": "AUTHORIZED" if all(s["status"] in ALLOWED for s in units) else "DECISION_REQUIRED"})
    return {"schema": SCHEMA, "task_id": state["task_id"], "proposals": proposals,
            "decisions": state["decisions"], "identity_limit": IDENTITY_LIMIT,
            "effect_authorization": "not granted by this projection; recheck at the actual effect boundary"}


def _overlap(a, b):
    a, b = a.replace("\\", "/").rstrip("/"), b.replace("\\", "/").rstrip("/")
    # WorkItem paths already accept globs. Literal prefixes keep ancestor scopes
    # conservative; no filesystem scan is needed to decide a declared overlap.
    if fnmatch.fnmatchcase(a, b) or fnmatch.fnmatchcase(b, a) or a.startswith(b + "/") or b.startswith(a + "/"):
        return True
    for pattern, literal in ((a, b), (b, a)):
        prefix = re.split(r"[*?\[]", pattern, maxsplit=1)[0].rstrip("/")
        if prefix != pattern and (not prefix or literal.startswith(prefix + "/") or prefix.startswith(literal + "/")):
            return True
    return False


def normalize_context(raw=None):
    raw = obj(raw or {}, {"effect_scope", "security_changes", "paths", "ac_refs"}, "security context")
    effect = raw.get("effect_scope", "implementation")
    if effect not in EFFECTS:
        raise ValueError("SECURITY_EFFECT_INVALID")
    return {"effect_scope": effect, **{key: strings(raw.get(key, []), key) for key in ("security_changes", "paths", "ac_refs")}}


def check(state, context=None, *, unknown_is_error=True):
    ctx = normalize_context(context)
    explicit = set(ctx["security_changes"])
    known = set(state["proposals"])
    known |= {p["proposal_id"] + "#" + s["id"] for p in state["proposals"].values() for s in registered_scopes(state, p)}
    if explicit - known:
        raise ValueError("SECURITY_PROPOSAL_UNKNOWN: " + ", ".join(sorted(explicit - known)))
    blocked, checks = [], []
    for p in state["proposals"].values():
        for unit in registered_scopes(state, p):
            key = p["proposal_id"] + "#" + unit["id"]
            status = scope_status(state, p, unit)
            # Explicit behaviour units disambiguate two different changes in the
            # same file. This is a scoped declaration for Review to verify, not
            # a claim that filenames can prove arbitrary business semantics.
            selected = (p["proposal_id"] in explicit or key in explicit) if explicit else (
                bool(set(ctx["ac_refs"]) & set(unit["ac_refs"])) if ctx["ac_refs"] and unit["ac_refs"] else
                any(_overlap(a, b) for a in ctx["paths"] for b in unit["paths"]))
            unknown = not explicit and not ctx["paths"] and not ctx["ac_refs"]
            if selected or (unknown and unknown_is_error and status["status"] not in ALLOWED):
                checks.append({"change": key, **status})
                if ctx["effect_scope"] not in READ_EFFECTS and status["status"] not in ALLOWED:
                    blocked.append(key + ":" + ("SCOPE_UNSPECIFIED" if unknown else status["status"]))
    if blocked:
        raise ValueError("SECURITY_APPROVAL_REQUIRED: " + "; ".join(blocked) + "; read-only investigation is still allowed")
    return {**ctx, "checks": checks, "schema": SCHEMA, "identity_limit": IDENTITY_LIMIT}


def check_effect(conn, task_id, context=None, *, task_dir=None):
    return check(read(conn, task_id, task_dir), context)


def work_context(conn, task_id, item_id):
    item = conn.execute("SELECT * FROM work_item WHERE task_id=? AND item_id=?", (task_id, item_id)).fetchone()
    if not item:
        raise ValueError("SECURITY_WORK_UNKNOWN: Work must belong to this Task")
    state = read(conn, task_id)
    bound = state["work"].get(item_id)
    ctx = normalize_context(bound["context"] if bound else {})
    ctx["paths"] = json.loads(item["allowed_paths_json"] or "[]")
    ctx["ac_refs"] = json.loads(item["acceptance_refs_json"] or "[]")
    return state, ctx


def check_work(conn, task_id, item_id):
    state, context = work_context(conn, task_id, item_id)
    return check(state, context)


def step_context(step):
    effect = "implementation" if step.get("phase") == "development" else "regression" if step.get("phase") == "verification" else "record_only"
    return normalize_context({"effect_scope": step.get("effect_scope", effect),
        **{key: step.get(key, []) for key in ("security_changes", "paths", "ac_refs")}})


def check_step(conn, task_id, step):
    state = read(conn, task_id)
    ctx = step_context(step)
    for wid in step.get("work_item_ids", []):
        _, work = work_context(conn, task_id, wid)
        check(state, work)
        if (ctx["effect_scope"] in READ_EFFECTS) != (work["effect_scope"] in READ_EFFECTS):
            raise ValueError("SECURITY_EFFECT_MISMATCH: step and Work effects must agree; split investigation from implementation")
        for key in ("paths", "ac_refs", "security_changes"):
            ctx[key] = sorted(set(ctx[key]) | set(work[key]))
    return check(state, ctx)


def context_from_args(args, *, effect="implementation"):
    return normalize_context({"effect_scope": getattr(args, "effect_scope", None) or effect,
        "security_changes": list(getattr(args, "security_change", None) or []),
        "paths": list(getattr(args, "scope_path", None) or []),
        "ac_refs": list(getattr(args, "scope_ac", None) or [])})


def add_context_args(parser, *, effect="implementation", investigation=False, scope_fields=True):
    parser.add_argument("--security-change", action="append", help="registered proposal ID or proposal#scope; repeatable, never an approval")
    if scope_fields:
        parser.add_argument("--scope-path", action="append", help="affected repo-relative path; narrows authority checks, not execution permission")
        parser.add_argument("--scope-ac", action="append", help="existing requirement/AC reference; not a new acceptance obligation")
    if investigation:
        parser.add_argument("--effect-scope", choices=sorted(EFFECTS - {"review_blocker"}), default=effect,
                            help="read_only/isolated_poc cannot be consumed as formal regression or implementation")


def changed_paths(snapshot):
    """Current HEAD-to-worktree paths only; not complete task-history coverage."""
    from .change_set import _run_git, _nul_paths, _is_product_path
    paths = set()
    for repo in (snapshot or {}).get("repositories", []):
        raw = _run_git(Path(repo["root_locator"]), "diff", "--no-ext-diff", "--no-textconv", "--name-only", "--no-renames", "-z", "HEAD", "--", ".", text=False)
        paths.update(p for p in _nul_paths(raw) if _is_product_path(p))
        paths.update(row["path"] for row in repo.get("untracked", []) if _is_product_path(row["path"]))
    return sorted(paths)


def classify_evidence(conn, task_id, task_dir, context, evidence, *, actor, transaction_id=None):
    ctx = normalize_context(context)
    if ctx["effect_scope"] not in {"read_only", "isolated_poc"} or not evidence:
        return None
    state = read(conn, task_id, task_dir)
    check(state, ctx)
    items = [evidence_item(task_dir, ref) for ref in evidence]
    payload = {"context": ctx, "evidence": items, "purpose": "investigation_only"}
    for prior in state["observations"]:
        if all(prior.get(k) == v for k, v in payload.items()):
            return prior["event_id"]
    return append(conn, task_id, OBSERVATION, payload, actor=actor,
                  summary="Security investigation evidence; not a regression requirement or authority", transaction_id=transaction_id)


def check_formal_evidence(state, task_dir, refs):
    items = [evidence_item(task_dir, ref) for ref in refs]
    for observation in state["observations"]:
        for old in observation["evidence"]:
            if any(item["path"] == old["path"] or item["sha256"] == old["sha256"] for item in items):
                raise ValueError("SECURITY_POC_NOT_FORMAL: investigation evidence cannot force a product rule; record a separately authorized actual regression result")
    return items


def validate_findings(conn, task_id, task_dir, ref, *, decision, count, snapshot=None):
    """Validate blocking Finding contracts; professional correctness is still reviewed.

    Findings outside authorized scope remain non-blocking proposals. Environment
    waits use BLOCKED + zero findings and the existing typed wait contract.
    """
    if ref is None:
        if decision in {"FAIL", "NEEDS_FIX", "REVISE"} or count:
            raise ValueError("REVIEW_FINDING_SCOPE_REQUIRED: provide --findings with requirement/AC, impact, relationship and evidence")
        return None
    raw, artifact = read_json_evidence(task_dir, ref)
    raw = obj(raw, {"schema", "findings"}, "findings")
    if raw.get("schema") != "tp-spec.scoped-findings/v1" or not isinstance(raw.get("findings"), list):
        raise ValueError("REVIEW_FINDING_INVALID")
    if len(raw["findings"]) != count:
        raise ValueError("REVIEW_FINDING_COUNT_MISMATCH")
    from .task_cmd import _acceptance_table_rows
    ac_path = Path(task_dir) / "acceptance.md"
    acs = _acceptance_table_rows(ac_path.read_text(encoding="utf-8-sig")) if ac_path.is_file() else {}
    state = read(conn, task_id, task_dir)
    result, seen = [], set()
    paths = None
    for value in raw["findings"]:
        f = obj(value, {"id", "blocking", "requirement_ref", "ac_ref", "relationship", "impact", "evidence", "paths", "security_changes", "summary"}, "finding")
        fid = identifier(f.get("id"), "finding.id")
        if fid in seen or type(f.get("blocking")) is not bool:
            raise ValueError("REVIEW_FINDING_INVALID: distinct IDs and boolean blocking required")
        seen.add(fid)
        ctx = normalize_context({"effect_scope": "review_blocker" if f["blocking"] else "record_only",
            "security_changes": f.get("security_changes", []), "paths": f.get("paths", []),
            "ac_refs": [f["ac_ref"]] if f.get("ac_ref") else []})
        row = {**f, "id": fid, "summary": text(f.get("summary"), "finding.summary"), "context": ctx}
        refs = strings(f.get("evidence"), "finding.evidence", required=True)
        row["evidence_items"] = [evidence_item(task_dir, e) for e in refs]
        if f["blocking"]:
            text(f.get("impact"), "finding.impact")
            if f.get("ac_ref"):
                if f["ac_ref"] not in acs:
                    raise ValueError("REVIEW_FINDING_AC_UNKNOWN: use an existing AC, not an invented obligation")
                # An existing AC is sufficient; do not invent a second mandatory
                # requirement record or ask for the same authorization again.
                req = acs[f["ac_ref"]]["cells"][3].strip()
                if f.get("requirement_ref") and f["requirement_ref"] != req:
                    raise ValueError("REVIEW_FINDING_REQUIREMENT_MISMATCH: must match the AC requirement source")
                row["requirement_ref"] = req
            else:
                # Tasks need not manufacture an AC just to cite an original
                # human requirement that is already registered in this ledger.
                req = text(f.get("requirement_ref"), "finding.requirement_ref")
                match = re.fullmatch(r"event:([1-9][0-9]*)", req)
                source = state["sources"].get(int(match[1])) if match else None
                if not source or source["body"]["kind"] != "HUMAN_REQUIREMENT" or not source_valid(state, source):
                    raise ValueError("REVIEW_FINDING_REQUIREMENT_UNKNOWN: cite an existing AC or registered original HUMAN_REQUIREMENT event")
                row["requirement_source_event_id"] = source["event_id"]
            if f.get("relationship") not in {"introduced_by_current_diff", "unmet_existing_requirement"}:
                raise ValueError("REVIEW_FINDING_RELATIONSHIP_REQUIRED")
            if f["relationship"] == "introduced_by_current_diff":
                if snapshot is None:
                    raise ValueError("REVIEW_FINDING_DIFF_REQUIRED: bind a real current product diff or use unmet_existing_requirement")
                if paths is None:
                    paths = changed_paths(snapshot)
                if not ctx["paths"] or not all(p in paths for p in ctx["paths"]):
                    raise ValueError("REVIEW_FINDING_DIFF_MISMATCH")
            check_formal_evidence(state, task_dir, refs)
        check(state, ctx)
        result.append(row)
    blockers = [f for f in result if f["blocking"]]
    if decision == "PASS" and blockers:
        raise ValueError("REVIEW_BLOCKING_FINDINGS_WITH_PASS")
    if decision in {"FAIL", "NEEDS_FIX", "REVISE"} and not blockers:
        raise ValueError("REVIEW_NO_AUTHORIZED_BLOCKER: optional hardening belongs in a proposal")
    return {"schema": "tp-spec.scoped-findings/v1", "artifact": artifact, "findings": result}


def explicit_context(args, *, effect="implementation"):
    if any(getattr(args, key, None) for key in ("security_change", "scope_path", "scope_ac", "effect_scope")):
        return context_from_args(args, effect=effect)
    return None


def check_dispatch(state, task, events, *, stage, effects):
    from .execution import project_execution
    facts = project_execution(task, events)
    step = next((s for s in facts["steps"] if s["phase"] == stage and s["status"] != "COMPLETED"), None)
    ctx = step_context(step) if step else normalize_context({
        "effect_scope": "implementation" if "repo_mutation" in effects else "regression" if stage == "verification" else "record_only"})
    if step:
        for wid in step.get("work_item_ids", []):
            work = state["work"].get(wid)
            if work:
                check(state, work["context"])
                if (ctx["effect_scope"] in READ_EFFECTS) != (work["context"]["effect_scope"] in READ_EFFECTS):
                    raise ValueError("SECURITY_EFFECT_MISMATCH: step cannot relabel Work effects")
                for key in ("paths", "ac_refs", "security_changes"):
                    ctx[key] = sorted(set(ctx[key]) | set(work["context"][key]))
    return check(state, ctx)


def formal_record_current(state, task_dir, detail):
    """Revalidate only new explicit bindings; do not retrofit historical duties."""
    try:
        if detail.get("security_context") is not None:
            ctx = normalize_context(detail["security_context"])
            if ctx["effect_scope"] in READ_EFFECTS:
                return False
            check(state, ctx)
        scoped = detail.get("scoped_findings")
        if scoped:
            evidence_item(task_dir, scoped["artifact"])
            for finding in scoped["findings"]:
                check(state, finding["context"])
                if finding.get("requirement_source_event_id"):
                    source = state["sources"].get(finding["requirement_source_event_id"])
                    if not source or not source_valid(state, source):
                        return False
                if finding["blocking"]:
                    check_formal_evidence(state, task_dir, finding["evidence_items"])
        # Already classified PoC stays an observation even when read via another
        # receipt/checkpoint or after copying the same bytes to a new path.
        if state["observations"]:
            check_formal_evidence(state, task_dir, detail.get("evidence_items") or detail.get("evidence") or [])
        return True
    except (ValueError, OSError, KeyError, TypeError):
        return False
