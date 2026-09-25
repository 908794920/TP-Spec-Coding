"""Hashed, append-only Knowledge usage receipts in the existing projection database.

Only ``upgrade`` (called by explicit index operations) changes schema. Search/read
writers use mode=rw and never initialize/migrate a database. UI callers use mode=ro.
No query text, snippets or document bodies are persisted here.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator
import uuid

from .common import now_iso, stable_hash

CONTRACT = "tp-spec.knowledge-usage/v2"
PURPOSES = {"development", "delivery_convergence", "maintenance", "unknown"}
CALLERS = {"ai_cli", "task_convergence", "unknown"}
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
SEARCH_COLUMNS = {
    "receipt_id": "TEXT", "request_id": "TEXT", "request_fingerprint": "TEXT",
    "task_id": "TEXT", "actor_role": "TEXT", "purpose": "TEXT", "caller": "TEXT",
    "request_scope": "TEXT", "requested_project": "TEXT", "requested_projects": "TEXT",
    "returned_projects": "TEXT", "status": "TEXT", "error_code": "TEXT",
    "document_count": "INTEGER", "results_json": "TEXT", "contract_version": "INTEGER",
    "scope_fingerprint": "TEXT", "count_kind": "TEXT", "has_canonical": "INTEGER", "has_source": "INTEGER",
}
READ_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_reads (
 id INTEGER PRIMARY KEY AUTOINCREMENT, receipt_id TEXT NOT NULL UNIQUE,
 request_id TEXT NOT NULL UNIQUE, request_fingerprint TEXT NOT NULL,
 task_id TEXT, actor_role TEXT, purpose TEXT NOT NULL, caller TEXT NOT NULL,
 request_scope TEXT NOT NULL, requested_project TEXT, requested_projects TEXT NOT NULL,
 returned_projects TEXT NOT NULL, status TEXT NOT NULL, error_code TEXT,
 document_key TEXT NOT NULL, read_mode TEXT NOT NULL, line_start INTEGER, line_end INTEGER,
 body_returned INTEGER NOT NULL, results_json TEXT NOT NULL,
 elapsed_ms REAL NOT NULL, contract_version INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS knowledge_reads_time ON knowledge_reads(created_at);
"""


class KnowledgeError(ValueError):
    """A fixed public code, never an exception containing query/body text."""
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@contextmanager
def connect_readonly(db: Path) -> Iterator[sqlite3.Connection]:
    # mode=ro is important: _connect's CREATE/PRAGMA path must not be used by GET.
    if not db.is_file():
        raise KnowledgeError("KNOWLEDGE_INDEX_MISSING")
    conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")
        yield conn
    finally:
        conn.close()


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    # table is a constant selected by the program, never a user SQL identifier.
    if table not in {"retrieval_runs", "knowledge_reads", "documents", "build_meta"}:
        raise ValueError("unsupported schema inspection")
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def ready(conn: sqlite3.Connection) -> bool:
    return set(SEARCH_COLUMNS).issubset(columns(conn, "retrieval_runs")) and bool(columns(conn, "knowledge_reads"))


def upgrade(conn: sqlite3.Connection, cfg) -> None:
    """Append nullable columns without inventing identities for historical rows."""
    existing = columns(conn, "retrieval_runs")
    for name, definition in SEARCH_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE retrieval_runs ADD COLUMN {name} {definition}")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS knowledge_search_request ON retrieval_runs(request_id) WHERE request_id IS NOT NULL")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS knowledge_search_receipt ON retrieval_runs(receipt_id) WHERE receipt_id IS NOT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS knowledge_search_time ON retrieval_runs(created_at)")
    # executescript commits implicitly; individual statements keep the caller's upgrade atomic.
    for statement in READ_SCHEMA.split(";"):
        if statement.strip():
            conn.execute(statement)
    for key, value in {
        "usage_contract": CONTRACT,
        "usage_started_at": now_iso(),
        "usage_upgrade_retention_days": str(retention_days(cfg)),
    }.items():
        conn.execute("INSERT OR IGNORE INTO build_meta(key,value) VALUES(?,?)", (key, value))


