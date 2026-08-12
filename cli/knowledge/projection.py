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

from .common import collect_notes, load_source_registry, now_iso, stable_hash, resolve_knowledge_project

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


def _source_id(note: Dict[str, Any], source_registry: Dict[str, Dict[str, Any]]) -> str:
    if note.get("id"):
        return str(note["id"])
    for sid, rec in source_registry.items():
        if str(rec.get("content_path") or "").replace("\\", "/") == note["rel_path"]:
            return sid
    return ""


def _insert_doc(conn: sqlite3.Connection, note: Dict[str, Any], source_registry: Dict[str, Dict[str, Any]]) -> None:
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
    for ref in note.get("source_refs") or []:
        conn.execute("INSERT INTO doc_links(doc_id,link_type,target_id) VALUES(?,?,?)", (doc_id, "source_ref", str(ref)))
    for idx, ch in enumerate(chunk_markdown(note["body"], note["body_start_line"])):
        c = conn.execute(
            "INSERT INTO chunks(doc_id,chunk_idx,heading_path,line_start,line_end,content,content_hash) VALUES(?,?,?,?,?,?,?)",
            (doc_id, idx, ch["heading_path"], ch["line_start"], ch["line_end"], ch["content"], ch["content_hash"]),
        )
        chunk_id = int(c.lastrowid)
        tokenized = tokenize(ch["content"] + " " + ch["heading_path"] + " " + note["title"])
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
    if clean:
        # Preserve telemetry and retired-compatible model tables; all active retrieval projections are rebuilt.
        conn.execute("DELETE FROM fts_chunks"); conn.execute("DELETE FROM doc_links"); conn.execute("DELETE FROM chunks"); conn.execute("DELETE FROM documents")
    for n in canonical + sources:
        _insert_doc(conn, n, registry)
    _rebuild_graph(conn, canonical, str(cfg.knowledge_projection.get("graph_mode") or "optional"))
    subject = stable_hash({n["rel_path"]: n["sha256"] for n in canonical + sources})
    meta = {
        "projection_schema": "ai-work.knowledge-projection/v1",
        "projection_subject": subject,
        "build_at": now_iso(),
        "build_doc_count": str(len(canonical) + len(sources)),
        "build_chunk_count": str(conn.execute("SELECT count(*) FROM chunks").fetchone()[0]),
        "vector_state": str(cfg.knowledge_projection.get("vector_mode") or "retired-compatible"),
        "retrieval_authority": str(cfg.knowledge_retrieval.get("strategy") or "canonical-first-fts5"),
    }
    for k, v in meta.items(): conn.execute("INSERT OR REPLACE INTO build_meta(key,value) VALUES(?,?)", (k, str(v)))
    conn.commit()
    result = projection_status(cfg, conn=conn)
    conn.close()
    return result


