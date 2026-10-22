# -*- coding: utf-8 -*-
"""CLI handlers and argument registration for Wiki retrieval."""
from __future__ import annotations

import json
from typing import Any, Dict

from .config import load_content_systems
from .retrieval import (build_index as build_retrieval_index, index_status as retrieval_index_status,
                        inventory as retrieval_inventory, read_document as retrieval_read_document,
                        search as retrieval_search, telemetry as retrieval_telemetry,
                        update_index as update_retrieval_index)


def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_index_build(args) -> int:
    """Build the user-root Wiki retrieval projection explicitly."""
    try:
        cfg = load_content_systems(args.workspace_root, config_path=getattr(args, "content_config", None))
        result = build_retrieval_index(cfg)
        _emit({"schema": "tp-spec.wiki-retrieval-index/v1", "operation": "build", **result})
        return 0 if result.get("status") in {"PASS", "WARN"} else 1
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-retrieval-index/v1", "operation": "build", "status": "FAIL",
               "error": f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_index_update(args) -> int:
    """Refresh the user-root Wiki retrieval projection explicitly."""
    try:
        cfg = load_content_systems(args.workspace_root, config_path=getattr(args, "content_config", None))
        result = update_retrieval_index(cfg, catalog_only=getattr(args, "catalog_only", False))
        _emit({"schema": "tp-spec.wiki-retrieval-index/v1", "operation": "update", **result})
        return 0 if result.get("status") in {"PASS", "WARN"} else 1
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-retrieval-index/v1", "operation": "update", "status": "FAIL",
               "error": f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_index_status(args) -> int:
    """Read retrieval projection metadata without creating a database."""
    try:
        cfg = load_content_systems(args.workspace_root, config_path=getattr(args, "content_config", None))
        result = retrieval_index_status(cfg)
        _emit({"schema": "tp-spec.wiki-retrieval-index-status/v1", **result})
        return 0 if result.get("status") in {"PASS", "WARN", "MISSING"} else 1
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-retrieval-index-status/v1", "status": "FAIL",
               "error": f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_inventory(args) -> int:
    try:
        cfg = load_content_systems(args.workspace_root, config_path=getattr(args, "content_config", None))
        _emit({"schema": "tp-spec.wiki-inventory/v1", **retrieval_inventory(cfg)})
        return 0
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-inventory/v1", "status": "FAIL",
               "error": f"{type(exc).__name__}: {exc}"})
        return 1


def _telemetry_args(args) -> Dict[str, Any]:
    return {
        "task_id": str(getattr(args, "task", "") or ""),
        "actor_role": str(getattr(args, "role", "") or ""),
        "request_id": str(getattr(args, "request_id", "") or ""),
        "record_telemetry": not bool(getattr(args, "no_telemetry", False)),
    }


def cmd_search(args) -> int:
    try:
        cfg = load_content_systems(args.workspace_root, config_path=getattr(args, "content_config", None))
        result = retrieval_search(
            cfg, args.query, project=getattr(args, "project", "") or "", repo=getattr(args, "repo", "") or "",
            kind=getattr(args, "kind", "") or "", limit=getattr(args, "limit", 5),
            offset=getattr(args, "offset", 0), scope=getattr(args, "scope", "") or "", **_telemetry_args(args),
        )
        failed = result.get("status") == "failed" or bool(result.get("error"))
        if not failed and isinstance(result.get("index"), dict):
            result = dict(result)
            index = result["index"]
            result["index"] = {"status": index.get("status"), "indexed_at": index.get("indexed_at")}
        _emit({"schema": "tp-spec.wiki-search/v1", "status": "FAIL" if failed else "PASS", **result})
        return 1 if failed else 0
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-search/v1", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_read(args) -> int:
    try:
        document_id = str(getattr(args, "document_id", "") or getattr(args, "document_id_option", "") or "").strip()
        if not document_id:
            raise ValueError("read requires a document id or --document-id")
        start_line = getattr(args, "start_line", None)
        end_line = getattr(args, "end_line", None)
        if bool(getattr(args, "full", False)) and (start_line is not None or end_line is not None):
            raise ValueError("--full cannot be combined with --start-line/--end-line")
        cfg = load_content_systems(args.workspace_root, config_path=getattr(args, "content_config", None))
        result = retrieval_read_document(
            cfg, document_id, start_line=start_line, end_line=end_line, full=bool(getattr(args, "full", False)),
            **_telemetry_args(args),
        )
        if result.get("error"):
            _emit({"schema": "tp-spec.wiki-read/v1", "status": "FAIL", **result})
            return 1
        _emit({"schema": "tp-spec.wiki-read/v1", "status": "PASS", **result})
        return 0
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-read/v1", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        return 1