def retention_days(cfg) -> int:
    return int(cfg.knowledge_retrieval.get("telemetry_retention_days") or 90)


def request_context(*, request_id=None, task_id=None, actor_role=None,
                    purpose="unknown", caller="unknown") -> dict[str, Any]:
    if purpose not in PURPOSES or caller not in CALLERS:
        raise KnowledgeError("KNOWLEDGE_INVALID_CALL_CONTEXT")
    values = {"request_id": request_id or uuid.uuid4().hex,
              "task_id": task_id or "", "actor_role": actor_role or ""}
    if any(value and (not isinstance(value, str) or not IDENTIFIER.fullmatch(value)) for value in values.values()):
        raise KnowledgeError("KNOWLEDGE_INVALID_CALL_CONTEXT")
    return {**values, "purpose": purpose, "caller": caller}


def fingerprint(operation: str, request: dict) -> str:
    return stable_hash({"operation": operation, **request})


def _existing(conn, request_id):
    for table in ("retrieval_runs", "knowledge_reads"):
        row = conn.execute(f"SELECT * FROM {table} WHERE request_id=?", (request_id,)).fetchone()
        if row:
            return dict(row)
    return None


def check_request(cfg, request: dict, digest: str, *, enabled: bool) -> None:
    """Reject a changed request before reading/searching when a receipt exists."""
    if not enabled or not cfg.knowledge_retrieval.get("telemetry", True):
        return
    try:
        with connect_readonly(cfg.paths.knowledge_projection_db) as conn:
            if ready(conn):
                row = _existing(conn, request["request_id"])
                if row and row["request_fingerprint"] != digest:
                    raise KnowledgeError("KNOWLEDGE_REQUEST_CONFLICT")
    except KnowledgeError as exc:
        if exc.code == "KNOWLEDGE_REQUEST_CONFLICT":
            raise
    except (sqlite3.Error, OSError):
        pass  # The actual result will carry a collection warning if persistence fails.


def result_identity(row: dict) -> dict:
    """Whitelisted receipt fields; candidates may additionally have a body snippet."""
    names = ("document_key", "id", "path", "title", "project", "layer", "version",
             "version_kind", "content_hash", "line_start", "line_end")
    return {name: row[name] for name in names if name in row}


def _receipt(row, *, replay=False):
    return {"schema": CONTRACT, "receipt_id": row["receipt_id"], "request_id": row["request_id"],
            "status": row["status"], "created_at": row["created_at"], "replayed": replay,
            "query_hash_only": True}


