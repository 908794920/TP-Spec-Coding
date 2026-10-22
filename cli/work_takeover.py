# -*- coding: utf-8 -*-
"""记录用户指定的新责任并保留旧执行事实；进程状态由实际宿主管理。"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import uuid
import re

from . import command_context, db as dbmod, execution, orchestration_policy, recording

EVENT = "WORK_TAKEOVER_RECORDED"
SCHEMA = "tp-spec.work-takeover/v1"


def work_snapshot(conn, task_id):
    """旧 Work 的行更新未必有事件；接管另核当前责任行，避免接管已变化的执行者。"""
    return [dict(row) for row in conn.execute(
        "SELECT item_id,status,owner_role,owner_agent,updated_at FROM work_item "
        "WHERE task_id=? ORDER BY item_id", (task_id,),
    )]


def _identity(value):
    return (isinstance(value, dict) and set(value) == {"role", "agent"}
            and all(execution._nonempty(value.get(k)) for k in ("role", "agent")))


def session_identity(row):
    detail = execution.detail_of(row)
    return {"session_id": detail.get("session_id"), "start_event_id": row["id"],
            "role": row.get("actor_role"), "agent": row.get("actor_agent") or "",
            "work_item_id": row.get("work_item_id"), "plan_version": detail.get("plan_version"),
            "step_id": detail.get("step_id")}


def trusted(row, prior=None):
    """各投影和重试共用可信校验；用户来源提供本地审计依据。"""
    row = dict(row)
    detail = execution.detail_of(row)
    body = detail.get("takeover")
    saved = detail.get("logical_request")
    if (row.get("event_type") != EVENT or row.get("actor_role") != "human_owner"
            or not execution._trusted(row, detail, "work_takeover")
            or detail.get("schema_version") != row.get("workflow_version")
            or detail.get("takeover_schema") != SCHEMA or not isinstance(body, dict)
            or detail.get("takeover_digest") != execution.digest(body)
            or not orchestration_policy.valid_user_source(body.get("user_source"))
            or not execution._nonempty(detail.get("cli_invocation_id"))
            or type(body.get("expected_event_id")) is not int or body["expected_event_id"] < 0
            or not isinstance(body.get("selection"), dict)
            or body.get("effect_scope") != "record_only"
            or not isinstance(saved, dict) or saved.get("operation") != "work_takeover"
            or not execution._nonempty(saved.get("request_id"))
            or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", saved["request_id"])
            or saved.get("payload_sha256") != execution.digest({"actor": "human_owner",
                "selection": body["selection"], "user_source": body["user_source"]})):
        return None
    selection = body["selection"]
    if (not isinstance(body.get("work_snapshot"), list)
            or body.get("expected_work_snapshot_digest") != execution.digest(body["work_snapshot"])
            or selection.get("expected_work_snapshot_digest") != body["expected_work_snapshot_digest"]):
        return None
    coordinator = body.get("coordinator")
    works, sessions = body.get("work_items"), body.get("sessions")
    if (selection.get("expected_event_id") != body["expected_event_id"]
            or not isinstance(works, list) or not isinstance(sessions, list)
            or not (coordinator or works or sessions)
            or (coordinator is not None and (not isinstance(coordinator, dict)
                or not _identity(coordinator.get("after"))
                or coordinator["after"] != selection.get("coordinator")
                or (coordinator.get("before") is not None and not isinstance(coordinator["before"], dict))))
            or (coordinator is None and selection.get("coordinator") is not None)):
        return None
    if (any(not isinstance(w, dict) for w in works) or any(not isinstance(s, dict) for s in sessions)
            or len({w.get("id") for w in works if isinstance(w, dict)}) != len(works)
            or len({s.get("session_id") for s in sessions if isinstance(s, dict)}) != len(sessions)):
        return None
    for work in works:
        if (not isinstance(work, dict) or not execution._nonempty(work.get("id"))
                or not _identity(work.get("after")) or not isinstance(work.get("before"), dict)
                or work["before"].get("status") != "ACTIVE"
                or (work.get("attempt") is not None and (type(work["attempt"]) is not int or work["attempt"] < 1))):
            return None
    for session in sessions:
        if (set(session) != {"session_id", "start_event_id", "role", "agent", "work_item_id", "plan_version", "step_id"}
                or not execution._nonempty(session.get("session_id"))
                or type(session.get("start_event_id")) is not int
                or not isinstance(session.get("role"), str) or not isinstance(session.get("agent"), str)):
            return None
    if selection.get("work_items", []) != [{"id": w["id"], **w["after"]} for w in works]:
        return None
    if selection.get("sessions", []) != [s.get("session_id") for s in sessions]:
        return None
    response = saved.get("response")
    if response != receipt(row["task_id"], row["id"], saved["request_id"], body):
        return None
    if prior is not None:
        prior = [dict(r) for r in prior if dict(r).get("task_id") == row["task_id"]]
        if max((r["id"] for r in prior), default=0) != body["expected_event_id"]:
            return None
        by_id = {r["id"]: r for r in prior}
        for session in sessions:
            if not isinstance(session, dict) or type(session.get("start_event_id")) is not int:
                return None
            start = by_id.get(session["start_event_id"])
            if (not start or start.get("event_type") != "WORK_SESSION_STARTED"
                    or session_identity(start) != session or not execution._nonempty(session.get("session_id"))):
                return None
    return body


def receipt(task_id, event_id, request_id, body):
    return {"task_id": task_id, "event_id": event_id, "request_id": request_id,
            "expected_event_id": body["expected_event_id"], "coordinator": body["coordinator"],
            "work_items": body["work_items"], "sessions": body["sessions"],
            "user_source": body["user_source"], "replayed": False,
            "effect_scope": "record_only", "runtime_status": "UNKNOWN"}


def replay(conn, request):
    rows = execution.read_events(conn, request.task_id)
    found = None
    for index, row in enumerate(rows):
        saved = execution.detail_of(row).get("logical_request")
        if not isinstance(saved, dict) or saved.get("request_id") != request.request_id:
            continue
        if saved.get("operation") != request.operation or saved.get("payload_sha256") != request.payload_sha256:
            raise ValueError("REQUEST_ID_CONFLICT: use a new ID for a different instruction or selection")
        body = trusted(row, rows[:index])
        if body is None or found is not None:
            raise ValueError("REQUEST_RECORD_INVALID: untrusted or duplicate takeover receipt")
        # 同时核对历史状态链，避免只凭字段哈希一致就接受损坏回执。
        task = conn.execute("SELECT * FROM task WHERE task_id=?", (request.task_id,)).fetchone()
        facts = execution.project_execution(task, rows[:index + 1])
        from .work_units import project_units
        issues = facts["issues"] + project_units(rows[:index + 1])["issues"]
        if issues:
            raise ValueError("REQUEST_RECORD_INVALID: " + "; ".join(issues))
        found = {**saved["response"], "replayed": True, "receipt_event_id": row["id"],
                 "result_scope": "original logical request, not current task state or process termination"}
    return found


def normalize(raw):
    from .execution_cmd import _keys, _text, role_ids
    raw = _keys(raw, {"expected_event_id", "expected_work_snapshot_digest", "coordinator", "work_items", "sessions"}, "takeover")
    if type(raw.get("expected_event_id")) is not int or raw["expected_event_id"] < 0:
        raise ValueError("EXPECTED_EVENT_REQUIRED: use expected_event_id from work show")
    if not re.fullmatch(r"[0-9a-f]{64}", str(raw.get("expected_work_snapshot_digest") or "")):
        raise ValueError("EXPECTED_WORK_SNAPSHOT_REQUIRED: use expected_work_snapshot_digest from work show")
    roles = role_ids()
    def owner(value):
        value = _keys(value, {"role", "agent"}, "takeover identity")
        value = {key: _text(value.get(key), "takeover." + key) for key in ("role", "agent")}
        if value["role"] not in roles or value["role"] == "human_owner":
            raise ValueError("TAKEOVER_ROLE_INVALID: select the actual registered AI role")
        return value
    result = {"expected_event_id": raw["expected_event_id"],
              "expected_work_snapshot_digest": raw["expected_work_snapshot_digest"]}
    if "coordinator" in raw:
        result["coordinator"] = owner(raw["coordinator"])
    works = raw.get("work_items", [])
    if not isinstance(works, list):
        raise ValueError("work_items must be a list")
    result["work_items"] = []
    for work in works:
        work = _keys(work, {"id", "role", "agent"}, "work takeover")
        result["work_items"].append({"id": _text(work.get("id"), "work.id"),
                                    **owner({k: work.get(k) for k in ("role", "agent")})})
    result["sessions"] = raw.get("sessions", [])
    if (not execution._string_list(result["sessions"])
            or len({w["id"] for w in result["work_items"]}) != len(result["work_items"])):
        raise ValueError("TAKEOVER_SELECTION_INVALID: use distinct exact Work/session identities")
    if not (result.get("coordinator") or result["work_items"] or result["sessions"]):
        raise ValueError("TAKEOVER_SELECTION_REQUIRED")
    return result


def record(conn, task, facts, selection, source, request):
    from .execution_cmd import append_event
    from . import work_units, security_authority as authority
    from .work_session_cmd import _open_sessions
    rows = execution.read_events(conn, task["task_id"])
    if max((r["id"] for r in rows), default=0) != selection["expected_event_id"]:
        raise ValueError("TAKEOVER_SNAPSHOT_CHANGED: reread work show before reassignment")
    snapshot = work_snapshot(conn, task["task_id"])
    if execution.digest(snapshot) != selection["expected_work_snapshot_digest"]:
        raise ValueError("TAKEOVER_SNAPSHOT_CHANGED: Work responsibility changed; reread work show")
    works = []
    units = work_units.read(conn, task["task_id"])["units"]
    for selected in selection["work_items"]:
        item = work_units.checked_item(conn, task["task_id"], selected["id"])
        unit = units.get(selected["id"])
        if item["status"] != "ACTIVE":
            raise ValueError("TAKEOVER_WORK_NOT_ACTIVE: " + selected["id"])
        work_units.claim_guard(conn, task, item, unit, selected["role"], selected["agent"], record_only=True)
        if unit:
            if selected["role"] not in unit["spec"]["roles"]:
                raise ValueError("WORK_ROLE_MISMATCH")
            step = next((s for s in facts["steps"] if s["id"] == unit["waiting_step_id"]), None)
            if not step or step["status"] not in {"ACTIVE", "WAITING"}:
                raise ValueError("WORK_PARENT_NOT_CURRENT")
            if (item["owner_role"], item["owner_agent"]) != (unit.get("owner_role"), unit.get("owner_agent")):
                raise ValueError("WORK_ROW_FACT_MISMATCH")
        works.append({"id": selected["id"], "before": {"role": item["owner_role"],
            "agent": item["owner_agent"], "status": item["status"]},
            "after": {k: selected[k] for k in ("role", "agent")}, "attempt": unit["attempt"] if unit else None})
    opened = _open_sessions(conn, task["task_id"])
    sessions = []
    for sid in selection["sessions"]:
        matched = [r for r in opened if execution.detail_of(r).get("session_id") == sid]
        if len(matched) != 1:
            raise ValueError("TAKEOVER_SESSION_NOT_OPEN: " + sid)
        sessions.append(session_identity(matched[0]))
    body = {"expected_event_id": selection["expected_event_id"], "selection": selection,
            "expected_work_snapshot_digest": selection["expected_work_snapshot_digest"], "work_snapshot": snapshot,
            "user_source": source, "effect_scope": "record_only", "work_items": works, "sessions": sessions,
            "coordinator": {"before": facts["coordinator"], "after": selection["coordinator"]}
                           if selection.get("coordinator") else None}
    eid = append_event(conn, task, EVENT, actor="human_owner", summary=source["statement"],
        producer="work_takeover", payload={"takeover_schema": SCHEMA, "takeover": body,
            "takeover_digest": execution.digest(body), "cli_invocation_id": command_context.invocation_id() or uuid.uuid4().hex,
            "logical_request": request.detail({})})
    response = receipt(task["task_id"], eid, request.request_id, body)
    detail = execution.detail_of(conn.execute("SELECT * FROM task_event WHERE id=?", (eid,)).fetchone())
    detail["logical_request"] = request.detail(response)
    conn.execute("UPDATE task_event SET detail_json=? WHERE id=?", (json.dumps(detail, ensure_ascii=False), eid))
    if body["coordinator"]:
        owner = body["coordinator"]["after"]
        conn.execute("UPDATE task SET owner_role=?,owner_agent=? WHERE task_id=?", (owner["role"], owner["agent"], task["task_id"]))
    for work in works:
        conn.execute("UPDATE work_item SET owner_role=?,owner_agent=?,updated_at=? WHERE task_id=? AND item_id=?",
            (work["after"]["role"], work["after"]["agent"], dbmod.now_iso(), task["task_id"], work["id"]))
    # 同一事务内验证最终事件可以合法重放，再提交责任变更。
    updated = execution.read_events(conn, task["task_id"])
    if trusted(updated[-1], updated[:-1]) is None:
        raise ValueError("TAKEOVER_RECORD_INVALID")
    check = execution.project_execution(task, updated)
    issues = check["issues"] + work_units.project_units(updated)["issues"]
    if issues:
        raise ValueError("TAKEOVER_RECORD_INVALID: " + "; ".join(issues))
    return response


def cmd_work_takeover(args):
    conn = None
    try:
        if args.actor != "human_owner":
            raise ValueError("TAKEOVER_USER_REQUIRED: record the actual user instruction as human_owner")
        selection = normalize(json.loads(Path(args.file).read_text(encoding="utf-8-sig")))
        source = orchestration_policy.user_source(args.source, args.source_ref)
        path = dbmod.resolve_db_path(args.db, task_id=args.task)
        if not Path(path).is_file():
            raise ValueError("Runtime database not found")
        request = recording.LogicalRequest(args.task, Path(args.file).parent, "work_takeover",
            {"actor": args.actor, "selection": selection, "user_source": source}, args.request_id)
        conn = dbmod.connect(path)
        with command_context.span("lock_wait"):
            conn.execute("BEGIN IMMEDIATE")
        try:
            with command_context.span("lock_held"):
                result = replay(conn, request)
                if result is None:
                    from .execution_cmd import load_current
                    task, facts = load_current(conn, args.task, allow_legacy=True)
                    result = record(conn, task, facts, selection, source, request)
                conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if conn is not None:
            conn.close()


def add_subparser(sub):
    parser = sub.add_parser("takeover", help="Record explicit user reassignment; never stops or launches agents")
    for key in ("task", "file", "source", "source-ref", "request-id"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--actor", required=True, choices=["human_owner"])
    parser.add_argument("--db", default=None)
    parser.set_defaults(func=cmd_work_takeover)
