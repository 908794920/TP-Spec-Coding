# -*- coding: utf-8 -*-
"""Rebuildable Knowledge retrieval projection (SQLite FTS5 + optional graph)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import hashlib
import json
import math
import os
import re
import sqlite3
import time
import warnings

from . import telemetry
from .documents import document_key, public_document, query_documents, resolve_scope

from .common import collect_notes, load_source_registry, now_iso, stable_hash, resolve_knowledge_project, meta_paths, read_jsonl

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
MAX_CHUNK_LINES = 60
MIN_CHUNK_LINES = 3


def tokenize(text: str) -> str:
    if not text:
        return ""
    tokens: List[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if CJK_RE.match(ch):
            j = i
            while j < len(text) and CJK_RE.match(text[j]):
                j += 1
            run = text[i:j]
            tokens.extend(run)
            tokens.extend(run[k:k+2] for k in range(len(run)-1))
            i = j
        elif ch.isascii() and (ch.isalnum() or ch in "_./-:"):
            j = i
            while j < len(text) and text[j].isascii() and (text[j].isalnum() or text[j] in "_./-:"):
                j += 1
            tok = text[i:j].rstrip("./-:")
            if tok:
                tokens.append(tok.lower())
            i = max(j, i + 1)
        else:
            i += 1
    return " ".join(tokens)


def tokenize_query(query: str) -> Optional[str]:
    if not query or not query.strip():
        return None
    parts = tokenize(query).split()
    if not parts:
        safe = query.replace('"', '""')
        return f'"{safe}"'
    seen: set[str] = set(); unique: List[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p); unique.append(p)
    return " OR ".join(f'"{p}"' for p in unique)


def chunk_markdown(body: str, body_start_line: int = 1) -> List[Dict[str, Any]]:
    lines = body.splitlines(keepends=True)
    chunks: List[Dict[str, Any]] = []
    headings: List[str] = []
    current: List[str] = []
    current_start = body_start_line
    current_heading = ""

    def flush(end_line: int) -> None:
        nonlocal current, current_start, current_heading
        if not current:
            return
        content = "".join(current)
        chunks.append({
            "heading_path": current_heading,
            "line_start": current_start,
            "line_end": max(current_start, end_line),
            "content": content,
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        })
        current = []

    for idx, line in enumerate(lines):
        line_no = body_start_line + idx
        m = HEADING_RE.match(line.rstrip("\r\n"))
        if m:
            if current:
                flush(line_no - 1)
            level = len(m.group(1)); title = m.group(2).strip()
            headings = headings[:level-1]
            while len(headings) < level-1:
                headings.append("")
            headings.append(title)
            current_heading = " > ".join(h for h in headings if h)
            current_start = line_no
            current = [line]
            continue
        if not current:
            current_start = line_no
            current_heading = " > ".join(h for h in headings if h)
        current.append(line)
        if len(current) >= MAX_CHUNK_LINES:
            flush(line_no)
            current_start = line_no + 1
    if current:
        flush(body_start_line + max(0, len(lines)-1))

    merged: List[Dict[str, Any]] = []
    for ch in chunks:
        if merged and ch["line_end"] - ch["line_start"] + 1 < MIN_CHUNK_LINES:
            prev = merged[-1]
            prev["line_end"] = ch["line_end"]
            prev["content"] += ch["content"]
            prev["content_hash"] = hashlib.sha256(prev["content"].encode("utf-8")).hexdigest()
        else:
            merged.append(ch)
    return merged


CORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
 id INTEGER PRIMARY KEY AUTOINCREMENT, rel_path TEXT UNIQUE NOT NULL,
 scope TEXT NOT NULL, project TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT '',
 canonical_id TEXT NOT NULL DEFAULT '', source_id TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',
 sha256 TEXT NOT NULL, size INTEGER NOT NULL DEFAULT 0, mtime_ns INTEGER NOT NULL DEFAULT 0,
 source_refs TEXT NOT NULL DEFAULT '[]', freshness TEXT NOT NULL DEFAULT '', indexed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chunks (
 id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER NOT NULL, chunk_idx INTEGER NOT NULL,
 heading_path TEXT NOT NULL DEFAULT '', line_start INTEGER NOT NULL, line_end INTEGER NOT NULL,
 content TEXT NOT NULL, content_hash TEXT NOT NULL,
 FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS build_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS doc_links (
 id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER NOT NULL, link_type TEXT NOT NULL,
 target_id TEXT NOT NULL, FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE);
CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
 tokenized_content, heading_path, project, kind, scope, tokenize='unicode61');
CREATE TABLE IF NOT EXISTS graph_nodes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, canonical_id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
 title TEXT NOT NULL DEFAULT '', project TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
 layer TEXT NOT NULL DEFAULT '', rel_path TEXT NOT NULL DEFAULT '', source_refs TEXT NOT NULL DEFAULT '[]',
 confidence REAL NOT NULL DEFAULT 0, last_verified TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS graph_edges (
 id INTEGER PRIMARY KEY AUTOINCREMENT, edge_id TEXT UNIQUE NOT NULL,
 source_canonical_id TEXT NOT NULL, target_id TEXT NOT NULL, relation_type TEXT NOT NULL,
 direction TEXT NOT NULL DEFAULT 'forward', evidence_source_ids TEXT NOT NULL DEFAULT '[]',
 confidence REAL NOT NULL DEFAULT 0, origin TEXT NOT NULL DEFAULT 'canonical', reason TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'active');
CREATE TABLE IF NOT EXISTS chunk_embeddings (
 id INTEGER PRIMARY KEY AUTOINCREMENT, chunk_id INTEGER NOT NULL, content_hash TEXT NOT NULL,
 chunker_version TEXT NOT NULL, embedding_model TEXT NOT NULL, model_served TEXT NOT NULL DEFAULT '',
 dim INTEGER NOT NULL, vector BLOB NOT NULL, normalized INTEGER NOT NULL DEFAULT 1,
 server_revision TEXT NOT NULL DEFAULT '', config_hash TEXT NOT NULL, created_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'active', UNIQUE(chunk_id, config_hash));
CREATE TABLE IF NOT EXISTS model_metadata (
 id INTEGER PRIMARY KEY AUTOINCREMENT, service TEXT NOT NULL, model_requested TEXT NOT NULL,
 model_served TEXT NOT NULL DEFAULT '', dim INTEGER, server_revision TEXT NOT NULL DEFAULT '',
 config_hash TEXT NOT NULL, doctor_status TEXT NOT NULL, probed_at TEXT NOT NULL,
 capabilities_path TEXT NOT NULL, UNIQUE(service, config_hash));
CREATE TABLE IF NOT EXISTS retrieval_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, query_hash TEXT NOT NULL, retrieval_mode TEXT NOT NULL,
 fallback_reason TEXT NOT NULL DEFAULT '', model_config_hash TEXT NOT NULL DEFAULT '',
 candidate_count INTEGER NOT NULL DEFAULT 0, fts_score REAL, vector_score REAL, rerank_score REAL,
 answerability TEXT NOT NULL DEFAULT 'unknown', layer TEXT NOT NULL DEFAULT '', elapsed_ms REAL NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL);
"""


