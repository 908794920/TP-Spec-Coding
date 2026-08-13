# -*- coding: utf-8 -*-
"""Deterministic external-source registration and disposition tracking."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import fnmatch
import hashlib
import json

from .common import meta_paths, now_iso, read_json, read_jsonl, write_json, write_jsonl

TERMINAL = {"canonicalized", "merged", "source_only", "duplicate", "superseded", "quarantined", "excluded"}
VALID = TERMINAL | {"pending"}


def _ingest_root(cfg) -> Path:
    rel = str(cfg.knowledge_ingest.get("manifest_root") or ".ai-kb/ingest")
    p = Path(rel)
    return p if p.is_absolute() else (cfg.paths.knowledge_physical_root / p)


def batch_paths(cfg, batch: str) -> Dict[str, Path]:
    root = _ingest_root(cfg) / batch
    return {"root":root, "meta":root/"batch.json", "manifest":root/"manifest.jsonl"}


def _excluded(rel: str, globs: List[str]) -> bool:
    rel = rel.replace("\\", "/")
    return any(fnmatch.fnmatch(rel, g) or Path(rel).match(g) for g in globs)


def _sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()


def _sync_global_registry(cfg, batch_rows: List[Dict[str, Any]]) -> None:
    path=meta_paths(cfg)["source_registry"]
    current=read_jsonl(path)
    keyed={(str(r.get("batch") or ""),str(r.get("origin_path") or "")):r for r in current}
    for r in batch_rows:
        key=(str(r.get("batch") or ""),str(r.get("origin_path") or ""))
        keyed[key]={k:v for k,v in r.items() if k not in {"absolute_path","classification"}}
    write_jsonl(path, [keyed[k] for k in sorted(keyed)])


def register_batch(cfg, *, project: str, batch: str, source_root: Path) -> Dict[str, Any]:
    source_root=source_root.resolve(strict=True)
    if not source_root.is_dir(): raise ValueError(f"source root is not a directory: {source_root}")
    # Project must be configured; do not infer from folder names.
    import yaml
    reg=cfg.paths.knowledge_registry
    if not reg.is_file(): raise ValueError("knowledge project registry missing")
    data=yaml.safe_load(reg.read_text(encoding="utf-8-sig")) or {}
    ids={str(x.get("id")) for x in (data.get("projects") or []) if isinstance(x,dict)} | {str(x.get("id")) for x in (data.get("shared_scopes") or []) if isinstance(x,dict)}
    if project not in ids: raise ValueError(f"project not registered: {project}")
    paths=batch_paths(cfg,batch)
    if paths["meta"].is_file() and (read_json(paths["meta"],{}) or {}).get("finalized_at"):
        raise ValueError(f"batch already finalized: {batch}")
    allowed={str(x).lower() for x in (cfg.knowledge_ingest.get("allowed_extensions") or [])}
    exclude=[str(x) for x in (cfg.knowledge_ingest.get("hard_exclude_globs") or [])]
    rows=[]; first_by_hash={}
    for p in sorted(x for x in source_root.rglob("*") if x.is_file()):
        rel=p.relative_to(source_root).as_posix(); suffix=p.suffix.lower(); sha=_sha256(p)
        source_id="SRC-"+sha[:12]
        disposition="pending"; reason=""
        if _excluded(rel,exclude): disposition="excluded"; reason="hard-exclude-glob"
        elif allowed and suffix not in allowed: disposition="excluded"; reason="extension-not-enabled"
        elif sha in first_by_hash: disposition="duplicate"; reason=f"duplicate-of:{first_by_hash[sha]}"
        else: first_by_hash[sha]=rel
        if suffix in {".md",".txt",".pdf",".doc",".docx"}: classification="convert_candidate"
        elif suffix in {".xls",".xlsx",".ppt",".pptx"}: classification="register_summary"
        else: classification="listed_only"
        rows.append({"source_id":source_id,"project":project,"batch":batch,"origin_path":rel,"sha256":sha,"size":p.stat().st_size,"mtime_ns":p.stat().st_mtime_ns,"classification":classification,"disposition":disposition,"canonical_ids":[],"reason":reason})
    paths["root"].mkdir(parents=True,exist_ok=True)
    write_jsonl(paths["manifest"],rows)
    write_json(paths["meta"],{"schema":"tp-spec.knowledge-ingest-batch/v1","batch":batch,"project":project,"source_root":str(source_root),"registered_at":now_iso(),"source_count":len(rows),"finalized_at":None})
    _sync_global_registry(cfg,rows)
    return ingest_status(cfg,batch)


def disposition(cfg, *, batch: str, source_id: str, disposition_name: str, canonical_ids: List[str], reason: str="", origin_path: Optional[str]=None) -> Dict[str, Any]:
    if disposition_name not in VALID: raise ValueError(f"invalid disposition: {disposition_name}")
    paths=batch_paths(cfg,batch); rows=read_jsonl(paths["manifest"])
    matches=[i for i,r in enumerate(rows) if str(r.get("source_id"))==source_id and (origin_path is None or str(r.get("origin_path"))==origin_path)]
    if not matches: raise ValueError(f"source not found in batch: {source_id}")
    if len(matches)>1 and origin_path is None: raise ValueError("source_id appears multiple times; specify --origin-path")
    for i in matches:
        rows[i]["disposition"]=disposition_name; rows[i]["canonical_ids"]=sorted(set(canonical_ids)); rows[i]["reason"]=reason; rows[i]["updated_at"]=now_iso()
    write_jsonl(paths["manifest"],rows); _sync_global_registry(cfg,rows); return ingest_status(cfg,batch)


def ingest_status(cfg, batch: str) -> Dict[str, Any]:
    paths=batch_paths(cfg,batch); rows=read_jsonl(paths["manifest"]); counts={}
    for r in rows:
        d=str(r.get("disposition") or ""); counts[d]=counts.get(d,0)+1
    total=len(rows); accounted=sum(v for k,v in counts.items() if k in TERMINAL)
    return {"schema":"tp-spec.knowledge-ingest-status/v1","batch":batch,"registered":total,"accounted":accounted,"pending":counts.get("pending",0),"accountability":accounted/total if total else None,"dispositions":counts,"finalized":bool((read_json(paths["meta"],{}) or {}).get("finalized_at"))}


def finalize_batch(cfg, batch: str) -> Dict[str, Any]:
    paths=batch_paths(cfg,batch); status=ingest_status(cfg,batch)
    if status["pending"] or status["accounted"] != status["registered"]:
        raise ValueError(f"batch finalize blocked: accountability incomplete ({status['accounted']}/{status['registered']})")
    meta=read_json(paths["meta"],{}) or {}
    meta["finalized_at"]=now_iso(); meta["final_accountability"]=status["accountability"]
    write_json(paths["meta"],meta)
    status["finalized"]=True; status["status"]="PASS"; return status