def cmd_retrieval_telemetry(args) -> int:
    try:
        cfg = load_content_systems(args.workspace_root, config_path=getattr(args, "content_config", None))
        _emit({"schema": "tp-spec.wiki-retrieval-telemetry/v1", **retrieval_telemetry(cfg, days=args.days)})
        return 0
    except Exception as exc:
        _emit({"schema": "tp-spec.wiki-retrieval-telemetry/v1", "status": "FAIL",
               "error": f"{type(exc).__name__}: {exc}"})
        return 1


def add_retrieval_subparsers(subs, _add_common) -> None:
    p = subs.add_parser("inventory", help="List registered Wiki projects, repositories, and manifest documents")
    _add_common(p); p.set_defaults(func=cmd_inventory)

    p = subs.add_parser("search", help="Search the user-root Wiki retrieval index")
    _add_common(p)
    p.add_argument("-q", "--query", required=True)
    p.add_argument("--project", help="explicit workspace/project id; omitted means current workspace")
    p.add_argument("--scope", choices=["current", "all"], default="current", help="current workspace by default; all is explicit")
    p.add_argument("--all", dest="scope", action="store_const", const="all", help="explicitly search all registered Wiki workspaces")
    p.add_argument("--kind", default="")
    p.add_argument("--limit", type=int, default=5, help="results per page; defaults to 5 and is capped at 20")
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--task", default="")
    p.add_argument("--role", default="")
    p.add_argument("--request-id", default="")
    p.add_argument("--no-telemetry", action="store_true")
    p.set_defaults(func=cmd_search)

    p = subs.add_parser("read", help="Read one registered Wiki document, optionally by one-based line range")
    _add_common(p)
    p.add_argument("document_id", nargs="?")
    p.add_argument("--document-id", dest="document_id_option")
    p.add_argument("--start-line", type=int)
    p.add_argument("--end-line", type=int)
    p.add_argument("--full", action="store_true", help="return full document text; cannot combine with line ranges")
    p.add_argument("--task", default="")
    p.add_argument("--role", default="")
    p.add_argument("--request-id", default="")
    p.add_argument("--no-telemetry", action="store_true")
    p.set_defaults(func=cmd_read)

    p = subs.add_parser("telemetry", help="Read Wiki retrieval telemetry without writing")
    _add_common(p)
    p.add_argument("--days", type=int, default=30)
    p.set_defaults(func=cmd_retrieval_telemetry)

    p = subs.add_parser("index", help="Build or inspect the user-root Wiki retrieval projection")
    _add_common(p)
    index_subs = p.add_subparsers(dest="index_cmd", required=True)
    child = index_subs.add_parser("build", help="Build the complete registered Wiki FTS5 index")
    _add_common(child, suppress_defaults=True); child.set_defaults(func=cmd_index_build)
    child = index_subs.add_parser("update", help="Refresh the registered Wiki FTS5 index")
    child.add_argument("--catalog-only", action="store_true", help="Refresh only manifest parse metadata in the existing index; do not rebuild document/FTS rows")
    _add_common(child, suppress_defaults=True); child.set_defaults(func=cmd_index_update)
    child = index_subs.add_parser("status", help="Read retrieval index metadata")
    _add_common(child, suppress_defaults=True); child.set_defaults(func=cmd_index_status)
