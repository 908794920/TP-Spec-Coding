# -*- coding: utf-8 -*-
"""Explicit execution-plan and step recording under the existing `work` group."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
import sys
import uuid

from . import db as dbmod, event_contract, execution
from .version import active_version


def _text(value, name: str, *, required=True) -> str:
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{name} must be {'a non-empty' if required else 'a'} string")
    return value.strip()


def _strings(value, name: str, *, required=False) -> list[str]:
    if not isinstance(value, list) or (required and not value):
        raise ValueError(f"{name} must be {'a non-empty' if required else 'a'} list")
    result = [_text(item, name) for item in value]
    if len(set(result)) != len(result):
        raise ValueError(f"{name} contains duplicate values")
    return result


def _keys(value, allowed: set[str], name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"unknown {name} fields: {', '.join(sorted(unknown))}")
    return value


def effective_level(conn, task) -> str:
    from . import orchestration, risk_signals
    level = orchestration.resolve_effective_level(task["risk_level"], task["flow_level"])
    project = conn.execute("SELECT root_path FROM project WHERE project_id=?", (task["project_id"],)).fetchone()
    if project and project["root_path"]:
        scan = risk_signals.scan_task_artifacts(Path(project["root_path"]) / ".tp-spec" / "tasks" / task["task_id"])
        floor = scan.get("floor")
        if floor:
            level = orchestration.resolve_effective_level(level, floor)
    return level


def role_ids() -> set[str]:
    from .orchestration import load_role_catalog
    return {str(item["workflow_role"]) for item in load_role_catalog()["roles"]} | {"tp-spec-coding", "tp-software-lifecycle", "human_owner"}


def validate_refs(conn, task_id: str, values) -> list[str]:
    refs = _strings(values, "evidence/source refs")
    for ref in refs:
        if ref.startswith("event:"):
            if not re.fullmatch(r"event:[1-9][0-9]*", ref) or not conn.execute(
                    "SELECT 1 FROM task_event WHERE task_id=? AND id=?", (task_id, int(ref[6:]))).fetchone():
                raise ValueError(f"REFERENCE_NOT_IN_TASK: {ref}")
    # Non-event references are locators, not a claim of evidence validation or approval.
    return refs


def validate_items(conn, task_id: str, values) -> list[str]:
    items = _strings(values, "work_item_ids")
    for item in items:
        if not conn.execute("SELECT 1 FROM work_item WHERE task_id=? AND item_id=?", (task_id, item)).fetchone():
            raise ValueError(f"WORK_ITEM_NOT_IN_TASK: {item}")
    return items


def normalize_plan(conn, task, raw) -> tuple[dict, int]:
    raw = _keys(raw, {"expected_version", "coordinator", "assessment", "reason", "scope_refs", "steps"}, "plan")
    expected = raw.get("expected_version")
    if type(expected) is not int or expected < 0:
        raise ValueError("expected_version must be a non-negative integer (0 for first adoption)")
    roles = role_ids()
    owner = _keys(raw.get("coordinator"), {"role", "agent"}, "coordinator")
    owner = {"role": _text(owner.get("role"), "coordinator.role"),
             "agent": _text(owner.get("agent", ""), "coordinator.agent", required=False)}
    if owner["role"] not in roles:
        raise ValueError("unknown coordinator.role")
    assessment = _keys(raw.get("assessment"), {"summary", "source_refs", "omissions"}, "assessment")
    omissions = _keys(assessment.get("omissions", {}), {"verification", "review"}, "assessment.omissions")
    omissions = {key: _text(value, f"omissions.{key}") for key, value in omissions.items()}
    assessment = {"summary": _text(assessment.get("summary"), "assessment.summary"),
                  "source_refs": validate_refs(conn, task["task_id"], assessment.get("source_refs")), "omissions": omissions}
    if not assessment["source_refs"]:
        raise ValueError("assessment.source_refs must identify the actual assessment basis")
    from .record_first import PHASES
    phases = set(PHASES) | {"architecture_review"}
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a non-empty list")
    normalized, seen = [], set()
    for source in steps:
        step = _keys(source, {"id", "title", "phase", "roles", "depends_on", "scope", "work_item_ids", "effect_scope", "security_changes", "paths", "ac_refs"}, "step")
        sid = _text(step.get("id"), "step.id")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", sid) or sid in seen:
            raise ValueError(f"invalid/duplicate step.id: {sid}")
        phase = _text(step.get("phase"), "step.phase")
        if phase not in phases:
            raise ValueError(f"unknown phase: {phase}")
        expected_roles = _strings(step.get("roles"), "step.roles", required=True)
        if set(expected_roles) - roles:
            raise ValueError("step.roles contains unknown roles")
        dependencies = _strings(step.get("depends_on", []), "step.depends_on")
        if set(dependencies) - seen:
            raise ValueError(f"STEP_DEPENDENCY_ORDER: {sid}; dependencies must be earlier explicit step IDs")
        normalized.append({"id": sid, "title": _text(step.get("title"), "step.title"), "phase": phase,
            "roles": expected_roles, "depends_on": dependencies, "scope": _text(step.get("scope"), "step.scope"),
            "work_item_ids": validate_items(conn, task["task_id"], step.get("work_item_ids", []))})
        from . import security_authority as authority
        security_keys = {"effect_scope", "security_changes", "paths", "ac_refs"} & set(step)
        if security_keys:
            ctx = authority.step_context(step)
            normalized[-1].update({key: ctx[key] for key in security_keys})
        seen.add(sid)
    level = effective_level(conn, task)
    present = {step["phase"] for step in normalized}
    required = {"development", "delivery"}
    if level != "L0":
        required.add("verification")
    if level in {"L2", "L3"}:
        required.add("review")
    if required - present:
        raise ValueError(f"PLAN_OBLIGATIONS_MISSING: {', '.join(sorted(required - present))}")
    for phase in {"verification", "review"} - present:
        if phase not in omissions:
            raise ValueError(f"assessment.omissions.{phase} must explain why no separate step applies")
    if set(omissions) & present:
        raise ValueError("an included phase cannot also be declared omitted")
    # Specialized outcomes remain with their registered roles, even with other participants.
    for phase, owner_role in {"verification": "tp-test-engineer", "review": "tp-code-reviewer", "delivery": "tp-integration-engineer"}.items():
        if any(step["phase"] == phase and owner_role not in step["roles"] for step in normalized):
            raise ValueError(f"{phase} requires its accountable role {owner_role}")
    result = {"coordinator": owner, "assessment": assessment, "effective_level": level,
              "reason": _text(raw.get("reason"), "reason"),
              "scope_refs": validate_refs(conn, task["task_id"], raw.get("scope_refs")),
              "effect_scope": "record_only", "steps": normalized}
    if not result["scope_refs"]:
        raise ValueError("scope_refs must identify the existing authorized Task scope; a plan is not approval")
    return result, expected


def append_event(conn, task, event_type: str, *, actor: str, agent: str = "", summary: str,
                 payload: dict, item=None, producer="execution", operation="RECORD", result_status="RECORDED",
                 now=None, transaction_id=None) -> int:
    now = now or dbmod.now_iso()
    data = {**payload, "execution_schema": execution.SCHEMA, "producer": producer,
            "schema_version": active_version(), "transaction_id": transaction_id or uuid.uuid4().hex,
            "task_id": task["task_id"], "actor_role": actor, "created_at": now}
    data = event_contract.add_event_semantics(data, event_type=event_type, operation=operation,
                                              result_status=result_status, producer=producer)
    cur = conn.execute("INSERT INTO task_event (task_id,event_type,actor_role,actor_agent,work_item_id,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                       (task["task_id"], event_type, actor, agent, item, summary,
                        json.dumps(data, ensure_ascii=False), active_version(), now))
    conn.execute("UPDATE task SET updated_at=? WHERE task_id=?", (now, task["task_id"]))
    return int(cur.lastrowid)


def load_current(conn, task_id: str, *, allow_legacy=False, allow_legacy_end=False):
    from .event_policies import is_task_retired
    task = conn.execute("SELECT * FROM task WHERE task_id=?", (task_id,)).fetchone()
    if task is None:
        raise ValueError(f"task not found: {task_id}")
    retired = is_task_retired(conn, task_id)
    if (task["current_state"] in execution.TERMINAL or retired) and not allow_legacy_end:
        raise ValueError("TASK_NOT_CURRENT: terminal/retired task is read-only")
    if not allow_legacy and task["base_version"] != active_version():
        raise ValueError("TASK_CONTRACT_MISMATCH: use the existing supported migration before adoption")
    facts = execution.read_execution(conn, task, retired=retired)
    if facts["issues"]:
        raise ValueError("EXECUTION_FACTS_INVALID: " + "; ".join(facts["issues"]))
    from .work_units import read as read_units
    work_issues = read_units(conn, task_id)["issues"]
    if work_issues:
        raise ValueError("WORK_FACTS_INVALID: " + "; ".join(work_issues))
    return task, facts


def record_step(conn, task, facts: dict, *, step_id: str, plan_version: int, action: str, actor: str,
                summary: str, wait_reason="", expected_next="", waiting_items=None, evidence=None,
                now=None, transaction_id=None) -> dict:
    if facts["plan"] is None or plan_version != facts["plan_version"]:
        raise ValueError("PLAN_VERSION_CHANGED: reread work show and use the current plan version")
    step = next((item for item in facts["steps"] if item["id"] == step_id), None)
    if step is None:
        raise ValueError(f"STEP_NOT_IN_PLAN: {step_id}")
    if actor not in set(step["roles"]) | {facts["coordinator"]["role"]}:
        raise ValueError("STEP_ROLE_MISMATCH: actor must be an expected participant or coordinator")
    summary = _text(summary, "step summary")
    allowed = {"PLANNED": {"start"}, "ACTIVE": {"wait", "complete"}, "WAITING": {"resume"}}
    if action not in allowed.get(step["status"], set()):
        raise ValueError(f"STEP_TRANSITION_INVALID: {step['status']} -> {action}")
    if action in {"start", "resume", "complete"}:
        from .security_authority import check_step
        check_step(conn, task["task_id"], step)
    if action == "start":
        first = next((item for item in facts["steps"] if item["status"] != "COMPLETED"), None)
        if not first or first["id"] != step_id:
            raise ValueError("STEP_ORDER: finish the current step before advancing")
        if task["current_state"] == "BLOCKED":
            raise ValueError("TASK_BLOCKED: resolve the existing Task wait before starting another step")
    from .work_units import step_guard
    step_guard(conn, task, facts, step, action)
    if action == "complete":
        for wid in step.get("work_item_ids", []):
            row = conn.execute("SELECT status FROM work_item WHERE task_id=? AND item_id=?", (task["task_id"], wid)).fetchone()
            if row is None or row["status"] != "COMPLETED":
                raise ValueError("WORK_PENDING: " + wid)
    if action == "complete" and any(p["step_id"] == step_id and p["ended_at"] is None for p in facts["participations"]):
        raise ValueError("STEP_HAS_OPEN_PARTICIPATIONS: end or hand off the recorded sessions first")
    if action == "resume" and task["current_state"] == "BLOCKED":
        raise ValueError("TASK_BLOCKED: step resume cannot resolve an existing Task blocker")
    wait_reason = _text(wait_reason, "wait_reason", required=action == "wait")
    expected_next = _text(expected_next, "expected_next_actor", required=action == "wait")
    if action != "wait" and (wait_reason or expected_next or waiting_items):
        raise ValueError("wait fields are only valid for action=wait")
    refs = validate_refs(conn, task["task_id"], evidence or [])
    items = validate_items(conn, task["task_id"], waiting_items or [])
    payload = {"plan_version": plan_version, "step_id": step_id, "action": action,
               "wait_reason": wait_reason, "expected_next_actor": expected_next,
               "waiting_work_items": items, "evidence_refs": refs, "effect_scope": "record_only"}
    event_id = append_event(conn, task, execution.STEP, actor=actor, summary=summary, payload=payload,
                           now=now, transaction_id=transaction_id,
                           result_status={"start": "STARTED", "wait": "PENDING", "resume": "STARTED", "complete": "COMPLETED"}[action])
    conn.execute("UPDATE task SET current_stage=? WHERE task_id=?", (step["phase"], task["task_id"]))
    return {"event_id": event_id, **payload, "status": execution.STEP_ACTIONS[action]}


def _write_command(args, operation, *, allow_legacy=False, allow_legacy_end=False) -> int:
    conn = None
    try:
        path = dbmod.resolve_db_path(args.db, task_id=args.task)
        if not Path(path).is_file():
            raise ValueError("Runtime database not found; initialize the project first")
        conn = dbmod.connect(path)
        with dbmod.transactional(conn):
            task, facts = load_current(conn, args.task, allow_legacy=allow_legacy, allow_legacy_end=allow_legacy_end)
            result = operation(conn, task, facts)
        print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if conn is not None:
            conn.close()


def cmd_work_plan(args) -> int:
    try:
        raw = json.loads(Path(args.file).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        print(f"ERROR: plan file: {exc}", file=sys.stderr)
        return 2
    def write(conn, task, facts):
        body, expected = normalize_plan(conn, task, raw)
        fingerprint = execution.digest(body)
        if facts["plan"] == body:
            return {"task_id": args.task, "plan_version": facts["plan_version"], "replayed": True,
                    "event_id": facts["plan_history"][-1]["event_id"]}
        if expected != facts["plan_version"]:
            raise ValueError("PLAN_VERSION_CHANGED: reread before revising the plan")
        if facts["plan"]:
            begun = [item for item in facts["steps"] if item["status"] != "PLANNED"]
            for item in begun:
                old = next(step for step in facts["plan"]["steps"] if step["id"] == item["id"])
                index = facts["plan"]["steps"].index(old)
                if index >= len(body["steps"]) or body["steps"][index] != old:
                    raise ValueError("STARTED_HISTORY_IMMUTABLE: add future work instead of rewriting begun steps")
        from .security_authority import check_step
        begun_ids = {s["id"] for s in facts["steps"] if s["status"] != "PLANNED"}
        for step in body["steps"]:
            if step["id"] not in begun_ids:
                check_step(conn, task["task_id"], step)
        version = expected + 1
        event_id = append_event(conn, task, execution.PLAN, actor=body["coordinator"]["role"],
                                agent=body["coordinator"]["agent"], summary=body["reason"],
                                payload={"plan_version": version, "plan_digest": fingerprint, "plan": body})
        conn.execute("UPDATE task SET owner_role=?,owner_agent=? WHERE task_id=?",
                     (body["coordinator"]["role"], body["coordinator"]["agent"], args.task))
        return {"task_id": args.task, "plan_version": version, "event_id": event_id,
                "effective_level": body["effective_level"], "replayed": False}
    return _write_command(args, write)


def cmd_work_step(args) -> int:
    return _write_command(args, lambda conn, task, facts: record_step(
        conn, task, facts, step_id=args.step, plan_version=args.plan_version, action=args.action,
        actor=args.role or (facts.get("coordinator") or {}).get("role", ""), summary=args.summary,
        wait_reason=args.wait_reason, expected_next=args.expected_next, waiting_items=args.waiting_item,
        evidence=args.evidence))


def cmd_work_show(args) -> int:
    conn = None
    try:
        conn = dbmod.connect_readonly(dbmod.resolve_db_path(args.db, task_id=args.task))
        conn.execute("BEGIN")
        task = conn.execute("SELECT * FROM task WHERE task_id=?", (args.task,)).fetchone()
        if task is None:
            raise ValueError(f"task not found: {args.task}")
        from .event_policies import is_task_retired
        facts = execution.read_execution(conn, task, retired=is_task_retired(conn, args.task))
        print(json.dumps({"task_id": args.task, "task_state": task["current_state"], **facts}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if conn is not None:
            conn.close()


def add_execution_subparsers(sub) -> None:
    plan = sub.add_parser("plan", help="Record/revise a concrete Task execution plan (not execution approval)")
    plan.add_argument("--file", required=True, help="JSON plan; expected_version=0 for first adoption")
    step = sub.add_parser("step", help="Record a real execution-step boundary; never grants a quality PASS")
    step.add_argument("--step", required=True)
    step.add_argument("--plan-version", required=True, type=int)
    step.add_argument("--action", required=True, choices=list(execution.STEP_ACTIONS))
    step.add_argument("--role", default=None)
    step.add_argument("--summary", required=True)
    step.add_argument("--wait-reason", default="")
    step.add_argument("--expected-next", default="")
    step.add_argument("--waiting-item", action="append", default=[])
    step.add_argument("--evidence", action="append", default=[])
    show = sub.add_parser("show", help="Read persisted plan, current step and role participation history (JSON)")
    for parser, command in ((plan, cmd_work_plan), (step, cmd_work_step), (show, cmd_work_show)):
        parser.add_argument("--task", required=True)
        parser.add_argument("--db", default=None)
        parser.set_defaults(func=command)