def update_projection(cfg) -> Dict[str, Any]:
    db = cfg.paths.knowledge_projection_db
    if not db.is_file():
        return build_projection(cfg, clean=True)
    root = cfg.paths.knowledge_physical_root; canonical, sources = collect_notes(root, cfg); notes = canonical + sources
    current = {n["rel_path"]: n for n in notes}; registry = load_source_registry(cfg)
    conn = _connect(db)
    old = {r[0]: (int(r[1]), r[2]) for r in conn.execute("SELECT rel_path,id,sha256 FROM documents")}
    removed = set(old) - set(current)
    changed = [n for p,n in current.items() if p not in old or old[p][1] != n["sha256"]]
    for rel in removed | {n["rel_path"] for n in changed if n["rel_path"] in old}:
        doc_id = old[rel][0]
        for (cid,) in conn.execute("SELECT id FROM chunks WHERE doc_id=?", (doc_id,)).fetchall():
            conn.execute("DELETE FROM fts_chunks WHERE rowid=?", (cid,))
        conn.execute("DELETE FROM doc_links WHERE doc_id=?", (doc_id,)); conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,)); conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    for n in changed: _insert_doc(conn, n, registry)
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
      d.rel_path,d.project,d.kind,d.scope,d.canonical_id,d.source_id,d.source_refs,d.title,d.freshness
      FROM fts_chunks JOIN chunks c ON c.id=fts_chunks.rowid JOIN documents d ON d.id=c.doc_id
      WHERE fts_chunks MATCH ? AND {' AND '.join(where)} ORDER BY rank LIMIT ?"""
    rows = conn.execute(sql, params + [limit]).fetchall()
    out=[]
    for r in rows:
        out.append({"id":r[9] if r[8]=="canonical" else r[10],"path":r[5],"project":r[6],"kind":r[7],"layer":r[8],"heading_path":r[1],"line_start":r[2],"line_end":r[3],"content_hash":r[4],"score":r[0],"source_refs":json.loads(r[11] or "[]"),"title":r[12],"freshness":r[13]})
    return out


def search(
    cfg, query: str, *, project: Optional[str]=None, kind: Optional[str]=None,
    layer: Optional[str]=None, limit: Optional[int]=None, record_telemetry: bool=True,
    scope: Optional[str]=None,
) -> List[Dict[str, Any]]:
    db=cfg.paths.knowledge_projection_db
    if not db.is_file(): raise ValueError("knowledge projection database missing; run knowledge index build")
    expr=tokenize_query(query)
    if expr is None: return []
    limit=int(limit or cfg.knowledge_retrieval.get("limit_default") or 20)
    requested_scope = scope or ("project" if project else str(cfg.knowledge_retrieval.get("default_scope") or "project"))
    if requested_scope not in {"project", "global"}:
        raise ValueError("knowledge retrieval scope must be project|global")
    projects: Optional[List[str]] = None
    resolved_project = ""
    if project:
        projects=[project]; resolved_project=project; requested_scope="project"
    elif requested_scope == "project":
        resolved = resolve_knowledge_project(cfg, require=True)
        resolved_project = str(resolved.get("project_id") or "")
        projects=[resolved_project]
        if bool(cfg.knowledge_retrieval.get("include_shared", True)):
            projects.extend(str(v) for v in (resolved.get("shared_ids") or []) if str(v))
        projects=list(dict.fromkeys(projects))

    t0=time.perf_counter(); conn=_connect(db)
    if layer in {"canonical","source"}:
        hits=_query_scope(conn,expr,layer,projects,kind,limit)
    else:
        canonical=_query_scope(conn,expr,"canonical",projects,kind,limit)
        hits=list(canonical)
        if len(hits) < limit and bool(cfg.knowledge_retrieval.get("source_fallback",True)):
            sources=_query_scope(conn,expr,"source",projects,kind,limit-len(hits))
            hits.extend(sources)
        if not hits and requested_scope == "project" and bool(cfg.knowledge_retrieval.get("global_fallback",False)):
            canonical=_query_scope(conn,expr,"canonical",None,kind,limit)
            hits=list(canonical)
            if len(hits) < limit and bool(cfg.knowledge_retrieval.get("source_fallback",True)):
                hits.extend(_query_scope(conn,expr,"source",None,kind,limit-len(hits)))
            requested_scope="global-fallback"
    elapsed=(time.perf_counter()-t0)*1000
    if record_telemetry and bool(cfg.knowledge_retrieval.get("telemetry",True)):
        source_used=any(h["layer"]=="source" for h in hits)
        top=hits[0]["score"] if hits else None
        final_layer=("mixed" if any(h["layer"]=="canonical" for h in hits) and source_used else (hits[0]["layer"] if hits else ""))
        fallback_reason = "source-fallback" if source_used else ("global-fallback" if requested_scope == "global-fallback" else "")
        mode = str(cfg.knowledge_retrieval.get("strategy") or "canonical-first-fts5") + ":" + requested_scope
        conn.execute("""INSERT INTO retrieval_runs(query_hash,retrieval_mode,fallback_reason,candidate_count,fts_score,answerability,layer,elapsed_ms,created_at)
                        VALUES(?,?,?,?,?,?,?,?,?)""",
                     (hashlib.sha256(query.encode("utf-8")).hexdigest(), mode, fallback_reason, len(hits), top, "hit" if hits else "no_result", final_layer, elapsed, now_iso()))
        retention=int(cfg.knowledge_retrieval.get("telemetry_retention_days") or 30)
        conn.execute("DELETE FROM retrieval_runs WHERE julianday('now') - julianday(created_at) > ?", (retention,))
        conn.commit()
    conn.close(); return hits


def telemetry_summary(cfg, days: int=7) -> Dict[str, Any]:
    db=cfg.paths.knowledge_projection_db
    if not db.is_file(): return {"queries":0,"days":days}
    conn=_connect(db); rows=conn.execute("SELECT fallback_reason,answerability,layer,elapsed_ms FROM retrieval_runs WHERE julianday('now') - julianday(created_at) <= ?",(days,)).fetchall(); conn.close()
    n=len(rows)
    return {
        "days":days,"queries":n,
        "source_fallback":sum(1 for r in rows if r[0]=="source-fallback"),
        "no_result":sum(1 for r in rows if r[1]=="no_result"),
        "canonical_only":sum(1 for r in rows if r[2]=="canonical"),
        "average_latency_ms":round(sum(float(r[3] or 0) for r in rows)/n,3) if n else 0.0,
    }
