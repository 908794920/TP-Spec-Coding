# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import orchestration


def _emit(data, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(yaml.safe_dump(data, allow_unicode=True, sort_keys=False).rstrip())


def cmd_next(args) -> int:
    try:
        route = orchestration.resolve_route(
            args.task, db_path=args.db, base_root=args.base_root,
            confirmation_policy=args.confirmation_policy,
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


def add_workflow_subparsers(subparsers) -> None:
    p = subparsers.add_parser("workflow", help="V5.2.1 read-only workflow orchestration")
    sub = p.add_subparsers(dest="subcommand", required=True)
    pn = sub.add_parser("next", help="Resolve the next workflow role from existing Task facts (read-only)")
    pn.add_argument("--task", required=True)
    pn.add_argument("--db", default=None)
    pn.add_argument("--base-root", default=None)
    pn.add_argument("--confirmation-policy", choices=["material", "each_stage"], default=None)
    pn.add_argument("--json", action="store_true")
    pn.set_defaults(func=cmd_next)
    pd = sub.add_parser("doctor", help="Validate orchestration contract and role references (read-only)")
    pd.add_argument("--base-root", default=None)
    pd.add_argument("--json", action="store_true")
    pd.set_defaults(func=cmd_doctor)