def record(cfg, operation: str, request: dict, digest: str, *, status="completed", results=(),
           elapsed_ms=0.0, query_hash="", fallback_reason="", count_kind="documents",
           candidate_count=None, error_code="", read_mode="", line_start=None, line_end=None,
           body_returned=False, document_key="", enabled=True) -> dict:
    if not enabled or not cfg.knowledge_retrieval.get("telemetry", True):
        return {"collection_status": "disabled", "receipt": None}
    db = cfg.paths.knowledge_projection_db
    conn = None
    try:
        if not db.is_file():
            return {"collection_status": "missing", "receipt": None,
                    "collection_warning": "KNOWLEDGE_INDEX_MISSING_USAGE_NOT_RECORDED"}
        conn = sqlite3.connect(db.resolve().as_uri() + "?mode=rw", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        if not ready(conn):
            return {"collection_status": "legacy", "receipt": None,
                    "collection_warning": "KNOWLEDGE_USAGE_UPGRADE_REQUIRED"}
        conn.execute("BEGIN IMMEDIATE")
        old = _existing(conn, request["request_id"])
        clean_results = [result_identity(dict(row)) for row in results]
        # Versions on a retry must not claim the old receipt when the actual output changed.
        encoded = json.dumps(clean_results, ensure_ascii=False, sort_keys=True)
        if old:
            if old["request_fingerprint"] != digest:
                raise KnowledgeError("KNOWLEDGE_REQUEST_CONFLICT")
            if old["status"] != status or old["results_json"] != encoded:
                raise KnowledgeError("KNOWLEDGE_RETRY_RESULT_CHANGED")
            return {"collection_status": "available", "receipt": _receipt(old, replay=True)}
        actual_projects = sorted({str(row.get("project") or "") for row in clean_results if row.get("project")})
        common = {"receipt_id": "knowledge-" + uuid.uuid4().hex, "request_id": request["request_id"],
                  "request_fingerprint": digest, "task_id": request.get("task_id") or None,
                  "actor_role": request.get("actor_role") or None, "purpose": request["purpose"],
                  "caller": request["caller"], "request_scope": request.get("scope", "project"),
                  "requested_project": request.get("project") or None,
                  "requested_projects": json.dumps(request.get("projects", []), ensure_ascii=False),
                  "returned_projects": json.dumps(actual_projects, ensure_ascii=False), "status": status,
                  "error_code": error_code or None, "results_json": encoded,
                  "elapsed_ms": round(elapsed_ms, 3), "contract_version": 2, "created_at": now_iso()}
        if operation == "search":
            canonical = any(row.get("layer") == "canonical" for row in results)
            source = any(row.get("layer") == "source" for row in results)
            common.update(query_hash=query_hash,
                scope_fingerprint=stable_hash({name: request.get(name) for name in ("scope", "project", "projects", "kind", "layer", "limit", "offset", "include_shared", "source_fallback", "global_fallback", "count_kind")}),
                retrieval_mode="canonical-first-fts5:" + request.get("scope", "project"),
                fallback_reason=fallback_reason, candidate_count=len(clean_results) if candidate_count is None else candidate_count,
                answerability="failed" if status != "completed" else "hit" if clean_results else "no_result",
                layer="mixed" if canonical and source else "canonical" if canonical else "source" if source else "",
                document_count=len({row.get("document_key") or (row.get("layer"), row.get("path")) for row in clean_results}),
                count_kind=count_kind, has_canonical=int(canonical), has_source=int(source))
            table = "retrieval_runs"
        elif operation == "read":
            common.update(document_key=document_key if re.fullmatch(r"knowledge:[a-f0-9]{24}:[a-f0-9]{64}", document_key) else "", read_mode=read_mode, line_start=line_start,
                          line_end=line_end, body_returned=int(body_returned))
            table = "knowledge_reads"
        else:
            raise ValueError("unsupported Knowledge usage operation")
        names = list(common)
        conn.execute(f"INSERT INTO {table}({','.join(names)}) VALUES({','.join('?' for _ in names)})", list(common.values()))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days(cfg))).isoformat()
        for target in ("retrieval_runs", "knowledge_reads"):
            conn.execute(f"DELETE FROM {target} WHERE julianday(created_at) < julianday(?)", (cutoff,))
        conn.execute("INSERT OR REPLACE INTO build_meta(key,value) VALUES('usage_retention_days',?)", (str(retention_days(cfg)),))
        previous = conn.execute("SELECT value FROM build_meta WHERE key='usage_pruned_before'").fetchone()
        if not previous or datetime.fromisoformat(previous[0]) < datetime.fromisoformat(cutoff):
            conn.execute("INSERT OR REPLACE INTO build_meta(key,value) VALUES('usage_pruned_before',?)", (cutoff,))
        conn.commit()
        return {"collection_status": "available", "receipt": _receipt(common)}
    except KnowledgeError:
        raise
    except (sqlite3.Error, OSError, ValueError):
        # Failure to collect never converts a valid content result into an execution failure.
        return {"collection_status": "unavailable", "receipt": None,
                "collection_warning": "KNOWLEDGE_USAGE_WRITE_FAILED"}
    finally:
        if conn is not None:
            conn.close()


def query_hash(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()
