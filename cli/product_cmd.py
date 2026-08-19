# -*- coding: utf-8 -*-
from __future__ import annotations

import json

from .product_router import route_domain


def cmd_route(args) -> int:
    decision = route_domain(args.text, active_task_domain=getattr(args, "active_task_domain", None))
    payload = decision.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"domain={decision.domain} confidence={decision.confidence} reason={decision.reason_code}")
    return 0


def add_product_subparsers(subparsers) -> None:
    p = subparsers.add_parser("route", help="Low-context tp-spec-coding Domain routing")
    p.add_argument("--text", required=True, help="current user intent; no repository or task deep-read is performed")
    p.add_argument("--active-task-domain", default=None, choices=["software", "wiki", "knowledge", "base", "autonomy"])
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_route)
