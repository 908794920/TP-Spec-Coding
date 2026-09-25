# -*- coding: utf-8 -*-
"""Bounded local Wiki retrieval and usage telemetry.

The Wiki files remain the source of truth.  This module only reads documents
listed by registered Wiki manifests and stores a rebuildable SQLite projection
under the user TP-Spec root.  In particular, it never uses a repository working
tree as an implicit document source and it never writes below a Wiki root.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Tuple
import copy
import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from urllib.parse import quote

import yaml

from cli import environment
from cli.knowledge.projection import tokenize as _knowledge_tokenize
from .registry import load_registry


MAX_RESULTS = 20
TELEMETRY_RETENTION_DAYS = 90
DB_RELATIVE_PATH = Path("wiki") / "retrieval.db"
MANIFEST_NAME = "meta/wiki-manifest.yaml"
_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+(.+?)\s*$")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_RECEIPT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SECRET_RE = re.compile(
    r"(?ix)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?token|authorization)"
    r"\s*(?:=|:)\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_URL_CREDENTIAL_RE = re.compile(r"(?i)(://[^/@\s:]+:)[^/@\s]+(@)")


class RetrievalError(ValueError):
    """A deterministic retrieval/input error safe for the CLI boundary."""


class _TelemetryConflict(RetrievalError):
    pass


_CATALOG_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _iso_from_mtime(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _within(path: Path, root: Path) -> bool:
    """Return true only when *path* is contained by *root* after resolution."""
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (OSError, ValueError):
        return False


def _safe_relative(value: Any) -> Optional[str]:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or _WINDOWS_ABSOLUTE_RE.match(raw):
        return None
    pure = PurePosixPath(raw)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    return pure.as_posix()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_read_text(path: Path) -> Tuple[str, bytes]:
    data = path.read_bytes()
    # Wiki documents are Markdown/text.  utf-8-sig keeps the public content
    # stable when a legacy document has a BOM.
    return data.decode("utf-8-sig"), data


def _redact_query(value: Any) -> str:
    text = str(value or "")
    text = _SECRET_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    return _URL_CREDENTIAL_RE.sub(r"\1[REDACTED]\2", text)


def _query_hash(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _portable_receipt(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text or len(text) > 128 or not _RECEIPT_RE.fullmatch(text):
        return None
    return text


def _storage_root() -> Path:
    return _canonical(environment.user_tp_spec_root()) / "wiki"


def _source_id_for_cfg(cfg: Any) -> str:
    """Resolve the source identity used for the current config's local DB."""
    try:
        registry = load_registry(cfg)
    except Exception:
        registry = {}
    return _source_id(cfg, registry)


def retrieval_db_path(cfg: Any = None, *, source_id: str = "") -> Path:
    """Return the isolated user-root database path without creating it.

    Each resolved Wiki registry/source gets its own directory.  A shared
    ``~/.tp-spec/wiki/retrieval.db`` would let one registry's rebuild delete a
    different registry's projection.
    """
    sid = str(source_id or (_source_id_for_cfg(cfg) if cfg is not None else "unresolved-source"))
    if not re.fullmatch(r"[0-9a-f]{64}", sid):
        sid = hashlib.sha256(sid.encode("utf-8")).hexdigest()
    return _storage_root() / sid / "retrieval.db"


def _registry_identity(cfg: Any, registry: Dict[str, Any]) -> str:
    registry_path = _canonical(cfg.paths.wiki_registry)
    # The source identity names the local source location and registry, not its
    # mutable display/repository contents.  Registry contents belong in the
    # indexed catalog fingerprint so adding a repo makes an index stale without
    # orphaning all historical telemetry for the same source.
    identity = {
        "path": str(registry_path),
        "layout": str(getattr(cfg.paths, "wiki_layout", "")),
        "workspace_dir_template": str(getattr(cfg, "data", {}).get("systems", {}).get("wiki", {}).get("workspace_dir_template") or ""),
    }
    blob = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return blob


def _source_id(cfg: Any, registry: Dict[str, Any]) -> str:
    wiki_root = _canonical(cfg.paths.wiki_system_root)
    payload = f"{wiki_root}\n{_registry_identity(cfg, registry)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _repo_wiki_root(cfg: Any, workspace_id: str, repo_id: str, group: str = "") -> Path:
    if cfg.paths.wiki_layout == "legacy-central":
        template = str(cfg.data.get("systems", {}).get("wiki", {}).get("workspace_dir_template") or
                       "projects/{workspace_id}")
        base = cfg.paths.wiki_system_root / template.format(workspace_id=workspace_id)
    else:
        base = cfg.paths.wiki_system_root
    if group:
        base = base / group
    return _canonical(base / repo_id)


