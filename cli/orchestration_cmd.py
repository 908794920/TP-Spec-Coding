# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import environment
from . import orchestration
from . import workflow_controls
from . import workflow_records


def _emit(data, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(yaml.safe_dump(data, allow_unicode=True, sort_keys=False).rstrip())


def _preferences_path() -> Path:
    return environment.user_tp_spec_root() / "preferences.yaml"


def cmd_next(args) -> int:
    try:
        route = orchestration.resolve_route(
            args.task, db_path=args.db, base_root=args.base_root,
            confirmation_policy=args.confirmation_policy,
            allowed_effects=args.allowed_effect,
        )
    except Exception as exc:
        print(f"WORKFLOW_ROUTE_ERROR: {exc}", file=sys.stderr)
        return 4
    _emit(route, args.json)
    return 0


def cmd_doctor(args) -> int:
    errors = orchestration.validate_contract(args.base_root)
    data = {
        "schema": "tp-spec.workflow-doctor/v1",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }
    _emit(data, args.json)
    return 0 if not errors else 1


def cmd_preference(args) -> int:
    try:
        path = _preferences_path()
        if args.set_policy:
            workflow_controls.write_user_confirmation_policy(path, args.set_policy)
        contract = orchestration.load_contract(args.base_root)
        default = str((contract.get("confirmation") or {}).get("default_policy") or "material")
        configured = workflow_controls.read_user_confirmation_policy(path)
        effective = workflow_controls.resolve_confirmation_policy(None, path, default)
        data = {
            "schema": "tp-spec.workflow-preference/v1",
            "path": str(path),
            "configured_confirmation_policy": configured,
            "effective_confirmation_policy": effective,
            "base_default": default,
            "project_override_supported": False,
        }
        _emit(data, args.json)
        return 0
    except Exception as exc:
        print(f"WORKFLOW_PREFERENCE_ERROR: {exc}", file=sys.stderr)
        return 4


def cmd_confirm(args) -> int:
    try:
        route = workflow_records.confirm_boundary(
            task_id=args.task,
            task_dir=args.task_dir,
            db=args.db,
            confirmation_policy=args.confirmation_policy,
        )
    except Exception as exc:
        print(f"WORKFLOW_CONFIRM_ERROR: {exc}", file=sys.stderr)
        return 4
    _emit(route, args.json)
    return 0


def add_workflow_subparsers(subparsers) -> None:
    p = subparsers.add_parser("workflow", help="Read-only workflow routing plus explicit human boundary confirmation")
    sub = p.add_subparsers(dest="subcommand", required=True)

    pn = sub.add_parser("next", help="Resolve the next workflow role from existing Task facts (read-only)")
    pn.add_argument("--task", required=True)
    pn.add_argument("--db", default=None)
    pn.add_argument("--base-root", default=None)
    pn.add_argument("--confirmation-policy", choices=["material", "each_stage"], default=None)
    pn.add_argument("--allowed-effect", action="append", choices=["repo_mutation"], default=None,
                    help="optional execution-envelope effect allowed by an external controller")
    pn.add_argument("--json", action="store_true")
    pn.set_defaults(func=cmd_next)

    pc = sub.add_parser("confirm", help="human_owner: confirm the currently bound ordinary(each_stage) or material workflow boundary")
    pc.add_argument("--task", required=True)
    pc.add_argument("--task-dir", required=True)
    pc.add_argument("--db", default=None)
    pc.add_argument("--confirmation-policy", choices=["material", "each_stage"], default=None)
    pc.add_argument("--json", action="store_true")
    pc.set_defaults(func=cmd_confirm)

    pp = sub.add_parser("preference", help="Show or set the user-level workflow confirmation preference")
    pp.add_argument("--set", dest="set_policy", choices=["material", "each_stage"], default=None)
    pp.add_argument("--base-root", default=None)
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_preference)

    pd = sub.add_parser("doctor", help="Validate orchestration contract and role references (read-only)")
    pd.add_argument("--base-root", default=None)
    pd.add_argument("--json", action="store_true")
    pd.set_defaults(func=cmd_doctor)
