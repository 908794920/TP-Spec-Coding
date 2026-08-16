# -*- coding: utf-8 -*-
"""CLI surface for Autonomous Maintenance."""
from __future__ import annotations

import json
import sys
from typing import Any

from . import autonomy_profile
from . import autonomy_workspace
from . import autonomy_cycle
from . import autonomy_records
from . import orchestration
from . import autonomy_discovery
from . import autonomy_digest
from . import autonomy_batch
from . import autonomy_review
from . import autonomy_integration
from . import autonomy_effects


def _emit(data: Any, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif isinstance(data, str):
        print(data)
    elif isinstance(data, dict):
        for key, value in data.items():
            print(f"{key}: {value}")
    else:
        print(data)


def _fail(exc: Exception) -> int:
    print(str(exc), file=sys.stderr)
    return 4


def cmd_profile_create(args) -> int:
    try:
        profile = autonomy_profile.build_profile(
            profile_id=args.id,
            canonical_root=args.canonical_root,
            canonical_project_id=args.canonical_project,
            autonomy_root=args.autonomy_root,
            mutable_repos=args.mutable_repo,
            support_repos=args.support_repo or [],
            goals=args.goal,
            difficulty_ceiling=args.difficulty_ceiling,
            max_new_tasks=args.max_new_tasks,
            confirmation_policy=args.confirmation_policy,
        )
        autonomy_profile.save_profile(profile)
        data = {
            "schema": profile["schema"],
            "profile_id": profile["profile_id"],
            "runtime_project_id": profile["autonomous"]["runtime_project_id"],
            "autonomy_root": profile["autonomous"]["workspace_root"],
            "enabled": True,
        }
        _emit(data, args.json)
        return 0
    except Exception as exc:
        return _fail(exc)



def cmd_profile_edit(args) -> int:
    try:
        data=autonomy_profile.edit_profile(args.id,goals=args.goal,difficulty_ceiling=args.difficulty_ceiling,max_new_tasks=args.max_new_tasks,confirmation_policy=args.confirmation_policy)
        _emit(data,args.json); return 0
    except Exception as exc: return _fail(exc)

def cmd_profile_refresh_prompt(args) -> int:
    try:
        _emit(autonomy_profile.refresh_prompt(args.id),args.json); return 0
    except Exception as exc: return _fail(exc)

def cmd_profile_show(args) -> int:
    try:
        _emit(autonomy_profile.load_profile(args.id), args.json)
        return 0
    except Exception as exc:
        return _fail(exc)


def cmd_profile_list(args) -> int:
    try:
        data = autonomy_profile.list_profiles()
        _emit(data, args.json)
        return 0
    except Exception as exc:
        return _fail(exc)


def cmd_profile_prompt(args) -> int:
    try:
        profile = autonomy_profile.load_profile(args.id)
        prompt = str((profile.get("automation") or {}).get("prompt") or "")
        print(prompt)
        return 0
    except Exception as exc:
        return _fail(exc)


def cmd_profile_enabled(args, enabled: bool) -> int:
    try:
        profile = autonomy_profile.set_enabled(args.id, enabled)
        _emit({"profile_id": args.id, "enabled": profile["enabled"]}, args.json)
        return 0
    except Exception as exc:
        return _fail(exc)


def cmd_doctor(args) -> int:
    data = autonomy_profile.doctor(args.profile)
    if data.get("status") == "PASS":
        try:
            profile = autonomy_profile.load_profile(args.profile)
            from pathlib import Path as _Path
            root = _Path(str((profile.get("autonomous") or {}).get("workspace_root") or ""))
            if root.is_dir():
                ws = autonomy_workspace.workspace_status(args.profile, refresh_canonical=True)
                workspace_warnings = [str(x) for x in (ws.get("warnings") or [])]
                hard_workspace_issues = [x for x in workspace_warnings if x == "SUPPORT_REPO_MUTATED" or x.startswith("REPO_MISSING:")]
                if hard_workspace_issues:
                    data.setdefault("errors", []).extend(hard_workspace_issues)
                    data["status"] = "FAIL"
                data["workspace"] = {**ws, "status": "FAIL" if hard_workspace_issues else "PASS"}
                data["cycle"] = autonomy_cycle.cycle_status(args.profile)
            else:
                data["workspace"] = {"status": "NOT_INITIALIZED", "workspace_root": str(root)}
                data["cycle"] = {"schema": autonomy_cycle.CYCLE_SCHEMA, "profile_id": args.profile, "state": "IDLE", "generation": 0}
            data["integration"] = autonomy_integration.capability()
        except Exception as exc:
            data.setdefault("errors", []).append(str(exc))
            data["status"] = "FAIL"
    _emit(data, args.json)
    return 0 if data["status"] == "PASS" else 1



def cmd_workspace_init(args) -> int:
    try:
        _emit(autonomy_workspace.initialize_workspace(args.profile), args.json)
        return 0
    except Exception as exc:
        return _fail(exc)


def cmd_workspace_status(args) -> int:
    try:
        _emit(autonomy_workspace.workspace_status(args.profile, refresh_canonical=not args.no_refresh), args.json)
        return 0
    except Exception as exc:
        return _fail(exc)



def cmd_cycle_begin(args) -> int:
    try:
        _emit(autonomy_cycle.begin_cycle(args.profile, executor_kind=args.executor_kind), args.json)
        return 0
    except Exception as exc:
        return _fail(exc)



def cmd_cycle_claim_rework(args) -> int:
    try:
        _emit(autonomy_cycle.claim_rework(args.profile,args.cycle_id,args.generation,args.task),args.json); return 0
    except Exception as exc: return _fail(exc)

def cmd_cycle_status(args) -> int:
    try:
        _emit(autonomy_cycle.cycle_status(args.profile), args.json)
        return 0
    except Exception as exc:
        return _fail(exc)


def cmd_cycle_end(args) -> int:
    try:
        _emit(autonomy_cycle.end_cycle(args.profile, args.cycle_id, args.generation, result=args.result), args.json)
        return 0
    except Exception as exc:
        return _fail(exc)



def cmd_decide(args) -> int:
    try:
        if autonomy_records.pending_autonomy_decision(args.profile, args.task) is None:
            raise ValueError(f"AUTONOMY_DECISION_NOT_PENDING: {args.task}")
        _emit(autonomy_records.record_decision(args.profile, args.task, decision=args.decision, reason=args.reason), args.json)
        return 0
    except Exception as exc:
        return _fail(exc)


def cmd_route(args) -> int:
    try:
        autonomy_cycle.require_cycle_token(args.profile, args.cycle_id, args.generation)
        autonomy_cycle.claim_task(args.profile, args.cycle_id, args.generation, args.task)
        # Verify the previously dispatched effects:[] stage before allowing the
        # workflow to advance or dispatch that stage again.  Guards intentionally
        # survive cycle boundaries.
        autonomy_effects.verify_pending_guard(args.profile, args.task)
        autonomy_records.resume_if_satisfied(args.profile, args.task, args.generation)
        profile = autonomy_profile.load_profile(args.profile)
        effects = autonomy_records.allowed_effects(args.profile, args.task, args.generation)
        runtime_id = str((profile.get("autonomous") or {}).get("runtime_project_id") or "")
        from pathlib import Path as _Path
        db_path = _Path((profile.get("autonomous") or {}).get("workspace_root")) / ".tp-spec" / "db" / f"{runtime_id}.db"
        policy = str((profile.get("workflow") or {}).get("confirmation_policy") or "material")
        route = orchestration.resolve_route(args.task, db_path=str(db_path), confirmation_policy=policy, allowed_effects=effects)
        if route.get("recommended_action") in {"await_effect_approval", "await_confirmation"}:
            route = autonomy_records.block_for_route(args.profile, args.task, route, cycle_id=args.cycle_id, generation=args.generation)
        else:
            pending = autonomy_records.pending_workflow_confirmation(args.profile, args.task)
            if pending:
                route["autonomy_waiting_reason"] = pending.get("waiting_reason")
            if route.get("decision") == "DISPATCH_ROLE":
                autonomy_effects.arm_stage_guard(
                    args.profile, args.task, cycle_id=args.cycle_id, generation=args.generation,
                    stage=str(route.get("next_stage") or ""), role_id=str(route.get("role_id") or ""),
                    declared_effects=list(route.get("required_effects") or []),
                )
        _emit(route, args.json)
        return 0
    except Exception as exc:
        return _fail(exc)



def cmd_discover(args) -> int:
    try:
        _emit(autonomy_discovery.discover(
            profile_id=args.profile, cycle_id=args.cycle_id, generation=args.generation,
            discovery_key=args.discovery_key, title=args.title, summary=args.summary, risk=args.risk, flow=args.flow,
        ), args.json)
        return 0
    except Exception as exc:
        return _fail(exc)


def cmd_digest(args) -> int:
    try:
        _emit(autonomy_digest.write_digest(args.profile,args.cycle_id,args.generation),args.json)
        return 0
    except Exception as exc:
        return _fail(exc)



def cmd_batch_create(args) -> int:
    try:
        _emit(autonomy_batch.create_batch(args.profile,args.cycle_id,args.generation,args.task),args.json); return 0
    except Exception as exc: return _fail(exc)

def cmd_batch_start_task(args) -> int:
    try:
        _emit(autonomy_batch.start_task(args.profile,args.batch,args.task,args.cycle_id,args.generation),args.json); return 0
    except Exception as exc: return _fail(exc)

def cmd_batch_commit_task(args) -> int:
    try:
        _emit(autonomy_batch.commit_task(args.profile,args.batch,args.task,args.cycle_id,args.generation),args.json); return 0
    except Exception as exc: return _fail(exc)

def cmd_batch_abort_task(args) -> int:
    try:
        _emit(autonomy_batch.abort_task(args.profile,args.batch,args.task,args.cycle_id,args.generation),args.json); return 0
    except Exception as exc: return _fail(exc)

def cmd_batch_finalize(args) -> int:
    try:
        _emit(autonomy_batch.finalize_batch(args.profile,args.batch,args.cycle_id,args.generation),args.json); return 0
    except Exception as exc: return _fail(exc)

def cmd_batch_show(args) -> int:
    try:
        _emit(autonomy_batch.load_batch(args.profile,args.batch),args.json); return 0
    except Exception as exc: return _fail(exc)

def cmd_review_inbox(args) -> int:
    try: _emit(autonomy_review.inbox(),args.json); return 0
    except Exception as exc: return _fail(exc)

def cmd_review_profile(args) -> int:
    try: _emit(autonomy_review.review_profile(args.profile),args.json); return 0
    except Exception as exc: return _fail(exc)

def cmd_review_batch(args) -> int:
    try: _emit(autonomy_review.review_batch(args.profile,args.batch),args.json); return 0
    except Exception as exc: return _fail(exc)

def cmd_review_task(args) -> int:
    try: _emit(autonomy_review.review_task(args.profile,args.task,include_diff=args.diff),args.json); return 0
    except Exception as exc: return _fail(exc)


def cmd_integrate_prepare(args) -> int:
    try: _emit(autonomy_integration.prepare(args.profile,args.batch),args.json); return 0
    except Exception as exc: return _fail(exc)

def cmd_integrate_verify(args) -> int:
    try: _emit(autonomy_integration.record_verification(args.profile,args.integration,decision=args.decision,evidence=args.evidence),args.json); return 0
    except Exception as exc: return _fail(exc)

def cmd_integrate_apply(args) -> int:
    try: _emit(autonomy_integration.apply(args.profile,args.integration),args.json); return 0
    except Exception as exc: return _fail(exc)

def cmd_integrate_show(args) -> int:
    try: _emit(autonomy_integration.load_integration(args.profile,args.integration),args.json); return 0
    except Exception as exc: return _fail(exc)

def cmd_integrate_capability(args) -> int:
    _emit(autonomy_integration.capability(),args.json); return 0

def add_autonomy_subparsers(subparsers) -> None:
    p = subparsers.add_parser("autonomy", help="Long-lived isolated Autonomous Maintenance control plane")
    sub = p.add_subparsers(dest="subcommand", required=True)

    pp = sub.add_parser("profile", help="Manage user-level Autonomy Profiles")
    psub = pp.add_subparsers(dest="profile_command", required=True)

    pc = psub.add_parser("create")
    pc.add_argument("--id", required=True)
    pc.add_argument("--canonical-root", required=True)
    pc.add_argument("--canonical-project", required=True)
    pc.add_argument("--autonomy-root", required=True)
    pc.add_argument("--mutable-repo", action="append", required=True)
    pc.add_argument("--support-repo", action="append", default=[])
    pc.add_argument("--goal", action="append", required=True)
    pc.add_argument("--difficulty-ceiling", choices=["L0", "L1", "L2", "L3"], required=True)
    pc.add_argument("--max-new-tasks", type=int, required=True)
    pc.add_argument("--confirmation-policy", choices=["material", "each_stage"], default="material")
    pc.add_argument("--json", action="store_true")
    pc.set_defaults(func=cmd_profile_create)

    ps = psub.add_parser("show")
    ps.add_argument("--id", required=True); ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=cmd_profile_show)
    ped = psub.add_parser("edit")
    ped.add_argument("--id",required=True); ped.add_argument("--goal",action="append"); ped.add_argument("--difficulty-ceiling",choices=["L0","L1","L2","L3"]); ped.add_argument("--max-new-tasks",type=int); ped.add_argument("--confirmation-policy",choices=["material","each_stage"]); ped.add_argument("--json",action="store_true"); ped.set_defaults(func=cmd_profile_edit)

    pref = psub.add_parser("refresh-prompt")
    pref.add_argument("--id",required=True); pref.add_argument("--json",action="store_true"); pref.set_defaults(func=cmd_profile_refresh_prompt)

    pl = psub.add_parser("list")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_profile_list)

    pr = psub.add_parser("prompt")
    pr.add_argument("--id", required=True)
    pr.set_defaults(func=cmd_profile_prompt)

    pe = psub.add_parser("enable")
    pe.add_argument("--id", required=True); pe.add_argument("--json", action="store_true")
    pe.set_defaults(func=lambda args: cmd_profile_enabled(args, True))

    pd = psub.add_parser("disable")
    pd.add_argument("--id", required=True); pd.add_argument("--json", action="store_true")
    pd.set_defaults(func=lambda args: cmd_profile_enabled(args, False))

    workspace = sub.add_parser("workspace", help="Initialize or inspect the long-lived isolated workspace")
    wsub = workspace.add_subparsers(dest="workspace_command", required=True)
    wi = wsub.add_parser("init")
    wi.add_argument("--profile", required=True); wi.add_argument("--json", action="store_true")
    wi.set_defaults(func=cmd_workspace_init)
    ws = wsub.add_parser("status")
    ws.add_argument("--profile", required=True); ws.add_argument("--no-refresh", action="store_true"); ws.add_argument("--json", action="store_true")
    ws.set_defaults(func=cmd_workspace_status)

    cycle = sub.add_parser("cycle", help="Generation-fenced unattended cycle control")
    csub = cycle.add_subparsers(dest="cycle_command", required=True)
    cb = csub.add_parser("begin")
    cb.add_argument("--profile", required=True); cb.add_argument("--executor-kind", default="local-agent"); cb.add_argument("--json", action="store_true")
    cb.set_defaults(func=cmd_cycle_begin)
    cs = csub.add_parser("status")
    cs.add_argument("--profile", required=True); cs.add_argument("--json", action="store_true")
    cs.set_defaults(func=cmd_cycle_status)
    cr = csub.add_parser("claim-rework")
    cr.add_argument("--profile",required=True); cr.add_argument("--task",required=True); cr.add_argument("--cycle-id",required=True); cr.add_argument("--generation",type=int,required=True); cr.add_argument("--json",action="store_true")
    cr.set_defaults(func=cmd_cycle_claim_rework)
    ce = csub.add_parser("end")
    ce.add_argument("--profile", required=True); ce.add_argument("--cycle-id", required=True); ce.add_argument("--generation", type=int, required=True)
    ce.add_argument("--result", choices=["COMPLETED", "BLOCKED", "FAILED", "EXPIRED"], default="COMPLETED"); ce.add_argument("--json", action="store_true")
    ce.set_defaults(func=cmd_cycle_end)

    decide = sub.add_parser("decide", help="human_owner approve/reject an autonomy-discovered Task; user-session command")
    decide.add_argument("--profile", required=True); decide.add_argument("--task", required=True)
    decide.add_argument("--decision", choices=["APPROVED", "REJECTED"], required=True); decide.add_argument("--reason", required=True)
    decide.add_argument("--json", action="store_true"); decide.set_defaults(func=cmd_decide)

    route = sub.add_parser("route", help="Cycle-scoped unattended workflow routing with execution envelope")
    route.add_argument("--profile", required=True); route.add_argument("--task", required=True)
    route.add_argument("--cycle-id", required=True); route.add_argument("--generation", type=int, required=True); route.add_argument("--json", action="store_true")
    route.set_defaults(func=cmd_route)

    discover = sub.add_parser("discover", help="Cycle-scoped bookkeeping for one AI-selected high-value Task candidate")
    discover.add_argument("--profile", required=True); discover.add_argument("--cycle-id", required=True); discover.add_argument("--generation", type=int, required=True)
    discover.add_argument("--discovery-key", required=True); discover.add_argument("--title", required=True); discover.add_argument("--summary", required=True)
    discover.add_argument("--risk", choices=["L0","L1","L2","L3"], required=True); discover.add_argument("--flow", choices=["L0","L1","L2","L3"], required=True)
    discover.add_argument("--json", action="store_true"); discover.set_defaults(func=cmd_discover)

    digest = sub.add_parser("digest", help="Cycle-scoped redacted status/digest projection")
    digest.add_argument("--profile", required=True); digest.add_argument("--cycle-id", required=True); digest.add_argument("--generation", type=int, required=True); digest.add_argument("--json", action="store_true")
    digest.set_defaults(func=cmd_digest)

    batch = sub.add_parser("batch", help="Thin cycle-scoped Batch / Task-to-commit binding")
    bsub = batch.add_subparsers(dest="batch_command", required=True)
    bc = bsub.add_parser("create"); bc.add_argument("--profile",required=True); bc.add_argument("--cycle-id",required=True); bc.add_argument("--generation",type=int,required=True); bc.add_argument("--task",action="append",required=True); bc.add_argument("--json",action="store_true"); bc.set_defaults(func=cmd_batch_create)
    bs = bsub.add_parser("start-task"); bs.add_argument("--profile",required=True); bs.add_argument("--batch",required=True); bs.add_argument("--task",required=True); bs.add_argument("--cycle-id",required=True); bs.add_argument("--generation",type=int,required=True); bs.add_argument("--json",action="store_true"); bs.set_defaults(func=cmd_batch_start_task)
    bm = bsub.add_parser("commit-task"); bm.add_argument("--profile",required=True); bm.add_argument("--batch",required=True); bm.add_argument("--task",required=True); bm.add_argument("--cycle-id",required=True); bm.add_argument("--generation",type=int,required=True); bm.add_argument("--json",action="store_true"); bm.set_defaults(func=cmd_batch_commit_task)
    ba = bsub.add_parser("abort-task"); ba.add_argument("--profile",required=True); ba.add_argument("--batch",required=True); ba.add_argument("--task",required=True); ba.add_argument("--cycle-id",required=True); ba.add_argument("--generation",type=int,required=True); ba.add_argument("--json",action="store_true"); ba.set_defaults(func=cmd_batch_abort_task)
    bf = bsub.add_parser("finalize"); bf.add_argument("--profile",required=True); bf.add_argument("--batch",required=True); bf.add_argument("--cycle-id",required=True); bf.add_argument("--generation",type=int,required=True); bf.add_argument("--json",action="store_true"); bf.set_defaults(func=cmd_batch_finalize)
    bsh = bsub.add_parser("show"); bsh.add_argument("--profile",required=True); bsh.add_argument("--batch",required=True); bsh.add_argument("--json",action="store_true"); bsh.set_defaults(func=cmd_batch_show)

    review = sub.add_parser("review", help="Read-only autonomy inbox / Batch / Task Git review")
    rsub = review.add_subparsers(dest="review_command", required=True)
    ri=rsub.add_parser("inbox"); ri.add_argument("--json",action="store_true"); ri.set_defaults(func=cmd_review_inbox)
    rp=rsub.add_parser("profile"); rp.add_argument("--profile",required=True); rp.add_argument("--json",action="store_true"); rp.set_defaults(func=cmd_review_profile)
    rb=rsub.add_parser("batch"); rb.add_argument("--profile",required=True); rb.add_argument("--batch",required=True); rb.add_argument("--json",action="store_true"); rb.set_defaults(func=cmd_review_batch)
    rt=rsub.add_parser("task"); rt.add_argument("--profile",required=True); rt.add_argument("--task",required=True); rt.add_argument("--diff",action="store_true"); rt.add_argument("--json",action="store_true"); rt.set_defaults(func=cmd_review_task)

    integrate = sub.add_parser("integrate", help="User-session prepare/verify/apply bridge to Canonical repos")
    isub = integrate.add_subparsers(dest="integrate_command", required=True)
    ip=isub.add_parser("prepare"); ip.add_argument("--profile",required=True); ip.add_argument("--batch",action="append",required=True); ip.add_argument("--json",action="store_true"); ip.set_defaults(func=cmd_integrate_prepare)
    iv=isub.add_parser("verify"); iv.add_argument("--profile",required=True); iv.add_argument("--integration",required=True); iv.add_argument("--decision",choices=["PASS","FAIL"],required=True); iv.add_argument("--evidence",action="append",required=True); iv.add_argument("--json",action="store_true"); iv.set_defaults(func=cmd_integrate_verify)
    ia=isub.add_parser("apply"); ia.add_argument("--profile",required=True); ia.add_argument("--integration",required=True); ia.add_argument("--json",action="store_true"); ia.set_defaults(func=cmd_integrate_apply)
    ish=isub.add_parser("show"); ish.add_argument("--profile",required=True); ish.add_argument("--integration",required=True); ish.add_argument("--json",action="store_true"); ish.set_defaults(func=cmd_integrate_show)
    ic=isub.add_parser("capability"); ic.add_argument("--json",action="store_true"); ic.set_defaults(func=cmd_integrate_capability)

    doctor = sub.add_parser("doctor", help="Validate an Autonomy Profile and its canonical scope")
    doctor.add_argument("--profile", required=True)
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)