def _target_rows(cfg: Any, registry: Dict[str, Any], source_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Resolve only enabled registry entries to their expected Wiki roots."""
    rows: List[Dict[str, Any]] = []
    problems: List[Dict[str, str]] = []
    wiki_root = _canonical(cfg.paths.wiki_system_root)
    workspaces = registry.get("workspaces") if isinstance(registry, dict) else None
    if not isinstance(workspaces, list):
        problems.append({"code": "WIKI_REGISTRY_INVALID", "message": "Wiki registry has no workspaces list"})
        return rows, problems
    for raw_ws in workspaces:
        if not isinstance(raw_ws, dict):
            problems.append({"code": "WIKI_WORKSPACE_INVALID", "message": "Wiki registry contains a non-object workspace"})
            continue
        if raw_ws.get("enabled", True) is False:
            continue
        workspace_id = str(raw_ws.get("id") or "").strip()
        if not workspace_id:
            problems.append({"code": "WIKI_WORKSPACE_ID_MISSING", "message": "Enabled Wiki workspace has no id"})
            continue
        project_name = str(raw_ws.get("display_name") or raw_ws.get("name") or workspace_id).strip()
        repos = raw_ws.get("repos")
        if not isinstance(repos, list):
            problems.append({"code": "WIKI_REPOS_INVALID", "message": f"Workspace {workspace_id} has no repos list"})
            continue
        for raw_repo in repos:
            if not isinstance(raw_repo, dict):
                problems.append({"code": "WIKI_REPO_INVALID", "message": f"Workspace {workspace_id} contains a non-object repo"})
                continue
            if raw_repo.get("enabled", True) is False:
                continue
            repo_id = str(raw_repo.get("id") or "").strip()
            if not repo_id:
                problems.append({"code": "WIKI_REPO_ID_MISSING", "message": f"Workspace {workspace_id} has an enabled repo without id"})
                continue
            group = str(raw_repo.get("group") or "").strip()
            wiki_repo_root = _repo_wiki_root(cfg, workspace_id, repo_id, group)
            if not _within(wiki_repo_root, wiki_root):
                problems.append({
                    "code": "WIKI_ROOT_ESCAPE",
                    "message": f"Registered Wiki root escapes system root: {workspace_id}/{repo_id}",
                })
                continue
            rows.append({
                "project_id": workspace_id,
                "project_name": project_name,
                "workspace_root": str(raw_ws.get("workspace_root") or ""),
                "repo_id": repo_id,
                "repo_root": str(raw_repo.get("repo_root") or ""),
                "group": group,
                "wiki_repo_root": wiki_repo_root,
                "source_id": source_id,
                "registry_repo": copy.deepcopy(raw_repo),
            })
    return rows, problems


def _safe_metadata_file(root: Path, relative: str) -> Optional[Path]:
    path = _canonical(root / relative)
    if not _within(path, root) or not path.is_file():
        return None
    return path


def _load_json_if_safe(root: Path, relative: str) -> Dict[str, Any]:
    path = _safe_metadata_file(root, relative)
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, UnicodeError, ValueError):
        return {}


def _doc_path(root: Path, relative: str) -> Optional[Path]:
    safe = _safe_relative(relative)
    if safe is None:
        return None
    path = _canonical(root / safe)
    if not _within(path, root) or not path.is_file():
        return None
    return path


def _document_signature(root: Path, relative: str) -> Tuple[str, bool, int, int]:
    safe = _safe_relative(relative)
    if safe is None:
        return ("", False, 0, 0)
    path = _canonical(root / safe)
    try:
        stat = path.stat()
        return (str(path), bool(path.is_file() and _within(path, root)), int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return (str(path), False, 0, 0)


def _first_heading(text: str) -> str:
    match = _HEADING_RE.search(text)
    return match.group(1).strip() if match else ""


def _catalog_for_target(target: Dict[str, Any]) -> Dict[str, Any]:
    root = _canonical(target["wiki_repo_root"])
    manifest_path = _safe_metadata_file(root, MANIFEST_NAME)
    cache_key = (str(target["source_id"]), f"{target['project_id']}/{target['repo_id']}")
    if manifest_path is None:
        return {
            "documents": [],
            "problems": [{"code": "WIKI_MANIFEST_MISSING", "message": f"Wiki manifest missing: {target['project_id']}/{target['repo_id']}"}],
            "maintenance": {"status": "missing", "updated_at": ""},
            "manifest_signature": ("", False, 0, 0),
            "document_signatures": {},
        }
    try:
        manifest_stat = manifest_path.stat()
        manifest_signature = (str(manifest_path), True, int(manifest_stat.st_mtime_ns), int(manifest_stat.st_size))
    except OSError:
        manifest_signature = (str(manifest_path), False, 0, 0)
    cached = _CATALOG_CACHE.get(cache_key)
    if cached and cached.get("manifest_signature") == manifest_signature:
        # Avoid reparsing large manifests on every page.  The cache remains
        # valid only while every allowlisted document's mtime/size and the
        # machine-owned maintenance receipts are unchanged.
        cached_docs = cached.get("document_signatures") or {}
        current_docs = {
            str(rel): _document_signature(root, str(rel)) for rel in cached_docs
        }
        cached_maintenance = cached.get("maintenance_signatures") or {}
        current_maintenance = {
            rel: _document_signature(root, rel) for rel in (
                "meta/wiki-snapshot.json", "meta/wiki-verification.json", "meta/wiki-coverage.json"
            )
        }
        if current_docs == cached_docs and current_maintenance == cached_maintenance:
            return copy.deepcopy(cached)
    try:
        loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
        raw = yaml.load(manifest_path.read_text(encoding="utf-8-sig"), Loader=loader) or {}
    except Exception as exc:
        return {
            "documents": [],
            "problems": [{"code": "WIKI_MANIFEST_INVALID", "message": f"Cannot parse Wiki manifest: {exc}"}],
            "maintenance": {"status": "invalid", "updated_at": ""},
            "manifest_signature": manifest_signature,
            "document_signatures": {},
        }
    if not isinstance(raw, dict) or raw.get("schema") not in {None, "tp-spec.wiki-manifest/v1"}:
        return {
            "documents": [],
            "problems": [{"code": "WIKI_MANIFEST_INVALID", "message": f"Unsupported Wiki manifest: {manifest_path}"}],
            "maintenance": {"status": "invalid", "updated_at": ""},
            "manifest_signature": manifest_signature,
            "document_signatures": {},
        }
    raw_docs = raw.get("documents")
    if not isinstance(raw_docs, list):
        return {
            "documents": [],
            "problems": [{"code": "WIKI_MANIFEST_INVALID", "message": f"Manifest documents must be a list: {manifest_path}"}],
            "maintenance": {"status": "invalid", "updated_at": ""},
            "manifest_signature": manifest_signature,
            "document_signatures": {},
        }
    rels = []
    for item in raw_docs:
        if isinstance(item, dict) and _safe_relative(item.get("path")):
            rels.append(_safe_relative(item.get("path")))
    doc_signatures = {str(rel): _document_signature(root, str(rel)) for rel in rels}
    documents: List[Dict[str, Any]] = []
    problems: List[Dict[str, str]] = []
    seen_paths: set[str] = set()
    seen_ids: set[str] = set()
    generated_at = str(raw.get("generated_at") or "")
    for item in raw_docs:
        if not isinstance(item, dict):
            problems.append({"code": "WIKI_DOCUMENT_INVALID", "message": f"Manifest contains a non-object document: {manifest_path}"})
            continue
        rel = _safe_relative(item.get("path"))
        if rel is None:
            problems.append({"code": "WIKI_DOCUMENT_PATH_INVALID", "message": f"Manifest document path is not a safe relative path: {item.get('path')!r}"})
            continue
        if rel in seen_paths:
            problems.append({"code": "WIKI_DOCUMENT_DUPLICATE", "message": f"Duplicate manifest document path: {rel}"})
            continue
        seen_paths.add(rel)
        path = _doc_path(root, rel)
        if path is None:
            problems.append({"code": "WIKI_DOCUMENT_UNREADABLE", "message": f"Manifest document is missing or escapes Wiki root: {rel}"})
            continue
        document_id = f"wiki:{target['project_id']}/{target['repo_id']}/{rel}"
        if document_id in seen_ids:
            problems.append({"code": "WIKI_DOCUMENT_DUPLICATE", "message": f"Duplicate document id: {document_id}"})
            continue
        seen_ids.add(document_id)
        try:
            text, data = _safe_read_text(path)
            stat = path.stat()
        except (OSError, UnicodeError) as exc:
            problems.append({"code": "WIKI_DOCUMENT_UNREADABLE", "message": f"Cannot read {rel}: {exc}"})
            continue
        file_hash = _sha256_bytes(data)
        updated_at = str(item.get("updated_at") or generated_at or _iso_from_mtime(stat.st_mtime))
        documents.append({
            "id": document_id,
            "source_id": target["source_id"],
            "project_id": target["project_id"],
            "project_name": target["project_name"],
            "repo_id": target["repo_id"],
            "path": rel,
            "title": str(item.get("title") or _first_heading(text) or Path(rel).stem),
            "type": str(item.get("type") or "content-doc"),
            "status": str(item.get("status") or ""),
            "updated_at": updated_at,
            "content_hash": file_hash,
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "_file_path": str(path),
            "_wiki_repo_root": str(root),
            "_relative_path": rel,
            "_content": text,
            "_manifest_content_hash": str(item.get("content_hash") or ""),
        })
    snapshot = _load_json_if_safe(root, "meta/wiki-snapshot.json")
    verification = _load_json_if_safe(root, "meta/wiki-verification.json")
    coverage = _load_json_if_safe(root, "meta/wiki-coverage.json")
    completion = snapshot.get("completion") if isinstance(snapshot.get("completion"), dict) else {}
    verification_result = str(verification.get("result") or verification.get("status") or "")
    maintenance_status = verification_result or str(completion.get("result") or "") or ("available" if snapshot else "unknown")
    maintenance_updated = str(completion.get("completed_at") or snapshot.get("generated_at") or generated_at or "")
    maintenance = {
        "status": maintenance_status,
        "updated_at": maintenance_updated,
        "generated_at": generated_at,
        "snapshot_id": str(snapshot.get("snapshot_id") or ""),
        "verification_result": verification_result,
        "verification_updated_at": str(verification.get("generated_at") or verification.get("verified_at") or ""),
        "coverage": coverage.get("summary") if isinstance(coverage.get("summary"), dict) else {},
    }
    maintenance_signatures = {
        rel: _document_signature(root, rel) for rel in (
            "meta/wiki-snapshot.json", "meta/wiki-verification.json", "meta/wiki-coverage.json"
        )
    }
    result = {
        "documents": documents,
        "problems": problems,
        "maintenance": maintenance,
        "manifest_signature": manifest_signature,
        "document_signatures": doc_signatures,
        "maintenance_signatures": maintenance_signatures,
    }
    _CATALOG_CACHE[cache_key] = copy.deepcopy(result)
    return result


def _catalog(cfg: Any) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, str]], List[Dict[str, Any]]]:
    try:
        registry = load_registry(cfg)
    except Exception as exc:
        return "", [], [{"code": "WIKI_REGISTRY_INVALID", "message": str(exc)}], []
    if not registry.get("workspaces"):
        return "", [], [{"code": "WIKI_REGISTRY_MISSING", "message": f"Wiki registry has no registered workspaces: {cfg.paths.wiki_registry}"}], []
    source_id = _source_id(cfg, registry)
    targets, problems = _target_rows(cfg, registry, source_id)
    docs: List[Dict[str, Any]] = []
    repo_rows: List[Dict[str, Any]] = []
    for target in targets:
        catalog = _catalog_for_target(target)
        problems.extend(catalog["problems"])
        docs.extend(catalog["documents"])
        maintenance = catalog["maintenance"]
        repo_rows.append({
            "project_id": target["project_id"],
            "repo_id": target["repo_id"],
            "repo_root": target["repo_root"],
            "wiki_repo_root": str(target["wiki_repo_root"]),
            "source_id": source_id,
            "group": target["group"],
            "document_count": len(catalog["documents"]),
            "updated_at": maintenance.get("updated_at") or maintenance.get("generated_at") or "",
            "status": maintenance.get("status") or "unknown",
            "maintenance": maintenance,
            "_registry_repo": target.get("registry_repo") or {},
        })
    return source_id, docs, problems, repo_rows


def _public_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {key: doc.get(key, "") for key in (
        "id", "project_id", "repo_id", "path", "title", "type", "status", "updated_at", "content_hash"
    )}


def _catalog_fingerprint(source_id: str, docs: Iterable[Dict[str, Any]], repos: Iterable[Dict[str, Any]], problems: Iterable[Dict[str, str]]) -> str:
    payload = {
        "source_id": source_id,
        "repositories": [
            {"project_id": row.get("project_id"), "repo_id": row.get("repo_id"), "document_count": row.get("document_count"),
             "status": row.get("status"), "updated_at": row.get("updated_at"), "registry": row.get("_registry_repo") or {}}
            for row in repos
        ],
        "documents": [
            {"id": row.get("id"), "content_hash": row.get("content_hash"), "size": row.get("size"), "mtime_ns": row.get("mtime_ns"),
             "title": row.get("title"), "type": row.get("type"), "status": row.get("status"), "updated_at": row.get("updated_at")}
            for row in docs
        ],
        "problems": list(problems),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def inventory(cfg: Any) -> Dict[str, Any]:
    """Return the registered Wiki catalog without reading arbitrary paths."""
    source_id, docs, problems, repos = _catalog(cfg)
    project_map: Dict[str, Dict[str, Any]] = {}
    for repo in repos:
        pid = str(repo.get("project_id") or "")
        if pid and pid not in project_map:
            project_map[pid] = {"id": pid, "name": pid}
    # Preserve registry display names from target cache when available.
    try:
        registry = load_registry(cfg)
        for ws in registry.get("workspaces", []) or []:
            if isinstance(ws, dict) and ws.get("id") and ws.get("enabled", True) is not False:
                pid = str(ws["id"])
                project_map[pid] = {"id": pid, "name": str(ws.get("display_name") or ws.get("name") or pid)}
    except Exception:
        pass
    return {
        "source_id": source_id,
        "projects": sorted(project_map.values(), key=lambda row: str(row["id"])),
        "repositories": [{key: value for key, value in row.items() if not key.startswith("_")} for row in repos],
        "documents": [_public_document(doc) for doc in docs],
        "problems": problems,
    }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS wiki_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wiki_documents (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    repo_id TEXT NOT NULL,
    path TEXT NOT NULL,
    title TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    mtime_ns INTEGER NOT NULL DEFAULT 0,
    content TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS wiki_documents_fts USING fts5(
    doc_id UNINDEXED,
    title,
    heading,
    path,
    body,
    tokenize='unicode61'
);
CREATE TABLE IF NOT EXISTS wiki_telemetry (
    receipt_id TEXT PRIMARY KEY,
    request_id TEXT UNIQUE,
    payload_hash TEXT NOT NULL,
    operation TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT '',
    repo_id TEXT NOT NULL DEFAULT '',
    task_id TEXT NOT NULL DEFAULT '',
    actor_role TEXT NOT NULL DEFAULT '',
    query TEXT NOT NULL DEFAULT '',
    query_hash TEXT NOT NULL DEFAULT '',
    result_count INTEGER NOT NULL DEFAULT 0,
    results_json TEXT NOT NULL DEFAULT '[]',
    elapsed_ms REAL NOT NULL DEFAULT 0,
    error_code TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_wiki_telemetry_created ON wiki_telemetry(created_at);
"""


def _open_rw(cfg: Any, *, source_id: str = "") -> sqlite3.Connection:
    path = retrieval_db_path(cfg, source_id=source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def _open_ro(cfg: Any, *, source_id: str = "") -> Optional[sqlite3.Connection]:
    path = retrieval_db_path(cfg, source_id=source_id)
    if not path.is_file():
        return None
    # mode=ro is necessary for page calls: SELECT must not create a DB or a
    # journal when the user has not explicitly asked for telemetry/indexing.
    uri = "file:" + quote(str(path), safe="/:\\") + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=3.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def _set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute("INSERT OR REPLACE INTO wiki_meta(key,value) VALUES(?,?)", (key, str(value)))


def _get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM wiki_meta WHERE key=?", (key,)).fetchone()
    return str(row[0]) if row else default


def _headings(text: str) -> str:
    return "\n".join(match.group(1).strip() for match in _HEADING_RE.finditer(text))


def _fts_query(query: str) -> str:
    tokens = [token for token in _knowledge_tokenize(query).split() if token]
    if not tokens:
        raise RetrievalError("query must contain searchable Chinese or English terms")
    seen: set[str] = set()
    escaped: List[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        escaped.append('"' + token.replace('"', '""') + '"')
    # A multi-term query is an intersection.  OR-ing every Chinese character
    # makes an almost arbitrary single-character hit appear relevant and
    # prevents a useful two-term query from proving zero results.
    return " AND ".join(escaped)


def _make_snippet(content: str, query: str, maximum: int = 200) -> str:
    """Return a bounded snippet; the ellipsis counts toward the budget."""
    maximum = max(1, int(maximum))
    text = re.sub(r"\s+", " ", content or "").strip()
    if len(text) <= maximum:
        return text
    if maximum == 1:
        return "…"
    terms = [term for term in _knowledge_tokenize(query).split() if term]
    position = -1
    lower = text.casefold()
    for term in terms:
        position = lower.find(term.casefold())
        if position >= 0:
            break
    if position < 0:
        return text[: maximum - 1].rstrip() + "…"
    budget = maximum - 1
    start = max(0, position - budget // 3)
    end = min(len(text), start + budget)
    prefix = "…" if start else ""
    suffix = "…" if end < len(text) else ""
    # If both sides need markers, reserve space for both.  The returned value
    # is always <= maximum, including its ellipsis characters.
    marker_count = int(bool(prefix)) + int(bool(suffix))
    body_budget = max(0, maximum - marker_count)
    body = text[start:end].strip()
    if len(body) > body_budget:
        body = body[:body_budget].rstrip()
    return prefix + body + suffix


_FRONTMATTER_END_RE = re.compile(r"^(?:---|\.\.\.)\s*$")
_FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
_OUTLINE_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")


def _frontmatter_body_start(lines: List[str]) -> int:
    """Return the first body line after a complete YAML frontmatter block."""
    if not lines:
        return 0
    first = lines[0].lstrip("\ufeff").rstrip("\r\n")
    if first.strip() != "---":
        return 0
    for index in range(1, len(lines)):
        if _FRONTMATTER_END_RE.match(lines[index].rstrip("\r\n")):
            return index + 1
    # An unmatched leading '---' is ordinary Markdown, not frontmatter.
    return 0


def _build_outline(lines: List[str], body_start: int, *, max_items: int = 20, max_chars: int = 1000) -> Tuple[List[Dict[str, Any]], bool]:
    """Extract bounded headings outside frontmatter and fenced code blocks."""
    outline: List[Dict[str, Any]] = []
    used_chars = 0
    truncated = False
    fence_char = ""
    fence_length = 0
    for index in range(body_start, len(lines)):
        raw = lines[index].rstrip("\r\n")
        fence = _FENCE_RE.match(raw)
        if fence_char:
            if (fence and fence.group(2)[0] == fence_char and len(fence.group(2)) >= fence_length
                    and not fence.group(3).strip()):
                fence_char = ""
                fence_length = 0
            continue
        if fence:
            fence_char = fence.group(2)[0]
            fence_length = len(fence.group(2))
            continue
        match = _OUTLINE_HEADING_RE.match(raw)
        if not match:
            continue
        title = match.group(2).strip()
        if not title:
            continue
        if len(outline) >= max_items or used_chars >= max_chars:
            truncated = True
            continue
        remaining = max_chars - used_chars
        if len(title) > remaining:
            if remaining == 1:
                title = "…"
            else:
                title = title[:remaining - 1].rstrip() + "…"
            truncated = True
        outline.append({"level": len(match.group(1)), "title": title, "line": index + 1})
        used_chars += len(title)
        if used_chars >= max_chars and index + 1 < len(lines):
            # The next heading, if any, will make this explicit below; leave
            # the flag false until another heading is actually observed.
            continue
    return outline, truncated


def _build_preview(lines: List[str], body_start: int, *, max_lines: int = 80, max_chars: int = 4000) -> Dict[str, Any]:
    """Select complete original body lines under the preview budget."""
    first_body = next((index for index in range(body_start, len(lines)) if lines[index].strip()), None)
    if first_body is None:
        return {
            "content": "", "line_start": None, "line_end": None, "truncated": False,
            "next_start_line": None, "warnings": [], "body_nonempty": False,
        }
    if len(lines[first_body]) > max_chars:
        line = first_body + 1
        warning = (
            f"首个正文行 {line} 超过 {max_chars} 字符，预览未跳过该行；请使用 "
            f"--start-line {line} --end-line {line} 或 --full 读取。"
        )
        return {
            "content": "", "line_start": None, "line_end": None, "truncated": True,
            "next_start_line": line, "warnings": [warning], "body_nonempty": True,
        }
    selected: List[str] = []
    used_chars = 0
    index = body_start
    truncated = False
    next_start_line: Optional[int] = None
    while index < len(lines) and len(selected) < max_lines:
        line = lines[index]
        if used_chars + len(line) > max_chars:
            truncated = True
            next_start_line = index + 1
            break
        selected.append(line)
        used_chars += len(line)
        index += 1
    if index < len(lines) and not truncated:
        truncated = True
        next_start_line = index + 1
    content = "".join(selected)
    nonempty_selected = bool(content.strip())
    return {
        "content": content,
        "line_start": (body_start + 1) if selected else None,
        "line_end": (body_start + len(selected)) if selected else None,
        "truncated": truncated,
        "next_start_line": next_start_line,
        "warnings": [],
        "body_nonempty": nonempty_selected or True,
    }


def _resolved_current_project(cfg: Any, registry: Dict[str, Any]) -> str:
    current = _canonical(cfg.paths.workspace_root)
    matches = []
    for ws in registry.get("workspaces", []) or []:
        if not isinstance(ws, dict) or ws.get("enabled", True) is False:
            continue
        raw = str(ws.get("workspace_root") or "").strip()
        if raw and _canonical(raw) == current:
            matches.append(str(ws.get("id") or "").strip())
    if len(matches) > 1:
        raise RetrievalError(f"multiple Wiki registry workspaces match current workspace: {cfg.paths.workspace_root}")
    return matches[0] if matches else ""


def _normalize_scope(scope: str) -> str:
    value = str(scope or "").strip().lower()
    if value in {"all", "global"}:
        return "all"
    return "current"


def _telemetry_payload_hash(payload: Dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _redact_payload(value: Any, *, key: str = "") -> Any:
    """Redact query-bearing payload values before writing JSON telemetry."""
    if isinstance(value, dict):
        return {str(k): _redact_payload(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_payload(item, key=key) for item in value]
    if key.casefold() in {"query", "q", "search_query"}:
        return _redact_query(value)
    return value


def _write_telemetry(
    *, cfg: Any, operation: str, status: str, payload: Dict[str, Any], project_id: str = "", repo_id: str = "",
    task_id: str = "", actor_role: str = "", query: str = "", result_count: int = 0,
    results: Optional[List[Dict[str, Any]]] = None, elapsed_ms: float = 0.0, error_code: str = "",
    request_id: str = "",
) -> str:
    if operation not in {"search", "read"}:
        raise RetrievalError("telemetry operation must be search or read")
    if status not in {"completed", "failed"}:
        raise RetrievalError("telemetry status must be completed or failed")
    conn = _open_rw(cfg, source_id=_source_id_for_cfg(cfg))
    try:
        payload_hash = _telemetry_payload_hash(payload)
        request = str(request_id or "").strip() or None
        cutoff = (_now() - timedelta(days=TELEMETRY_RETENTION_DAYS)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        conn.execute("DELETE FROM wiki_telemetry WHERE created_at < ?", (cutoff,))
        conn.commit()
        if request:
            old = conn.execute(
                "SELECT receipt_id,payload_hash FROM wiki_telemetry WHERE request_id=?", (request,)
            ).fetchone()
            if old:
                if str(old["payload_hash"]) != payload_hash:
                    raise _TelemetryConflict("REQUEST_ID_CONFLICT: request_id was used with a different payload")
                return str(old["receipt_id"])
        receipt_id = "wiki-" + uuid.uuid4().hex
        redacted = _redact_query(query)
        safe_payload = _redact_payload(payload)
        conn.execute(
            """INSERT INTO wiki_telemetry(
                receipt_id,request_id,payload_hash,operation,status,created_at,project_id,repo_id,
                task_id,actor_role,query,query_hash,result_count,results_json,elapsed_ms,error_code,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                receipt_id, request, payload_hash, operation, status, _now_iso(), str(project_id or ""),
                str(repo_id or ""), str(task_id or ""), str(actor_role or ""), redacted, _query_hash(query),
                int(result_count or 0), json.dumps(results or [], ensure_ascii=False, sort_keys=True),
                float(elapsed_ms or 0.0), str(error_code or ""), json.dumps(safe_payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        if not _get_meta(conn, "first_collected_at"):
            _set_meta(conn, "first_collected_at", _now_iso())
        conn.commit()
        return receipt_id
    finally:
        conn.close()


def _record_best_effort(**kwargs: Any) -> Tuple[Optional[str], Optional[str]]:
    try:
        return _write_telemetry(**kwargs), None
    except _TelemetryConflict:
        return None, "REQUEST_ID_CONFLICT"
    except Exception as exc:
        # A locked/unavailable telemetry DB must never turn a successful page
        # retrieval into a correctness failure.
        return None, f"TELEMETRY_UNAVAILABLE:{type(exc).__name__}"


def build_index(cfg: Any) -> Dict[str, Any]:
    """Build the user-root FTS5 projection from all enabled registered repos."""
    started = time.perf_counter()
    source_id, docs, problems, repos = _catalog(cfg)
    catalog_fingerprint = _catalog_fingerprint(source_id, docs, repos, problems)
    try:
        conn = _open_rw(cfg, source_id=source_id)
    except Exception as exc:
        return {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}", "source_id": source_id, "document_count": 0}
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM wiki_documents_fts")
        conn.execute("DELETE FROM wiki_documents")
        for doc in docs:
            conn.execute(
                """INSERT INTO wiki_documents(id,source_id,project_id,repo_id,path,title,type,status,updated_at,content_hash,size,mtime_ns,content)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    doc["id"], source_id, doc["project_id"], doc["repo_id"], doc["path"], doc["title"],
                    doc["type"], doc["status"], doc["updated_at"], doc["content_hash"], doc["size"],
                    doc["mtime_ns"], doc.get("_content") or "",
                ),
            )
            conn.execute(
                "INSERT INTO wiki_documents_fts(doc_id,title,heading,path,body) VALUES(?,?,?,?,?)",
                (
                    doc["id"], _knowledge_tokenize(doc["title"]), _knowledge_tokenize(_headings(doc.get("_content") or "")),
                    _knowledge_tokenize(doc["path"]), _knowledge_tokenize(doc.get("_content") or ""),
                ),
            )
        indexed_at = _now_iso()
        _set_meta(conn, "source_id", source_id)
        _set_meta(conn, "indexed_at", indexed_at)
        _set_meta(conn, "document_count", len(docs))
        _set_meta(conn, "repository_count", len(repos))
        _set_meta(conn, "problem_count", len(problems))
        _set_meta(conn, "catalog_fingerprint", catalog_fingerprint)
        _set_meta(conn, "schema", "tp-spec.wiki-retrieval/v1")
        conn.commit()
    except Exception as exc:
        conn.rollback()
        return {
            "status": "FAIL",
            "source_id": source_id,
            "document_count": 0,
            "repository_count": len(repos),
            "error": f"{type(exc).__name__}: {exc}",
            "database": str(retrieval_db_path(cfg, source_id=source_id)),
        }
    finally:
        conn.close()
    return {
        "status": "PASS" if not problems else "WARN",
        "source_id": source_id,
        "indexed_at": indexed_at,
        "document_count": len(docs),
        "repository_count": len(repos),
        "problems": problems,
        "catalog_fingerprint": catalog_fingerprint,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "database": str(retrieval_db_path(cfg, source_id=source_id)),
    }


def update_index(cfg: Any) -> Dict[str, Any]:
    """Refresh the rebuildable projection after a successful Wiki commit."""
    result = build_index(cfg)
    result["operation"] = "update"
    return result


def index_status(cfg: Any) -> Dict[str, Any]:
    """Read projection metadata without creating or changing the database."""
    source_id, current_docs, current_problems, current_repos = _catalog(cfg)
    path = retrieval_db_path(cfg, source_id=source_id)
    conn = _open_ro(cfg, source_id=source_id)
    if conn is None:
        return {"status": "MISSING", "database": str(path), "indexed_at": "", "source_id": source_id, "document_count": 0}
    try:
        try:
            schema = _get_meta(conn, "schema")
            if not schema:
                return {"status": "WARN", "database": str(path), "indexed_at": "", "source_id": source_id, "document_count": 0, "error": "metadata missing"}
            current_fingerprint = _catalog_fingerprint(source_id, current_docs, current_repos, current_problems)
            indexed_fingerprint = _get_meta(conn, "catalog_fingerprint")
            indexed_source = _get_meta(conn, "source_id")
            stale = bool(indexed_source != source_id or not indexed_fingerprint or indexed_fingerprint != current_fingerprint)
            return {
                "status": "STALE" if stale else ("WARN" if current_problems else "PASS"),
                "database": str(path),
                "schema": schema,
                "indexed_at": _get_meta(conn, "indexed_at"),
                "source_id": indexed_source,
                "document_count": int(_get_meta(conn, "document_count", "0") or 0),
                "repository_count": int(_get_meta(conn, "repository_count", "0") or 0),
                "problem_count": int(_get_meta(conn, "problem_count", "0") or 0),
                "catalog_fingerprint": indexed_fingerprint,
                "current_catalog_fingerprint": current_fingerprint,
            }
        except sqlite3.Error as exc:
            return {"status": "WARN", "database": str(path), "indexed_at": "", "source_id": "", "document_count": 0, "error": str(exc)}
    finally:
        conn.close()


def search(
    cfg: Any,
    query: str,
    project: str = "",
    repo: str = "",
    kind: str = "",
    limit: int = MAX_RESULTS,
    record_telemetry: bool = False,
    task_id: str = "",
    actor_role: str = "",
    request_id: str = "",
    offset: int = 0,
    scope: str = "",
) -> Dict[str, Any]:
    """Search unique registered Wiki documents with bounded result pages."""
    started = time.perf_counter()
    query = str(query or "")
    explicit_project = str(project or "").strip()
    explicit_repo = str(repo or "").strip()
    normalized_scope = _normalize_scope(scope)
    if explicit_project in {"*", "all"}:
        normalized_scope = "all"
        explicit_project = ""
    try:
        page_limit = max(1, min(int(limit or MAX_RESULTS), MAX_RESULTS))
    except (TypeError, ValueError):
        page_limit = MAX_RESULTS
        limit_error = "INVALID_LIMIT"
    else:
        limit_error = ""
    try:
        page_offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        page_offset = 0
        offset_error = "INVALID_OFFSET"
    else:
        offset_error = ""
    payload = {
        "query": query,
        "project": explicit_project,
        "repo": explicit_repo,
        "kind": str(kind or "").strip(),
        "scope": normalized_scope,
        "offset": page_offset,
        "limit": page_limit,
        "task_id": str(task_id or ""),
        "actor_role": str(actor_role or ""),
    }
    def failed(code: str, message: str, *, project_id: str = "") -> Dict[str, Any]:
        receipt: Optional[str] = None
        telemetry_error: Optional[str] = None
        if record_telemetry:
            receipt, telemetry_error = _record_best_effort(
                cfg=cfg, operation="search", status="failed", payload=payload, project_id=project_id,
                repo_id=explicit_repo, task_id=task_id, actor_role=actor_role, query=query, result_count=0,
                elapsed_ms=(time.perf_counter() - started) * 1000, error_code=code, request_id=request_id,
            )
        result: Dict[str, Any] = {
            "status": "failed", "error": code, "message": message, "results": [], "count": 0,
            "total": 0, "returned": 0, "offset": page_offset, "limit": page_limit, "receipt_id": receipt,
            "index": index_status(cfg), "scope": normalized_scope,
        }
        if project_id:
            result["project_id"] = project_id
        if telemetry_error:
            result["telemetry_error"] = telemetry_error
        return result

    if limit_error:
        return failed(limit_error, "limit must be an integer")
    if offset_error:
        return failed(offset_error, "offset must be an integer")
    try:
        fts_query = _fts_query(query)
    except Exception as exc:
        return failed("INVALID_QUERY", str(exc), project_id=explicit_project)

    # Validate scopes and explicit filters against the registered catalog
    # before touching the index.  Invalid filters are execution failures, not
    # successful zero-hit searches and must be visible as such in telemetry.
    source_id, catalog_docs, catalog_problems, catalog_repos = _catalog(cfg)
    project_filter = explicit_project
    if not project_filter and normalized_scope == "current":
        try:
            registry = load_registry(cfg)
            project_filter = _resolved_current_project(cfg, registry)
        except Exception as exc:
            return failed("CURRENT_SCOPE_UNRESOLVED", str(exc))
        if not project_filter:
            return failed("CURRENT_SCOPE_UNRESOLVED", "current workspace is not registered in the Wiki registry")
    valid_projects = {str(row.get("project_id") or "") for row in catalog_repos}
    if explicit_project and explicit_project not in valid_projects:
        return failed("INVALID_PROJECT", f"project is not registered: {explicit_project}", project_id=explicit_project)
    relevant_repos = [row for row in catalog_repos if not project_filter or project_filter in {"*", "all"} or row.get("project_id") == project_filter]
    if explicit_repo and not any(str(row.get("repo_id") or "") == explicit_repo for row in relevant_repos):
        return failed("INVALID_REPO", f"repo is not registered in the requested scope: {explicit_repo}", project_id=project_filter)
    relevant_docs = [row for row in catalog_docs if (not project_filter or project_filter in {"*", "all"} or row.get("project_id") == project_filter)
                     and (not explicit_repo or row.get("repo_id") == explicit_repo)]
    kind_value = str(kind or "").strip()
    if kind_value and not any(str(row.get("type") or "") == kind_value for row in relevant_docs):
        return failed("INVALID_KIND", f"kind is not present in the requested scope: {kind_value}", project_id=project_filter)

    # Never search an unbuilt or stale projection.  A telemetry-only database
    # can exist after an index-missing request, and an old FTS row can still
    # contain a document removed from the current manifest allowlist.
    current_index = index_status(cfg)
    if current_index.get("status") == "MISSING" or not current_index.get("indexed_at"):
        result = failed("INDEX_MISSING", "Wiki retrieval index is not built", project_id=project_filter)
        result["index"] = current_index
        return result
    if current_index.get("status") == "STALE":
        result = failed("INDEX_STALE", "Wiki retrieval index is stale; run wiki index update", project_id=project_filter)
        result["index"] = current_index
        return result

    source_id = _source_id_for_cfg(cfg)
    conn = _open_ro(cfg, source_id=source_id)
    if conn is None:
        result = failed("INDEX_MISSING", "Wiki retrieval index is not built", project_id=project_filter)
        result["index"] = current_index
        return result
    telemetry_error: Optional[str] = None
    try:
        # source_id was resolved from the same current registry used above;
        # ``_open_ro`` therefore cannot accidentally read another source's DB.
        if not project_filter and normalized_scope == "all":
            project_filter = ""
        conditions = ["f.wiki_documents_fts MATCH ?"]
        values: List[Any] = [fts_query]
        if project_filter and project_filter not in {"*", "all"}:
            conditions.append("d.project_id = ?")
            values.append(project_filter)
        if explicit_repo:
            conditions.append("d.repo_id = ?")
            values.append(explicit_repo)
        if kind_value:
            conditions.append("d.type = ?")
            values.append(kind_value)
        where = " AND ".join(conditions)
        total_row = conn.execute(
            f"SELECT COUNT(DISTINCT d.id) FROM wiki_documents_fts f JOIN wiki_documents d ON d.id=f.doc_id WHERE {where}",
            values,
        ).fetchone()
        total = int(total_row[0] or 0)
        rows = conn.execute(
            f"""SELECT d.id,d.project_id,d.repo_id,d.path,d.title,d.type,d.status,d.updated_at,d.content_hash,d.content,
                       bm25(wiki_documents_fts,0.0,10.0,7.0,5.0,1.0) AS rank
                FROM wiki_documents_fts f JOIN wiki_documents d ON d.id=f.doc_id
                WHERE {where}
                ORDER BY rank ASC, d.title COLLATE NOCASE ASC, d.path COLLATE NOCASE ASC
                LIMIT ? OFFSET ?""",
            values + [page_limit, page_offset],
        ).fetchall()
        results: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            doc_id = str(row["id"])
            if doc_id in seen:
                continue
            seen.add(doc_id)
            results.append({
                "id": doc_id,
                "project_id": str(row["project_id"]),
                "repo_id": str(row["repo_id"]),
                "path": str(row["path"]),
                "title": str(row["title"]),
                "type": str(row["type"]),
                "status": str(row["status"]),
                "updated_at": str(row["updated_at"]),
                "content_hash": str(row["content_hash"]),
                "snippet": _make_snippet(str(row["content"]), query),
                "score": round(float(-row["rank"]), 8) if row["rank"] is not None else 0.0,
            })
        receipt: Optional[str] = None
        if record_telemetry:
            receipt, telemetry_error = _record_best_effort(
                cfg=cfg, operation="search", status="completed", payload=payload, project_id=project_filter,
                repo_id=explicit_repo, task_id=task_id, actor_role=actor_role, query=query, result_count=len(results),
                results=[{"id": row["id"], "content_hash": row["content_hash"]} for row in results],
                elapsed_ms=(time.perf_counter() - started) * 1000, request_id=request_id,
            )
        result = {
            "status": "completed", "results": results, "count": total, "total": total, "returned": len(results),
            "offset": page_offset, "limit": page_limit, "receipt_id": receipt, "index": current_index,
            "scope": normalized_scope,
        }
        if project_filter:
            result["project_id"] = project_filter
        if telemetry_error:
            result["telemetry_error"] = telemetry_error
        return result
    except sqlite3.Error as exc:
        return failed("SEARCH_FAILED", str(exc), project_id=project_filter)
    finally:
        conn.close()


def read_document(
    cfg: Any,
    document_id: str,
    record_telemetry: bool = False,
    task_id: str = "",
    actor_role: str = "",
    request_id: str = "",
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    full: Optional[bool] = None,
) -> Dict[str, Any]:
    """Read a manifest-known document, optionally using a bounded preview.

    ``full=None`` preserves the historical library behavior: full text unless
    an explicit line range is supplied.  Callers such as the CLI pass
    ``full=False`` explicitly for the preview contract.
    """
    started = time.perf_counter()
    identifier = str(document_id or "").strip()
    has_range = start_line is not None or end_line is not None
    read_mode = "range" if has_range else ("preview" if full is False else "full")
    payload = {
        "document_id": identifier,
        "start_line": start_line,
        "end_line": end_line,
        "full": full,
        "read_mode": read_mode,
        "task_id": str(task_id or ""),
        "actor_role": str(actor_role or ""),
    }
    telemetry_error: Optional[str] = None
    try:
        _, docs, _, _ = _catalog(cfg)
        doc = next((row for row in docs if row["id"] == identifier), None)
        if doc is None:
            raise RetrievalError(f"document is not registered in a Wiki manifest: {identifier}")
        # The first check above is against the registered catalog.  Re-check
        # the original registered repo root and relative path before reading,
        # so a symlink replacement fails closed instead of turning the stored
        # absolute path into a new authority.
        path = _doc_path(Path(doc["_wiki_repo_root"]), doc["_relative_path"])
        if path is None:
            raise RetrievalError(f"registered document is no longer safely readable: {identifier}")
        text, data = _safe_read_text(path)
        current_hash = _sha256_bytes(data)
        original_lines = text.splitlines(keepends=True)
        lines = text.splitlines()
        body_start = _frontmatter_body_start(original_lines)
        outline: List[Dict[str, Any]] = []
        outline_truncated = False
        warnings: List[str] = []
        next_start_line: Optional[int] = None
        truncated = False
        body_nonempty = any(line.strip() for line in original_lines[body_start:])
        selected_body_nonempty = body_nonempty
        if has_range:
            selected = text
            first = 1 if start_line is None else int(start_line)
            last = len(lines) if end_line is None else int(end_line)
            if first < 1 or last < first or last > len(lines):
                raise RetrievalError("line range must satisfy 1 <= start_line <= end_line <= document line count")
            selected = "\n".join(lines[first - 1:last])
            selected_start, selected_end = first, last
            selected_body_nonempty = any(
                lines[index].strip() for index in range(first - 1, last) if index >= body_start
            )
            # Explicit ranges preserve the old exact-body semantics and omit
            # the outline to avoid spending tokens on an already targeted read.
            read_mode = "range"
        elif read_mode == "preview":
            preview = _build_preview(original_lines, body_start)
            selected = str(preview["content"])
            selected_start = preview["line_start"]
            selected_end = preview["line_end"]
            truncated = bool(preview["truncated"])
            next_start_line = preview["next_start_line"]
            warnings = list(preview["warnings"])
            outline, outline_truncated = _build_outline(original_lines, body_start)
            # A preview must never silently count a long-line/empty response as
            # a successful read.  The caller receives the directory and the
            # explicit line-range recommendation instead.
        else:
            selected = text
            selected_start = 1 if lines else None
            selected_end = len(lines) if lines else None
            outline, outline_truncated = _build_outline(original_lines, body_start)
        metadata = _public_document({**doc, "content_hash": current_hash})
        receipt = None
        # Only a returned non-empty body/preview is a successful read.  A
        # frontmatter-only document and an overlong first preview line return
        # metadata/outline without writing a success event.
        readable_content = bool(selected.strip()) and selected_body_nonempty
        if record_telemetry and readable_content:
            receipt, telemetry_error = _record_best_effort(
                cfg=cfg, operation="read", status="completed", payload=payload, project_id=doc["project_id"],
                repo_id=doc["repo_id"], task_id=task_id, actor_role=actor_role, query=identifier,
                result_count=1, results=[{"id": identifier, "content_hash": current_hash}],
                elapsed_ms=(time.perf_counter() - started) * 1000, request_id=request_id,
            )
        result: Dict[str, Any] = {
            "document": metadata, "content": selected, "receipt_id": receipt,
            "line_count": len(lines), "line_start": selected_start, "line_end": selected_end,
            "read_mode": read_mode, "outline": outline, "outline_truncated": outline_truncated,
            "truncated": truncated, "next_start_line": next_start_line,
            "warnings": warnings, "warning": warnings[0] if warnings else None,
        }
        if readable_content:
            result["status"] = "completed"
        elif read_mode == "preview" and warnings:
            result["status"] = "preview_unavailable"
        else:
            result["status"] = "empty"
        if telemetry_error:
            result["telemetry_error"] = telemetry_error
        return result
    except Exception as exc:
        if record_telemetry:
            receipt, write_error = _record_best_effort(
                cfg=cfg, operation="read", status="failed", payload=payload, project_id="", repo_id="",
                task_id=task_id, actor_role=actor_role, query=identifier, result_count=0,
                elapsed_ms=(time.perf_counter() - started) * 1000, error_code="READ_FAILED", request_id=request_id,
            )
            telemetry_error = write_error
        result = {"document": None, "content": "", "receipt_id": receipt if record_telemetry else None, "error": f"{type(exc).__name__}: {exc}"}
        if telemetry_error:
            result["telemetry_error"] = telemetry_error
        return result


def telemetry(cfg: Any, days: int = 30) -> Dict[str, Any]:
    """Read usage telemetry without cleaning or otherwise mutating it."""
    try:
        window_days = max(1, int(days or 30))
    except (TypeError, ValueError):
        window_days = 30
    cutoff = (_now() - timedelta(days=window_days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    source_id = _source_id_for_cfg(cfg)
    conn = _open_ro(cfg, source_id=source_id)
    if conn is None:
        status = "unavailable" if retrieval_db_path(cfg, source_id=source_id).is_file() else "not_collected"
        return {"status": status, "started_at": "", "retention_days": TELEMETRY_RETENTION_DAYS, "events": []}
    try:
        try:
            first_collected_at = _get_meta(conn, "first_collected_at")
            rows = conn.execute(
                """SELECT receipt_id,operation,status,created_at,project_id,task_id,actor_role,query,
                          result_count,results_json,elapsed_ms,error_code,repo_id,payload_json
                   FROM wiki_telemetry WHERE created_at >= ? ORDER BY created_at ASC, receipt_id ASC""",
                (cutoff,),
            ).fetchall()
        except sqlite3.Error:
            return {"status": "unavailable", "started_at": "", "retention_days": TELEMETRY_RETENTION_DAYS, "events": []}
        events: List[Dict[str, Any]] = []
        for row in rows:
            try:
                event_results = json.loads(str(row["results_json"] or "[]"))
                if not isinstance(event_results, list):
                    event_results = []
            except ValueError:
                event_results = []
            event: Dict[str, Any] = {
                "receipt_id": str(row["receipt_id"]),
                "operation": str(row["operation"]),
                "status": str(row["status"]),
                "created_at": str(row["created_at"]),
                "project_id": str(row["project_id"]),
                "task_id": str(row["task_id"]),
                "actor_role": str(row["actor_role"]),
                "query": str(row["query"]),
                "result_count": int(row["result_count"] or 0),
                "results": event_results,
                "elapsed_ms": float(row["elapsed_ms"] or 0.0),
            }
            if row["repo_id"]:
                event["repo_id"] = str(row["repo_id"])
            if row["error_code"]:
                event["error_code"] = str(row["error_code"])
            try:
                payload = json.loads(str(row["payload_json"] or "{}"))
                if isinstance(payload, dict):
                    for key in ("scope", "kind", "offset", "limit"):
                        if key in payload:
                            event[key] = payload[key]
            except ValueError:
                pass
            events.append(event)
        return {
            "status": "available" if first_collected_at else "not_collected",
            "started_at": first_collected_at,
            "retention_days": TELEMETRY_RETENTION_DAYS,
            "events": events,
        }
    finally:
        conn.close()


__all__ = [
    "RetrievalError", "build_index", "index_status", "inventory", "read_document", "retrieval_db_path",
    "search", "telemetry", "update_index",
]
