"""Stable Knowledge document identities and bounded, read-only FTS document queries.

This adapts the existing documents/chunks/fts_chunks tables; it is not another
index. Sorting, per-document chunk deduplication, counting and pagination run in
SQLite. No filesystem inventory/doctor/full integrity scan runs on this path.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sqlite3
from urllib.parse import unquote

from cli.path_identity import path_identity_key
from .common import CANONICAL_SUBDIRS, load_project_registry, resolve_knowledge_project, meta_paths, read_jsonl
from .telemetry import KnowledgeError, columns, connect_readonly


def source_identity(cfg) -> str:
    return hashlib.sha256(path_identity_key(cfg.paths.knowledge_physical_root).encode("utf-8")).hexdigest()[:24]


def document_key(cfg, layer: str, canonical_id: str, relative: str) -> str:
    identity = canonical_id if layer == "canonical" and canonical_id else relative
    digest = hashlib.sha256((layer + "\0" + identity).encode("utf-8")).hexdigest()
    return "knowledge:" + source_identity(cfg) + ":" + digest


def scopes(cfg) -> list[dict]:
    data, _ = load_project_registry(cfg)
    if not cfg.paths.knowledge_registry.is_file():
        raise KnowledgeError("KNOWLEDGE_REGISTRY_MISSING")
    result, seen = [], set()
    for field, shared in (("projects", False), ("shared_scopes", True)):
        for row in data.get(field) or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            value = str(row["id"])
            if value in seen:
                raise KnowledgeError("KNOWLEDGE_DUPLICATE_PROJECT")
            seen.add(value)
            if value in {".", ".."} or any(c in value for c in "/\\:\x00"):
                raise KnowledgeError("KNOWLEDGE_INVALID_PROJECT_REGISTRY")
            result.append({"id": value, "name": str(row.get("display_name") or row.get("name") or row.get("title") or value),
                           "shared": shared, "status": str(row.get("status") or "active")})
    return result


def resolve_scope(cfg, *, project=None, scope=None) -> dict:
    catalog = scopes(cfg)
    by_id = {row["id"]: row for row in catalog}
    selected_scope = scope or "project"  # New AI entry never inherits global/global_fallback.
    if selected_scope not in {"project", "global"} or (project and selected_scope == "global"):
        raise KnowledgeError("KNOWLEDGE_INVALID_SCOPE")
    if selected_scope == "global":
        return {"scope": "global", "project": "", "projects": sorted(by_id)}
    selected = str(project or "")
    if not selected:
        resolved = resolve_knowledge_project(cfg, require=True)
        selected = str(resolved.get("project_id") or "")
    if not selected or selected not in by_id:
        raise KnowledgeError("KNOWLEDGE_PROJECT_UNRESOLVED")
    projects = [selected]
    if cfg.knowledge_retrieval.get("include_shared", True):
        projects += [row["id"] for row in catalog if row["shared"] and row["status"] != "archived"]
    return {"scope": "project", "project": selected, "projects": sorted(set(projects))}


def _relative(raw: str) -> str:
    if not isinstance(raw, str) or not raw or "\x00" in raw or "\\" in raw:
        raise KnowledgeError("KNOWLEDGE_DOCUMENT_BOUNDARY")
    # Do not turn encoded paths into filesystem locators. Any decoded escape is invalid.
    decoded = raw
    for _ in range(4):
        value = unquote(decoded)
        if value == decoded:
            break
        decoded = value
    for value in (raw, decoded):
        if (PureWindowsPath(value).drive or value.startswith(("/", "\\")) or "\\" in value
                or ":" in value or any(p in {".", ".."} for p in value.split("/"))):
            raise KnowledgeError("KNOWLEDGE_DOCUMENT_BOUNDARY")
    return raw


def document_root(cfg, row: dict) -> Path:
    """Require indexed scope AND registered physical subroot, not arbitrary disk paths."""
    by_id = {item["id"]: item for item in scopes(cfg)}
    project = str(row.get("project") or "")
    if project not in by_id:
        raise KnowledgeError("KNOWLEDGE_DOCUMENT_UNREGISTERED")
    root = cfg.paths.knowledge_physical_root.resolve(strict=True)
    canonical = cfg.knowledge_canonical
    if by_id[project]["shared"]:
        boundary = root / str(canonical.get("shared_dir") or "20-shared")
        if row.get("scope", row.get("layer")) != "canonical":
            raise KnowledgeError("KNOWLEDGE_DOCUMENT_BOUNDARY")
    else:
        boundary = root / str(canonical.get("projects_dir") or "10-projects") / project
        if row.get("scope", row.get("layer")) == "source":
            boundary = boundary / str(canonical.get("source_dir") or "90-sources")
        elif row.get("scope", row.get("layer")) == "canonical":
            relative = _relative(str(row.get("rel_path", row.get("path", ""))))
            prefix = boundary.relative_to(root).as_posix() + "/"
            if not relative.startswith(prefix) or relative[len(prefix):].split("/", 1)[0] not in CANONICAL_SUBDIRS:
                raise KnowledgeError("KNOWLEDGE_DOCUMENT_BOUNDARY")
        else:
            raise KnowledgeError("KNOWLEDGE_DOCUMENT_BOUNDARY")
    # A registered project/shared subtree must itself remain within the resolved Vault.
    resolved_boundary = boundary.resolve(strict=True)
    if not resolved_boundary.is_relative_to(root):
        raise KnowledgeError("KNOWLEDGE_DOCUMENT_BOUNDARY")
    return resolved_boundary


def registered_conversion_path(cfg, record: dict) -> Path:
    """Only the exact output of an existing registered ingestion conversion.

    A source registry is not blanket permission to read arbitrary origin paths.
    Resolve the declared conversion against the configured ingest root and the
    batch's converted/<origin>.md convention; never fetch an original or URL.
    """
    from .ingest import batch_paths, _ingest_root
    batch = _relative(str(record.get("batch") or ""))
    origin = _relative(str(record.get("origin_path") or ""))
    if record.get("conversion_status") != "converted":
        raise KnowledgeError("KNOWLEDGE_CONVERSION_NOT_REGISTERED")
    ingest_root = _ingest_root(cfg).resolve(strict=True)
    configured = Path(str(cfg.knowledge_ingest.get("manifest_root") or ".ai-kb/ingest"))
    vault = cfg.paths.knowledge_physical_root.resolve(strict=True)
    if not configured.is_absolute() and not ingest_root.is_relative_to(vault):
        raise KnowledgeError("KNOWLEDGE_DOCUMENT_BOUNDARY")
    boundary = (batch_paths(cfg, batch)["root"] / "converted").resolve(strict=True)
    if not boundary.is_relative_to(ingest_root):
        raise KnowledgeError("KNOWLEDGE_DOCUMENT_BOUNDARY")
    declared = str(record.get("conversion_path") or "")
    declared_path = Path(declared)
    if not declared_path.is_absolute():
        _relative(declared)
        declared_path = vault / declared_path
    target = declared_path.resolve(strict=True)
    expected = (boundary / (origin + ".md")).resolve(strict=True)
    if target != expected or not target.is_relative_to(boundary) or not target.is_file() or target.suffix.lower() != ".md":
        raise KnowledgeError("KNOWLEDGE_DOCUMENT_BOUNDARY")
    return target


def _conversion_for_row(cfg, row: dict) -> Path:
    registration = metadata(row).get("registered_conversion")
    if not isinstance(registration, dict) or row.get("scope", row.get("layer")) != "source":
        raise KnowledgeError("KNOWLEDGE_DOCUMENT_BOUNDARY")
    matches = [record for record in read_jsonl(meta_paths(cfg)["source_registry"])
               if all(str(record.get(name) or "") == str(registration.get(name) or "") for name in ("project", "batch", "origin_path"))]
    if len(matches) != 1 or str(matches[0].get("project")) != str(row.get("project")):
        raise KnowledgeError("KNOWLEDGE_CONVERSION_REGISTRATION_CHANGED")
    if str(row.get("project")) not in {item["id"] for item in scopes(cfg)}:
        raise KnowledgeError("KNOWLEDGE_DOCUMENT_UNREGISTERED")
    return registered_conversion_path(cfg, matches[0])


def document_path(cfg, row: dict) -> Path:
    relative = _relative(str(row.get("rel_path", row.get("path", ""))))
    if relative.startswith("@converted/"):
        return _conversion_for_row(cfg, row)
    lexical = cfg.paths.knowledge_physical_root.resolve(strict=True) / relative
    boundary = document_root(cfg, row)
    resolved = lexical.resolve(strict=True)
    if not resolved.is_relative_to(boundary) or not resolved.is_file() or resolved.suffix.lower() != ".md":
        raise KnowledgeError("KNOWLEDGE_DOCUMENT_BOUNDARY")
    return resolved


def configure_connection(conn, cfg):
    conn.create_function("knowledge_document_key", 3, lambda layer, cid, path: document_key(cfg, layer, cid, path), deterministic=True)
    fields = columns(conn, "documents")
    if not {"id", "rel_path", "scope", "project", "sha256"}.issubset(fields):
        raise KnowledgeError("KNOWLEDGE_INDEX_SCHEMA_UNSUPPORTED")
    key = ("COALESCE(NULLIF(d.document_key,''),knowledge_document_key(d.scope,d.canonical_id,d.rel_path))"
           if "document_key" in fields else "knowledge_document_key(d.scope,d.canonical_id,d.rel_path)")
    meta = "d.metadata_json" if "metadata_json" in fields else "'{}'"
    return key, meta


def scope_condition(cfg, projects=None) -> tuple[str, list]:
    catalog = scopes(cfg)
    if projects is not None:
        requested = set(projects)
        if requested - {row["id"] for row in catalog}:
            raise KnowledgeError("KNOWLEDGE_PROJECT_UNRESOLVED")
        catalog = [row for row in catalog if row["id"] in requested]
    conditions, params = [], []
    for row in catalog:
        if row["shared"]:
            prefixes = [(str(cfg.knowledge_canonical.get("shared_dir") or "20-shared") + "/", "canonical")]
        else:
            base = str(cfg.knowledge_canonical.get("projects_dir") or "10-projects") + "/" + row["id"] + "/"
            prefixes = [(base + name + "/", "canonical") for name in CANONICAL_SUBDIRS]
            prefixes.append((base + str(cfg.knowledge_canonical.get("source_dir") or "90-sources") + "/", "source"))
        for prefix, layer in prefixes:
            conditions.append("(d.project=? AND d.scope=? AND substr(d.rel_path,1,?)=?)")
            params += [row["id"], layer, len(prefix), prefix]
        # Metadata-only original sources are registered during explicit indexing.
        conditions.append("(d.project=? AND d.scope='source' AND (substr(d.rel_path,1,12)='@registered/' OR substr(d.rel_path,1,11)='@converted/'))")
        params.append(row["id"])
    return "(" + (" OR ".join(conditions) or "0") + ")", params


def metadata(row) -> dict:
    try:
        value = json.loads(row.get("metadata_json") or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def public_document(cfg, row: dict) -> dict:
    layer = row.get("scope", row.get("layer"))
    meta = metadata(row)
    key = document_key(cfg, layer, row.get("canonical_id") or "", row["rel_path"])
    mtime = int(row.get("mtime_ns") or 0)
    refs = json.loads(row.get("source_refs") or "[]")
    return {"key": key, "document_key": key,
            "id": row.get("canonical_id") if layer == "canonical" else row.get("source_id"),
            "canonical_id": row.get("canonical_id") or "", "source_id": row.get("source_id") or "",
            "title": row.get("title") or PurePosixPath(row["rel_path"]).name,
            "path": row["rel_path"], "project": row.get("project") or "", "layer": layer,
            "kind": row.get("kind") or "", "version": row.get("sha256") or None,
            "version_kind": "registered_source" if meta.get("metadata_only") else "document",
            "updated_at": datetime.fromtimestamp(mtime / 1e9, timezone.utc).isoformat() if mtime else meta.get("updated_at"),
            "status": meta.get("status") if isinstance(meta.get("status"), str) else None, "metadata_available": bool(meta),
            "metadata_only": bool(meta.get("metadata_only")), "source_refs": [value for value in refs if isinstance(value, str)] if isinstance(refs, list) else [],
            "evidence_refs": meta["evidence_refs"] if isinstance(meta.get("evidence_refs"), list) else [], "superseded": meta.get("superseded"),
            "replaced_by": meta.get("replaced_by"), "relations": meta["relations"] if isinstance(meta.get("relations"), list) else [],
            "origin": meta["origin"] if isinstance(meta.get("origin"), dict) else None, "conversion": meta.get("conversion") if isinstance(meta.get("conversion"), str) else None}


def query_documents(cfg, query="", *, projects=None, layer="", kind="", maintenance="",
                    keys=None, limit=20, offset=0, conn=None, count_only=False) -> dict:
    if (not isinstance(query, str) or len(query) > 512 or not 1 <= limit <= 20
            or not 0 <= offset <= 2_000_000 or layer not in {"", "canonical", "source"}):
        raise KnowledgeError("KNOWLEDGE_INVALID_QUERY")
    if conn is None:
        with connect_readonly(cfg.paths.knowledge_projection_db) as opened:
            return query_documents(cfg, query, projects=projects, layer=layer, kind=kind,
                                   maintenance=maintenance, keys=keys, limit=limit, offset=offset, conn=opened, count_only=count_only)
    from .projection import tokenize_query
    key_expr, meta_expr = configure_connection(conn, cfg)
    base_where, params = scope_condition(cfg, projects)
    params = list(params)
    where = [base_where]
    if layer:
        where.append("d.scope=?"); params.append(layer)
    if kind:
        where.append("d.kind=?"); params.append(kind)
    if maintenance:
        where.append(f"json_extract({meta_expr},'$.status')=?"); params.append(maintenance)
    if keys is not None:
        # JSON expansion avoids SQLite's parameter-count limit on a large adoption filter.
        where.append(f"{key_expr} IN (SELECT value FROM json_each(?))")
        params.append(json.dumps(sorted(set(keys))))
    expr = tokenize_query(query.strip())
    if expr:
        cte = """WITH matched AS MATERIALIZED (
            SELECT c.doc_id,c.id AS chunk_id,c.heading_path,c.line_start,c.line_end,c.content,c.content_hash,rank AS score
            FROM fts_chunks JOIN chunks c ON c.id=fts_chunks.rowid WHERE fts_chunks MATCH ?),
            best AS (SELECT *,ROW_NUMBER() OVER(PARTITION BY doc_id ORDER BY score,chunk_id) AS rn FROM matched)"""
        join = "LEFT JOIN best c ON c.doc_id=d.id AND c.rn=1"
        # An ID/path/title exact substring is useful even in old indexes whose FTS omitted IDs.
        where.append("(c.doc_id IS NOT NULL OR instr(lower(COALESCE(d.title,'')||' '||COALESCE(d.canonical_id,'')||' '||COALESCE(d.source_id,'')||' '||d.rel_path),lower(?))>0)")
        params = [expr, *params, query.strip()]
    else:
        cte = "WITH best AS (SELECT *,0.0 AS score FROM chunks WHERE 0)"
        join = "LEFT JOIN best c ON c.doc_id=d.id"
        if query.strip():
            where.append("instr(lower(COALESCE(d.title,'')||' '||COALESCE(d.canonical_id,'')||' '||COALESCE(d.source_id,'')||' '||d.rel_path),lower(?))>0")
            params.append(query.strip())
    eligible = f""", eligible AS (
        SELECT d.*, {key_expr} AS public_key, {meta_expr} AS public_metadata,
            c.heading_path,c.line_start,c.line_end,c.content_hash,c.content,COALESCE(c.score,0.0) AS score,
            ROW_NUMBER() OVER(PARTITION BY {key_expr} ORDER BY d.rel_path) AS document_rank
        FROM documents d {join} WHERE {' AND '.join(where)})"""
    sql = cte + eligible
    total = conn.execute(sql + " SELECT count(*) FROM eligible WHERE document_rank=1", params).fetchone()[0]
    if count_only:
        return {"items": [], "total": int(total), "count": 0, "offset": offset, "limit": limit, "count_kind": "documents"}
    rows = conn.execute(sql + """ SELECT * FROM eligible WHERE document_rank=1
        ORDER BY CASE scope WHEN 'canonical' THEN 0 ELSE 1 END,score,title COLLATE NOCASE,rel_path,public_key
        LIMIT ? OFFSET ?""", [*params, limit, offset]).fetchall()
    items = []
    for raw in rows:
        row = dict(raw)
        row["metadata_json"] = row["public_metadata"]
        item = public_document(cfg, row)
        # A stale symlink must never turn an indexed snippet into out-of-bound disclosure.
        if not item["metadata_only"]:
            try:
                document_path(cfg, row)
            except FileNotFoundError:
                item["availability"] = "missing"
            except (ValueError, OSError, RuntimeError):
                item["availability"] = "boundary_rejected"
            else:
                item["availability"] = "indexed"
        else:
            item["availability"] = "metadata_only"
        item.update(score=row["score"], heading_path=row.get("heading_path"),
                    line_start=row.get("line_start"), line_end=row.get("line_end"),
                    content_hash=row.get("content_hash"),
                    snippet=(str(row.get("content") or "")[:200] if item["availability"] == "indexed" else ""))
        items.append(item)
    return {"items": items, "total": int(total), "count": len(items), "offset": offset,
            "limit": limit, "count_kind": "documents"}


def find_document(cfg, key: str, *, projects=None, conn=None) -> dict:
    if not re.fullmatch(r"knowledge:[a-f0-9]{24}:[a-f0-9]{64}", key or ""):
        raise KnowledgeError("KNOWLEDGE_INVALID_DOCUMENT_ID")
    if conn is None:
        with connect_readonly(cfg.paths.knowledge_projection_db) as opened:
            return find_document(cfg, key, projects=projects, conn=opened)
    key_expr, meta_expr = configure_connection(conn, cfg)
    where, params = scope_condition(cfg, projects)
    rows = conn.execute(f"SELECT d.*, {meta_expr} AS public_metadata FROM documents d WHERE {where} AND {key_expr}=? LIMIT 2", [*params, key]).fetchall()
    if not rows:
        raise KnowledgeError("KNOWLEDGE_DOCUMENT_NOT_FOUND")
    if len(rows) > 1:
        raise KnowledgeError("KNOWLEDGE_DOCUMENT_ID_AMBIGUOUS")
    result = dict(rows[0]); result["metadata_json"] = result.pop("public_metadata")
    return result