def _connect(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(CORE_SCHEMA)
    return conn



def upgrade_projection_schema(conn, cfg):
    """Explicit index build/update only; preserve all historical usage rows."""
    fields = telemetry.columns(conn, "documents")
    if "document_key" not in fields:
        conn.execute("ALTER TABLE documents ADD COLUMN document_key TEXT")
    if "metadata_json" not in fields:
        conn.execute("ALTER TABLE documents ADD COLUMN metadata_json TEXT")
    for row in conn.execute("SELECT id,scope,canonical_id,rel_path FROM documents").fetchall():
        conn.execute("UPDATE documents SET document_key=? WHERE id=?", (document_key(cfg, row[1], row[2], row[3]), row[0]))
    conn.execute("CREATE INDEX IF NOT EXISTS knowledge_document_key ON documents(document_key)")
    telemetry.upgrade(conn, cfg)


def _note_metadata(note):
    fm = note.get("frontmatter") or {}
    # Only explicitly recorded maintenance facts. Missing is unknown, not healthy.
    return {"metadata_version": 1, "evidence_refs": fm.get("evidence_refs") or [],
            **{key: fm[key] for key in ("status", "superseded", "replaced_by", "relations", "last_verified", "expires_at") if key in fm}}


def _registered_sources(conn, cfg, notes):
    """Index metadata for registered, unconverted originals, without opening them.

    Converted Markdown already has its own source document. A source_id can name
    several files; the synthetic relative locator includes batch + origin path.
    """
    from .documents import scopes, registered_conversion_path
    from .common import read_note
    known = {note["rel_path"]: note for note in notes}
    registered = {row["id"] for row in scopes(cfg)}
    conn.execute("DELETE FROM fts_chunks WHERE rowid IN (SELECT c.id FROM chunks c JOIN documents d ON c.doc_id=d.id WHERE substr(d.rel_path,1,11)='@converted/')")
    conn.execute("DELETE FROM documents WHERE substr(rel_path,1,12)='@registered/' OR substr(rel_path,1,11)='@converted/'")
    for record in read_jsonl(meta_paths(cfg)["source_registry"]):
        project, origin = str(record.get("project") or ""), str(record.get("origin_path") or "")
        if project not in registered or not origin:
            continue
        converted = str(record.get("conversion_path") or record.get("content_path") or "").replace("\\", "/")
        origin_meta = {k: record[k] for k in ("source_id", "origin_path", "batch", "sha256", "disposition") if k in record}
        if converted in known:
            note = known[converted]
            metadata = {**_note_metadata(note), "origin": origin_meta, "conversion": converted}
            conn.execute("UPDATE documents SET metadata_json=? WHERE rel_path=?", (json.dumps(metadata, ensure_ascii=False), converted))
            continue
        # Ingest conversions are already registered outputs, not a request for
        # conversion. Keep them in the existing source/chunk index with a stable
        # virtual locator; reading rechecks the live registration and boundary.
        if record.get("conversion_status") == "converted" and record.get("disposition") not in {"quarantined", "excluded"}:
            try:
                path = registered_conversion_path(cfg, record)
                note = read_note(path, root=path.parent, scope="source")
                relative = "@converted/" + stable_hash([record.get("batch"), origin, project])
                note.update(rel_path=relative, project=project, kind="source", id=str(record.get("source_id") or ""),
                            title=note.get("title") or Path(origin).name)
                _insert_doc(conn, note, {}, cfg)
                metadata = {**_note_metadata(note), "origin": origin_meta, "conversion": converted,
                            "registered_conversion": {name: record.get(name) for name in ("project", "batch", "origin_path")}}
                conn.execute("UPDATE documents SET metadata_json=? WHERE rel_path=?", (json.dumps(metadata, ensure_ascii=False), relative))
                continue
            except (ValueError, OSError, RuntimeError):
                pass  # Preserve registered original metadata when its output is unavailable.
        relative = "@registered/" + stable_hash([record.get("batch"), origin, project])
        metadata = {"metadata_only": True, "origin": origin_meta,
                    "conversion": converted or None, "status": record.get("disposition"),
                    "updated_at": record.get("updated_at") or record.get("registered_at")}
        conn.execute("""INSERT OR REPLACE INTO documents(rel_path,scope,project,kind,source_id,title,sha256,indexed_at,document_key,metadata_json)
                        VALUES(?,'source',?,'source',?,?,?,?,?,?)""",
                     (relative, project, str(record.get("source_id") or ""), Path(origin).name,
                      str(record.get("sha256") or ""), now_iso(), document_key(cfg, "source", "", relative),
                      json.dumps(metadata, ensure_ascii=False)))


def _source_id(note: Dict[str, Any], source_registry: Dict[str, Dict[str, Any]]) -> str:
    if note.get("id"):
        return str(note["id"])
    for sid, rec in source_registry.items():
        if str(rec.get("content_path") or "").replace("\\", "/") == note["rel_path"]:
            return sid
    return ""


def _insert_doc(conn: sqlite3.Connection, note: Dict[str, Any], source_registry: Dict[str, Dict[str, Any]], cfg=None) -> None:
    source_id = _source_id(note, source_registry) if note["scope"] == "source" else ""
    canonical_id = str(note.get("id") or "") if note["scope"] == "canonical" else ""
    freshness = datetime.fromtimestamp(note["mtime_ns"] / 1e9, timezone.utc).strftime("%Y-%m-%d")
    cur = conn.execute(
        """INSERT INTO documents(rel_path,scope,project,kind,canonical_id,source_id,title,sha256,size,mtime_ns,source_refs,freshness,indexed_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (note["rel_path"], note["scope"], note["project"], note["kind"], canonical_id, source_id,
         note["title"], note["sha256"], note["size"], note["mtime_ns"],
         json.dumps(note.get("source_refs") or [], ensure_ascii=False), freshness, now_iso()),
    )
    doc_id = int(cur.lastrowid)
    if cfg is not None and "document_key" in telemetry.columns(conn, "documents"):
        conn.execute("UPDATE documents SET document_key=?,metadata_json=? WHERE id=?",
                     (document_key(cfg, note["scope"], canonical_id, note["rel_path"]),
                      json.dumps(_note_metadata(note), ensure_ascii=False), doc_id))
    for ref in note.get("source_refs") or []:
        conn.execute("INSERT INTO doc_links(doc_id,link_type,target_id) VALUES(?,?,?)", (doc_id, "source_ref", str(ref)))
    for idx, ch in enumerate(chunk_markdown(note["body"], note["body_start_line"])):
        c = conn.execute(
            "INSERT INTO chunks(doc_id,chunk_idx,heading_path,line_start,line_end,content,content_hash) VALUES(?,?,?,?,?,?,?)",
            (doc_id, idx, ch["heading_path"], ch["line_start"], ch["line_end"], ch["content"], ch["content_hash"]),
        )
        chunk_id = int(c.lastrowid)
        tokenized = tokenize(ch["content"] + " " + ch["heading_path"] + " " + note["title"] + " " + canonical_id + " " + source_id + " " + note["rel_path"])
        conn.execute("INSERT INTO fts_chunks(rowid,tokenized_content,heading_path,project,kind,scope) VALUES(?,?,?,?,?,?)",
                     (chunk_id, tokenized, ch["heading_path"], note["project"], note["kind"], note["scope"]))


def _rebuild_graph(conn: sqlite3.Connection, canonical: List[Dict[str, Any]], mode: str) -> None:
    conn.execute("DELETE FROM graph_edges"); conn.execute("DELETE FROM graph_nodes")
    if mode == "disabled":
        return
    for n in canonical:
        fm = n.get("frontmatter") or {}
        cid = str(fm.get("id") or "")
        if not cid:
            continue
        conf = fm.get("confidence", 0)
        try: conf = float(conf)
        except Exception: conf = 0.0
        conn.execute("""INSERT OR REPLACE INTO graph_nodes(canonical_id,kind,title,project,status,layer,rel_path,source_refs,confidence,last_verified)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""",
                     (cid, str(fm.get("kind") or ""), str(fm.get("title") or ""), str(fm.get("project") or ""),
                      str(fm.get("status") or "active"), "canonical", n["rel_path"],
                      json.dumps(fm.get("source_refs") or [], ensure_ascii=False), conf, str(fm.get("last_verified") or "")))
    for n in canonical:
        fm = n.get("frontmatter") or {}; cid = str(fm.get("id") or "")
        if not cid: continue
        refs = [str(x) for x in fm.get("source_refs") or []]
        for rel in fm.get("relations") or []:
            if not isinstance(rel, dict) or not rel.get("type") or not rel.get("target"): continue
            rtype, target = str(rel["type"]), str(rel["target"])
            edge_id = "E-" + hashlib.sha256(f"{cid}|{rtype}|{target}".encode()).hexdigest()[:24]
            conn.execute("""INSERT OR REPLACE INTO graph_edges(edge_id,source_canonical_id,target_id,relation_type,evidence_source_ids,origin,reason)
                            VALUES(?,?,?,?,?,?,?)""",
                         (edge_id, cid, target, rtype, json.dumps(refs, ensure_ascii=False), "canonical", str(rel.get("note") or "")))
        for ref in refs:
            edge_id = "E-" + hashlib.sha256(f"{cid}|source_refs|{ref}".encode()).hexdigest()[:24]
            conn.execute("""INSERT OR REPLACE INTO graph_edges(edge_id,source_canonical_id,target_id,relation_type,evidence_source_ids,origin)
                            VALUES(?,?,?,?,?,?)""", (edge_id, cid, ref, "source_refs", json.dumps([ref], ensure_ascii=False), "canonical"))


def build_projection(cfg, *, clean: bool = True) -> Dict[str, Any]:
    root = cfg.paths.knowledge_physical_root; db = cfg.paths.knowledge_projection_db
    canonical, sources = collect_notes(root, cfg); registry = load_source_registry(cfg)
    conn = _connect(db)
    conn.execute("BEGIN")
    upgrade_projection_schema(conn, cfg)
    if clean:
        # Preserve telemetry and retired-compatible model tables; all active retrieval projections are rebuilt.
        conn.execute("DELETE FROM fts_chunks"); conn.execute("DELETE FROM doc_links"); conn.execute("DELETE FROM chunks"); conn.execute("DELETE FROM documents")
    for n in canonical + sources:
        _insert_doc(conn, n, registry, cfg)
    _registered_sources(conn, cfg, canonical + sources)
    _rebuild_graph(conn, canonical, str(cfg.knowledge_projection.get("graph_mode") or "optional"))
    subject = stable_hash({n["rel_path"]: n["sha256"] for n in canonical + sources})
    meta = {
        "projection_schema": "tp-spec.knowledge-projection/v1",
        "projection_subject": subject,
        "build_at": now_iso(),
        "build_doc_count": str(conn.execute("SELECT count(*) FROM documents").fetchone()[0]),
        "build_chunk_count": str(conn.execute("SELECT count(*) FROM chunks").fetchone()[0]),
        "vector_state": str(cfg.knowledge_projection.get("vector_mode") or "retired-compatible"),
        "retrieval_authority": str(cfg.knowledge_retrieval.get("strategy") or "canonical-first-fts5"),
    }
    for k, v in meta.items(): conn.execute("INSERT OR REPLACE INTO build_meta(key,value) VALUES(?,?)", (k, str(v)))
    conn.commit()
    result = projection_status(cfg, conn=conn)
    conn.close()
    return result



def update_canonical_note_projection(cfg, note: Dict[str, Any]) -> Dict[str, Any]:
    """只增量索引一条精确 canonical note，不扫描整个 Knowledge vault。"""
    if note.get("scope") != "canonical" or not str(note.get("id") or "").strip():
        raise ValueError("exact Knowledge index requires one canonical note with stable id")
    db = cfg.paths.knowledge_projection_db
    if not db.is_file():
        raise ValueError("knowledge projection database missing; run knowledge index build")
    registry = load_source_registry(cfg)
    conn = _connect(db)
    try:
        canonical_id = str(note["id"])
        rel_path = str(note["rel_path"])
        old_rows = conn.execute(
            "SELECT id,rel_path FROM documents WHERE rel_path=? OR (scope='canonical' AND canonical_id=?)",
            (rel_path, canonical_id),
        ).fetchall()
        for old_id, old_rel in old_rows:
            old_rel = str(old_rel)
            if old_rel != rel_path and (cfg.paths.knowledge_physical_root / old_rel).is_file():
                raise ValueError(f"canonical id already exists at another live path: {canonical_id}")
            doc_id = int(old_id)
            chunk_ids = [int(r[0]) for r in conn.execute("SELECT id FROM chunks WHERE doc_id=?", (doc_id,)).fetchall()]
            for chunk_id in chunk_ids:
                conn.execute("DELETE FROM fts_chunks WHERE rowid=?", (chunk_id,))
            conn.execute("DELETE FROM doc_links WHERE doc_id=?", (doc_id,))
            conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
            conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        _insert_doc(conn, note, registry, cfg)

        if str(cfg.knowledge_projection.get("graph_mode") or "optional") != "disabled":
            fm = note.get("frontmatter") or {}
            confidence = fm.get("confidence", 0)
            try:
                confidence = float(confidence)
            except Exception:
                confidence = 0.0
            conn.execute(
                """INSERT OR REPLACE INTO graph_nodes(canonical_id,kind,title,project,status,layer,rel_path,source_refs,confidence,last_verified)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (canonical_id, str(fm.get("kind") or ""), str(fm.get("title") or ""), str(fm.get("project") or ""),
                 str(fm.get("status") or "active"), "canonical", rel_path,
                 json.dumps(fm.get("source_refs") or [], ensure_ascii=False), confidence, str(fm.get("last_verified") or "")),
            )
            conn.execute("DELETE FROM graph_edges WHERE source_canonical_id=?", (canonical_id,))
            refs = [str(x) for x in fm.get("source_refs") or []]
            for rel in fm.get("relations") or []:
                if not isinstance(rel, dict) or not rel.get("type") or not rel.get("target"):
                    continue
                rtype, target = str(rel["type"]), str(rel["target"])
                edge_id = "E-" + hashlib.sha256(f"{canonical_id}|{rtype}|{target}".encode()).hexdigest()[:24]
                conn.execute(
                    """INSERT OR REPLACE INTO graph_edges(edge_id,source_canonical_id,target_id,relation_type,evidence_source_ids,origin,reason)
                       VALUES(?,?,?,?,?,?,?)""",
                    (edge_id, canonical_id, target, rtype, json.dumps(refs, ensure_ascii=False), "canonical", str(rel.get("note") or "")),
                )
            for ref in refs:
                edge_id = "E-" + hashlib.sha256(f"{canonical_id}|source_refs|{ref}".encode()).hexdigest()[:24]
                conn.execute(
                    """INSERT OR REPLACE INTO graph_edges(edge_id,source_canonical_id,target_id,relation_type,evidence_source_ids,origin)
                       VALUES(?,?,?,?,?,?)""",
                    (edge_id, canonical_id, ref, "source_refs", json.dumps([ref], ensure_ascii=False), "canonical"),
                )

        subject = stable_hash({str(r[0]): str(r[1]) for r in conn.execute("SELECT rel_path,sha256 FROM documents WHERE substr(rel_path,1,1) != '@' ORDER BY rel_path")})
        conn.execute("INSERT OR REPLACE INTO build_meta(key,value) VALUES('projection_subject',?)", (subject,))
        conn.execute("INSERT OR REPLACE INTO build_meta(key,value) VALUES('last_update',?)", (now_iso(),))
        conn.execute("INSERT OR REPLACE INTO build_meta(key,value) VALUES('build_doc_count',?)", (str(conn.execute("SELECT count(*) FROM documents").fetchone()[0]),))
        conn.execute("INSERT OR REPLACE INTO build_meta(key,value) VALUES('build_chunk_count',?)", (str(conn.execute("SELECT count(*) FROM chunks").fetchone()[0]),))
        conn.commit()
        return {
            "schema": "tp-spec.knowledge-index-exact/v1",
            "status": "PASS",
            "canonical_id": canonical_id,
            "path": rel_path,
            "sha256": str(note.get("sha256") or ""),
        }
    finally:
        conn.close()

def update_projection(cfg) -> Dict[str, Any]:
    db = cfg.paths.knowledge_projection_db
    if not db.is_file():
        return build_projection(cfg, clean=True)
    root = cfg.paths.knowledge_physical_root; canonical, sources = collect_notes(root, cfg); notes = canonical + sources
    current = {n["rel_path"]: n for n in notes}; registry = load_source_registry(cfg)
    conn = _connect(db)
    conn.execute("BEGIN")
    upgrade_projection_schema(conn, cfg)
    old = {r[0]: (int(r[1]), r[2]) for r in conn.execute("SELECT rel_path,id,sha256 FROM documents WHERE substr(rel_path,1,1) != '@'")}
    removed = set(old) - set(current)
    changed = [n for p,n in current.items() if p not in old or old[p][1] != n["sha256"]]
    for rel in removed | {n["rel_path"] for n in changed if n["rel_path"] in old}:
        doc_id = old[rel][0]
        for (cid,) in conn.execute("SELECT id FROM chunks WHERE doc_id=?", (doc_id,)).fetchall():
            conn.execute("DELETE FROM fts_chunks WHERE rowid=?", (cid,))
        conn.execute("DELETE FROM doc_links WHERE doc_id=?", (doc_id,)); conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,)); conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    for n in changed: _insert_doc(conn, n, registry, cfg)
    for n in notes:
        conn.execute("UPDATE documents SET metadata_json=? WHERE rel_path=?", (json.dumps(_note_metadata(n), ensure_ascii=False), n["rel_path"]))
    _registered_sources(conn, cfg, notes)
    _rebuild_graph(conn, canonical, str(cfg.knowledge_projection.get("graph_mode") or "optional"))
    subject = stable_hash({n["rel_path"]: n["sha256"] for n in notes})
    conn.execute("INSERT OR REPLACE INTO build_meta(key,value) VALUES('projection_subject',?)", (subject,))
    conn.execute("INSERT OR REPLACE INTO build_meta(key,value) VALUES('last_update',?)", (now_iso(),))
    conn.execute("INSERT OR REPLACE INTO build_meta(key,value) VALUES('retrieval_authority',?)", (str(cfg.knowledge_retrieval.get("strategy") or "canonical-first-fts5"),))
    conn.execute("INSERT OR REPLACE INTO build_meta(key,value) VALUES('vector_state',?)", (str(cfg.knowledge_projection.get("vector_mode") or "retired-compatible"),))
    conn.commit(); result = projection_status(cfg, conn=conn); result["delta"]={"added_or_modified":len(changed),"deleted":len(removed)}; conn.close(); return result


