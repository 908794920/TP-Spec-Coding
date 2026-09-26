# -*- coding: utf-8 -*-
"""Read-only CLI adapter for the shared built-in/external skill catalog."""
from __future__ import annotations

import argparse
import json
import sys

from .skill_catalog import (
    CATALOG_SCHEMA, DOCUMENT_SCHEMA, SkillCatalogError,
    load_skill_catalog, read_skill_document,
)


def _error(exc: SkillCatalogError, *, as_json: bool, schema: str) -> int:
    if as_json:
        print(json.dumps({"schema": schema, "status": "error", "error_code": exc.code,
                          "message": str(exc)}, ensure_ascii=False))
    else:
        print(f"{exc.code}: {exc}", file=sys.stderr)
    return 1


def cmd_list(args: argparse.Namespace) -> int:
    try:
        catalog = load_skill_catalog()
    except SkillCatalogError as exc:
        return _error(exc, as_json=args.json, schema=CATALOG_SCHEMA)
    query = args.query.strip().casefold()
    if query:
        def matches(node):
            fields = [node.get(key, "") for key in ("id", "name", "description", "source_kind", "upstream")]
            fields.extend(node.get("applies_to", []))
            return any(query in str(value).casefold() for value in fields)
        catalog["nodes"] = {key: node for key, node in catalog["nodes"].items() if matches(node)}
        ids = catalog["nodes"]
        catalog["edges"] = [edge for edge in catalog["edges"] if edge["from"] in ids and edge["to"] in ids]
        if catalog["root_id"] not in ids:
            catalog["root_id"] = ""
    catalog["query"] = args.query.strip()
    if args.json:
        print(json.dumps(catalog, ensure_ascii=False))
    else:
        for node in catalog["nodes"].values():
            description = " ".join(node.get("description", "").split())
            name = " ".join(node["name"].split())
            print(f"{node['id']} [{node['status']}] {node['source_kind']} {name}"
                  + (f" — {description[:240]}" if description else ""))
        for problem in catalog["problems"]:
            print(f"{problem['code']}: {problem.get('node_id', '')} {problem['message']}", file=sys.stderr)
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    try:
        document = read_skill_document(args.id, args.path)
    except SkillCatalogError as exc:
        return _error(exc, as_json=args.json, schema=DOCUMENT_SCHEMA)
    if args.json:
        print(json.dumps(document, ensure_ascii=False))
    else:
        sys.stdout.write(document["content"])
    return 0


def add_skill_subparsers(subparsers) -> None:
    parser = subparsers.add_parser("skill", help="Read built-in and user-level external skills")
    commands = parser.add_subparsers(dest="subcommand", required=True)
    listing = commands.add_parser("list", help="Compact discovery; no skill bodies or Runtime writes")
    listing.add_argument("--query", default="", help="Filter IDs, names, descriptions and declared associations")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_list)
    reading = commands.add_parser("read", help="Read an available skill by exact source-qualified ID")
    reading.add_argument("--id", required=True, help="Built-in ID or external:local:<package-directory>")
    reading.add_argument("--path", default="", help="Markdown path relative to Base or this external package")
    reading.add_argument("--json", action="store_true")
    reading.set_defaults(func=cmd_read)
