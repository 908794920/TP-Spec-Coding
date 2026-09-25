# -*- coding: utf-8 -*-
"""Small source/proposal intake; decisions reuse task scope-change.

No approval server, UI write endpoint, tool-permission grant or new Task state.
"""
from __future__ import annotations

import json
from pathlib import Path
import uuid

from . import db as dbmod, record_first, security_authority as authority, transaction_commit


def _write(args, prepare, event_type, actor):
    task_dir = record_first._task_dir(args.task_dir)
    conn = dbmod.connect(dbmod.resolve_db_path(args.db, task_id=args.task))
    try:
        task = record_first._load(conn, args.task)
        transaction_commit._assert_task_workspace_identity(conn, task_dir, args.task)
        if task["current_state"] in record_first.TERMINAL_STATES:
            raise ValueError("SECURITY_TASK_TERMINAL: historical sources and decisions are read-only")
        from .event_policies import is_task_retired
        if is_task_retired(conn, args.task):
            raise ValueError("SECURITY_TASK_RETIRED")
        payload, replay = prepare(conn, task_dir)
        if replay:
            result = {"task_id": args.task, "event_id": replay, "replayed": True}
        else:
            result = {"task_id": args.task, "replayed": False}
            def writer(dbconn, transaction_id=""):
                checked, repeated = prepare(dbconn, task_dir)
                if checked != payload or repeated:
                    raise ValueError("SECURITY_FACTS_CHANGED: reread before retrying")
                result["event_id"] = authority.append(dbconn, args.task, event_type, payload,
                    actor=actor, summary=args.summary, transaction_id=transaction_id)
            result.update(record_first._write_with_projection(conn, task_dir, task,
                operation="security_authority", target_state=task["current_state"], owner_after=task["owner_role"] or "",
                flush_id="SECURITY-" + uuid.uuid4().hex, writer=writer, summary=args.summary))
            result.update({k: payload[k] for k in ("proposal_id", "version", "proposal_digest") if k in payload})
        result["identity_limit"] = authority.IDENTITY_LIMIT
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        conn.close()


def cmd_source(args):
    return _write(args, lambda conn, tdir: authority.prepare_source(conn, args.task, tdir, args.file,
        attested=args.attest_human_source), authority.SOURCE, args.actor)


def cmd_propose(args):
    raw = json.loads(Path(args.file).read_text(encoding="utf-8-sig"))
    return _write(args, lambda conn, tdir: authority.prepare_proposal(conn, args.task, tdir, raw), authority.PROPOSAL, args.actor)


def record_decision(args):
    if args.repo_root:
        raise ValueError("SECURITY_SCOPE_SEPARATE: a security decision cannot silently replace repository scope")
    if args.scope_id != args.security_proposal:
        raise ValueError("SECURITY_PROPOSAL_MISMATCH: --scope-id must be the proposal ID")
    return _write(args, lambda conn, tdir: authority.prepare_decision(conn, args.task, tdir,
        proposal_id=args.security_proposal, version=args.proposal_version, proposal_digest=args.proposal_digest,
        decision=args.security_decision, scope_ids=args.approved_scope, human_event_id=args.human_event_id),
        authority.DECISION, "human_owner")


def cmd_show(args):
    conn = dbmod.connect_readonly(dbmod.resolve_db_path(args.db, task_id=args.task))
    try:
        conn.execute("BEGIN")
        print(json.dumps(authority.summary(authority.read(conn, args.task)), ensure_ascii=False, indent=2))
        return 0
    finally:
        conn.close()


def cmd_observe(args):
    def prepare(conn, tdir):
        ctx = authority.context_from_args(args, effect="isolated_poc")
        if ctx["effect_scope"] not in {"read_only", "isolated_poc"}:
            raise ValueError("SECURITY_OBSERVATION_ONLY: choose read_only or isolated_poc")
        state = authority.read(conn, args.task, tdir)
        authority.check(state, ctx)
        payload = {"context": ctx, "evidence": [authority.evidence_item(tdir, ref) for ref in args.evidence], "purpose": "investigation_only"}
        for prior in state["observations"]:
            if all(prior.get(k) == v for k, v in payload.items()):
                return None, prior["event_id"]
        return payload, None
    return _write(args, prepare, authority.OBSERVATION, args.actor)


def add_security_subparsers(sub):
    root = sub.add_parser("security", help="Scoped security proposals, original human sources and read-only decisions")
    actions = root.add_subparsers(dest="security_action", required=True)
    source = actions.add_parser("source", help="Register an original human statement; attribution is local, not host authentication")
    source.add_argument("--file", required=True, help="evidence/*.json, task-relative; tp-spec.human-authority/v1")
    source.add_argument("--attest-human-source", action="store_true", help="confirm you inspected the original human message; never use agent/tool/generated text")
    propose = actions.add_parser("propose", help="Record or revise a proposal without changing behavior or creating an obligation")
    propose.add_argument("--file", required=True, help="proposal JSON; optimistic expected_version (0 for first proposal)")
    observe = actions.add_parser("observe", help="Classify investigative/PoC evidence; cannot become a formal regression by copying it")
    observe.add_argument("--evidence", action="append", required=True)
    authority.add_context_args(observe, effect="isolated_poc", investigation=True)
    show = actions.add_parser("show", help="Read proposal versions, scoped decisions and pending/invalid authority (JSON)")
    for parser, func in ((source, cmd_source), (propose, cmd_propose), (observe, cmd_observe), (show, cmd_show)):
        parser.add_argument("--task", required=True)
        parser.add_argument("--db", default=None)
        if parser is not show:
            parser.add_argument("--task-dir", required=True)
            parser.add_argument("--actor", default="tp-spec-coding", choices=record_first.ACTORS)
            parser.add_argument("--summary", required=True)
        parser.set_defaults(func=func)