def projection_status(cfg, *, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    db = cfg.paths.knowledge_projection_db
    own = conn is None
    if not db.is_file() and own:
        return {"status":"MISSING","database":str(db),"fresh":False,"issues":["projection database missing"]}
    if own: conn = _connect(db)
    assert conn is not None
    issues: List[str] = []
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok": issues.append(f"integrity_check: {integrity}")
    canonical, sources = collect_notes(cfg.paths.knowledge_physical_root, cfg)
    current_subject = stable_hash({n["rel_path"]: n["sha256"] for n in canonical + sources})
    row = conn.execute("SELECT value FROM build_meta WHERE key='projection_subject'").fetchone(); stored = row[0] if row else ""
    fresh = bool(stored and stored == current_subject)
    if not fresh: issues.append("projection subject is stale")
    excluded_roots = [".ai-kb", "tools"]
    maintenance = dict(cfg.knowledge.get("maintenance") or {})
    excluded_roots.extend(str(x).strip("/\\") for x in maintenance.get("local_out_of_scope_roots") or [] if str(x).strip("/\\"))
    indexed_excluded = 0
    for row in conn.execute("SELECT rel_path FROM documents"):
        rel = str(row[0] or "").replace("\\", "/").strip("/")
        if any(rel == root or rel.startswith(root + "/") for root in excluded_roots):
            indexed_excluded += 1
    if indexed_excluded: issues.append(f"excluded documents indexed: {indexed_excluded}")
    vector_mode = str(cfg.knowledge_projection.get("vector_mode") or "retired-compatible")
    vectors = conn.execute("SELECT count(*) FROM chunk_embeddings").fetchone()[0]
    if vector_mode in {"retired-compatible","disabled"} and vectors:
        issues.append(f"vector_mode={vector_mode} but active embedding rows exist: {vectors}")
    result = {
        "status":"PASS" if not issues else "WARN", "database":str(db), "fresh":fresh,
        "documents":conn.execute("SELECT count(*) FROM documents").fetchone()[0],
        "canonical_documents":conn.execute("SELECT count(*) FROM documents WHERE scope='canonical'").fetchone()[0],
        "source_documents":conn.execute("SELECT count(*) FROM documents WHERE scope='source'").fetchone()[0],
        "chunks":conn.execute("SELECT count(*) FROM chunks").fetchone()[0],
        "graph_nodes":conn.execute("SELECT count(*) FROM graph_nodes").fetchone()[0],
        "graph_edges":conn.execute("SELECT count(*) FROM graph_edges").fetchone()[0],
        "embedding_rows":vectors, "vector_mode":vector_mode, "retrieval_authority":str(cfg.knowledge_retrieval.get("strategy") or "canonical-first-fts5"),
        "issues":issues,
    }
    if own: conn.close()
    return result


def _query_scope(conn: sqlite3.Connection, expr: str, scope: str, projects: Optional[List[str]], kind: Optional[str], limit: int) -> List[Dict[str, Any]]:
    where = ["d.scope = ?"]; params: List[Any] = [expr, scope]
    if projects:
        where.append("d.project IN (" + ",".join("?" for _ in projects) + ")")
        params.extend(projects)
    if kind: where.append("d.kind = ?"); params.append(kind)
    sql = f"""SELECT rank score,c.heading_path,c.line_start,c.line_end,c.content_hash,
      d.rel_path,d.project,d.kind,d.scope,d.canonical_id,d.source_id,d.source_refs,d.title,d.freshness,d.sha256
      FROM fts_chunks JOIN chunks c ON c.id=fts_chunks.rowid JOIN documents d ON d.id=c.doc_id
      WHERE fts_chunks MATCH ? AND {' AND '.join(where)} ORDER BY rank LIMIT ?"""
    rows = conn.execute(sql, params + [limit]).fetchall()
    out=[]
    for r in rows:
        out.append({"id":r[9] if r[8]=="canonical" else r[10],"path":r[5],"project":r[6],"kind":r[7],"layer":r[8],"heading_path":r[1],"line_start":r[2],"line_end":r[3],"content_hash":r[4],"score":r[0],"source_refs":json.loads(r[11] or "[]"),"title":r[12],"freshness":r[13],"version":r[14],"version_kind":"document"})
    return out


def search_documents(cfg, query: str, *, project=None, scope=None, kind=None, layer=None,
                     limit=5, record_telemetry=True, request_id=None, task_id=None,
                     actor_role=None, purpose="development", caller="ai_cli") -> Dict[str, Any]:
    """Low-output AI entry. The legacy ``search`` chunk-list contract stays below."""
    request = telemetry.request_context(request_id=request_id, task_id=task_id,
        actor_role=actor_role, purpose=purpose, caller=caller)
    request.update(scope=scope or "project", project=project or "", projects=[], kind=kind or "",
                   layer=layer or "", limit=limit, offset=0, query_hash=telemetry.query_hash(query),
                   include_shared=bool(cfg.knowledge_retrieval.get("include_shared", True)),
                   source_fallback=bool(cfg.knowledge_retrieval.get("source_fallback", True)))
    t0 = time.perf_counter()
    try:
        request.update(resolve_scope(cfg, project=project, scope=scope))
        if not query.strip() or len(query) > 512 or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise telemetry.KnowledgeError("KNOWLEDGE_INVALID_QUERY")
        digest = telemetry.fingerprint("search", request)
        telemetry.check_request(cfg, request, digest, enabled=record_telemetry)
        effective_layer = layer or ("" if request["source_fallback"] else "canonical")
        result = query_documents(cfg, query, projects=request["projects"], kind=kind or "",
                                 layer=effective_layer, limit=limit)
        hits = result["items"]
        fallback = "canonical_shortfall" if not layer and any(h["layer"] == "source" for h in hits) else ""
        collected = telemetry.record(cfg, "search", request, digest, results=hits,
            elapsed_ms=(time.perf_counter()-t0)*1000, query_hash=request["query_hash"],
            fallback_reason=fallback, enabled=record_telemetry)
        return {"schema": "tp-spec.knowledge-search/v1", "status": "PASS", "query_hash_only": True,
                "query_hash": request["query_hash"], "scope": request["scope"],
                "requested_project": request["project"], "requested_projects": request["projects"],
                "returned_projects": sorted({h["project"] for h in hits}),
                "total": result["total"], "count": len(hits), "count_kind": "documents", "results": hits,
                "fallback_reason": fallback or None, **collected}
    except (ValueError, sqlite3.Error, OSError) as exc:
        code = exc.code if isinstance(exc, telemetry.KnowledgeError) else "KNOWLEDGE_SEARCH_FAILED"
        error = telemetry.KnowledgeError(code)
        if code not in {"KNOWLEDGE_REQUEST_CONFLICT", "KNOWLEDGE_RETRY_RESULT_CHANGED"}:
            error.collection = telemetry.record(cfg, "search", request, telemetry.fingerprint("search", request),
                status="failed", error_code=code, query_hash=request["query_hash"],
                elapsed_ms=(time.perf_counter()-t0)*1000, enabled=record_telemetry)
        raise error from None


def search(
    cfg, query: str, *, project: Optional[str]=None, kind: Optional[str]=None,
    layer: Optional[str]=None, limit: Optional[int]=None, record_telemetry: bool=True,
    scope: Optional[str]=None, purpose: str="unknown", caller: str="unknown",
    task_id=None, actor_role=None, request_id=None, telemetry_out=None,
) -> List[Dict[str, Any]]:
    """Compatibility chunk-list retrieval for Golden Query and Task convergence.

    The configured legacy limit and strategy remain intact. Its telemetry now has
    the same authoritative receipt writer as the document-oriented AI adapter.
    """
    if not query.strip():
        return []
    request = telemetry.request_context(request_id=request_id, task_id=task_id,
                                       actor_role=actor_role, purpose=purpose, caller=caller)
    request.update(query_hash=telemetry.query_hash(query), project=project or "", projects=[],
                   scope=scope or ("project" if project else str(cfg.knowledge_retrieval.get("default_scope") or "project")),
                   layer=layer or "", kind=kind or "", limit=limit or cfg.knowledge_retrieval.get("limit_default") or 20,
                   offset=0, count_kind="chunks",
                   source_fallback=bool(cfg.knowledge_retrieval.get("source_fallback", True)),
                   global_fallback=bool(cfg.knowledge_retrieval.get("global_fallback", False)),
                   include_shared=bool(cfg.knowledge_retrieval.get("include_shared", True)))
    t0 = time.perf_counter()
    try:
        expr = tokenize_query(query)
        limit = int(request["limit"])
        requested_scope = request["scope"]
        if requested_scope not in {"project", "global"}:
            raise telemetry.KnowledgeError("KNOWLEDGE_INVALID_SCOPE")
        projects = None
        if project:
            projects = [project]; requested_scope = "project"
        elif requested_scope == "project":
            resolved = resolve_knowledge_project(cfg, require=True)
            if not resolved.get("project_id"):
                raise telemetry.KnowledgeError("KNOWLEDGE_PROJECT_UNRESOLVED")
            request["project"] = str(resolved["project_id"])
            projects = [request["project"]]
            if cfg.knowledge_retrieval.get("include_shared", True):
                projects += [str(value) for value in resolved.get("shared_ids", []) if value]
            projects = sorted(set(projects))
        request.update(scope=requested_scope, projects=projects or [])
        digest = telemetry.fingerprint("search", request)
        telemetry.check_request(cfg, request, digest, enabled=record_telemetry)
        fallback = ""
        with telemetry.connect_readonly(cfg.paths.knowledge_projection_db) as conn:
            if layer in {"canonical", "source"}:
                hits = _query_scope(conn, expr, layer, projects, kind, limit)
            else:
                hits = _query_scope(conn, expr, "canonical", projects, kind, limit)
                if len(hits) < limit and cfg.knowledge_retrieval.get("source_fallback", True):
                    sources = _query_scope(conn, expr, "source", projects, kind, limit-len(hits))
                    hits.extend(sources)
                    if sources: fallback = "source-fallback"
                if not hits and requested_scope == "project" and cfg.knowledge_retrieval.get("global_fallback", False):
                    hits = _query_scope(conn, expr, "canonical", None, kind, limit)
                    if len(hits) < limit and cfg.knowledge_retrieval.get("source_fallback", True):
                        hits.extend(_query_scope(conn, expr, "source", None, kind, limit-len(hits)))
                    fallback = "global-fallback"
        for hit in hits:
            hit["document_key"] = document_key(cfg, hit["layer"], hit["id"] if hit["layer"] == "canonical" else "", hit["path"])
        collected = telemetry.record(cfg, "search", request, digest, results=hits, count_kind="chunks",
            candidate_count=len(hits), query_hash=request["query_hash"], fallback_reason=fallback,
            elapsed_ms=(time.perf_counter()-t0)*1000, enabled=record_telemetry)
        if telemetry_out is not None:
            telemetry_out.update(collected)
        elif collected.get("collection_warning"):
            warnings.warn(collected["collection_warning"], RuntimeWarning, stacklevel=2)
        return hits
    except (ValueError, sqlite3.Error, OSError) as exc:
        code = exc.code if isinstance(exc, telemetry.KnowledgeError) else "KNOWLEDGE_SEARCH_FAILED"
        if code not in {"KNOWLEDGE_REQUEST_CONFLICT", "KNOWLEDGE_RETRY_RESULT_CHANGED"}:
            collected = telemetry.record(cfg, "search", request, telemetry.fingerprint("search", request),
                status="failed", error_code=code, query_hash=request["query_hash"],
                elapsed_ms=(time.perf_counter()-t0)*1000, enabled=record_telemetry)
            if telemetry_out is not None: telemetry_out.update(collected)
        raise telemetry.KnowledgeError(code) from None


def telemetry_summary(cfg, days: int=7) -> Dict[str, Any]:
    db = cfg.paths.knowledge_projection_db
    if not db.is_file():
        return {"queries": 0, "days": days, "status": "missing", "note": "usage availability unknown"}
    with telemetry.connect_readonly(db) as conn:
        modern = "status" in telemetry.columns(conn, "retrieval_runs")
        condition = "AND (status IS NULL OR status='completed')" if modern else ""
        rows = conn.execute("SELECT fallback_reason,answerability,layer,elapsed_ms FROM retrieval_runs "
            f"WHERE julianday('now')-julianday(created_at) BETWEEN 0 AND ? {condition}", (days,)).fetchall()
    n = len(rows)
    return {"days": days, "queries": n, "status": "available" if modern else "legacy",
            "source_fallback": sum(r[0] in {"source-fallback", "canonical_shortfall"} for r in rows),
            "no_result": sum(r[1] == "no_result" for r in rows),
            "canonical_only": sum(r[2] == "canonical" for r in rows),
            "average_latency_ms": round(sum(float(r[3] or 0) for r in rows)/n, 3) if n else 0.0}
