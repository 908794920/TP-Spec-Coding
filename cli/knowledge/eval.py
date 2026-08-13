# -*- coding: utf-8 -*-
"""Golden-query evaluation for the active FTS5 Knowledge retrieval chain.

This deliberately evaluates only deterministic/local retrieval surfaces. Vector
retrieval is retired-compatible and is not silently resurrected by evaluation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
import json
import math
import os
import sqlite3
import time

from .common import load_project_registry, now_iso
from .projection import search


def _resolve_path(root: Path, value: Any, default: str) -> Path:
    text = str(value or default).strip() or default
    p = Path(os.path.expandvars(os.path.expanduser(text)))
    if not p.is_absolute():
        p = root / p
    return p.resolve(strict=False)


def load_golden(cfg, path: Optional[str] = None) -> Tuple[Path, List[Dict[str, Any]]]:
    root = cfg.paths.knowledge_physical_root
    if path:
        p = Path(path)
        if not p.is_absolute(): p = root / p
        p = p.resolve(strict=False)
    else:
        p = _resolve_path(root, cfg.knowledge_evaluation.get("golden_set"), "00-system/eval/golden.jsonl")
    if not p.is_file():
        raise ValueError(f"golden set not found: {p}")
    rows: List[Dict[str, Any]] = []
    for line_no, line in enumerate(p.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip(): continue
        try: row = json.loads(line)
        except json.JSONDecodeError as exc: raise ValueError(f"invalid golden JSONL line {line_no}: {exc}") from exc
        if not isinstance(row, dict) or not row.get("id") or not row.get("question") or not row.get("answer_type"):
            raise ValueError(f"golden line {line_no} requires id/question/answer_type")
        rows.append(row)
    return p, rows


def _project_alias_map(cfg) -> Dict[str, Set[str]]:
    data, _ = load_project_registry(cfg)
    out: Dict[str, Set[str]] = {}
    for entry in list(data.get("projects", []) or []) + list(data.get("shared_scopes", []) or []):
        if not isinstance(entry, dict) or not entry.get("id"): continue
        pid = str(entry["id"])
        values = {pid, str(entry.get("display_name") or ""), str(entry.get("source_dir") or "")}
        values.update(str(x) for x in (entry.get("aliases") or []) if x)
        for v in values:
            v=v.strip().casefold()
            if v: out.setdefault(v,set()).add(pid)
    return out


def _expected_projects(row: Dict[str, Any], aliases: Dict[str, Set[str]]) -> Set[str]:
    raw=str(row.get("expected_project") or "").strip()
    if not raw: return set()
    return set(aliases.get(raw.casefold()) or {raw})


def _expected_ids(row: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()
    for key in ("expected_canonical", "expected_canonical_id"):
        if row.get(key): out.add(str(row[key]))
    for key in ("expected_canonical_ids", "expected_source_refs"):
        val=row.get(key) or []
        if isinstance(val,list): out.update(str(x) for x in val if x)
    return out


def _match_rank(row: Dict[str, Any], hits: Sequence[Dict[str, Any]], aliases: Dict[str, Set[str]], limit: int) -> int:
    expected=_expected_ids(row); projects=_expected_projects(row,aliases)
    for idx, hit in enumerate(hits[:limit],1):
        hid=str(hit.get("id") or "")
        hrefs={str(x) for x in (hit.get("source_refs") or [])}
        if expected and (hid in expected or bool(hrefs & expected)):
            return idx
        if not expected and row.get("answer_type") == "has_answer" and projects:
            if str(hit.get("project") or "") in projects:
                return idx
    return 0


def _filename_search(cfg, query: str, limit: int) -> List[Dict[str, Any]]:
    db=cfg.paths.knowledge_projection_db
    if not db.is_file(): return []
    # Kept only as a historical/local baseline; this is not the product retrieval path.
    import re
    keywords=re.findall(r"[\u4e00-\u9fffA-Za-z0-9_./:-]+", query)
    if not keywords: return []
    conn=sqlite3.connect(str(db)); conn.row_factory=sqlite3.Row
    rows=conn.execute("SELECT rel_path,scope,project,kind,canonical_id,source_id,source_refs,title,freshness FROM documents ORDER BY rel_path").fetchall(); conn.close()
    out=[]
    for r in rows:
        fname=Path(r["rel_path"]).name.casefold()
        if all(k.casefold() in fname for k in keywords):
            out.append({"id":r["canonical_id"] if r["scope"]=="canonical" else r["source_id"],"path":r["rel_path"],"project":r["project"],"kind":r["kind"],"layer":r["scope"],"source_refs":json.loads(r["source_refs"] or "[]"),"title":r["title"],"freshness":r["freshness"]})
        if len(out)>=limit: break
    return out


def _metrics(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    answered=[r for r in rows if r["answer_type"]=="has_answer"]
    no_answer=[r for r in rows if r["answer_type"]=="no_answer"]
    lat=sorted(float(r["latency_ms"]) for r in rows)
    def pct(q: float) -> float:
        if not lat: return 0.0
        idx=max(0,min(len(lat)-1,math.ceil(len(lat)*q)-1)); return lat[idx]
    recall=sum(1 for r in answered if r["rank"]>0)/len(answered) if answered else 0.0
    mrr=sum((1.0/r["rank"]) for r in answered if r["rank"]>0)/len(answered) if answered else 0.0
    ndcg=sum((1.0/math.log2(r["rank"]+1)) for r in answered if 0<r["rank"]<=5)/len(answered) if answered else 0.0
    top5=sum(1 for r in answered if 0<r["rank"]<=5)/len(answered) if answered else 0.0
    false=sum(1 for r in no_answer if r["hit_count"]>0)/len(no_answer) if no_answer else 0.0
    return {
        "Recall@20":round(recall,4),"MRR":round(mrr,4),"nDCG@5":round(ndcg,4),"Top5_hit_rate":round(top5,4),
        "no_answer_false_recall_rate":round(false,4),"p50_latency_ms":round(pct(.50),3),"p95_latency_ms":round(pct(.95),3),
        "denominators":{"has_answer_count":len(answered),"no_answer_count":len(no_answer),"route_fallback_count":sum(1 for r in rows if r["answer_type"]=="route_fallback"),"total":len(rows)},
    }


def evaluate(cfg, *, golden_path: Optional[str]=None, output: Optional[str]=None, modes: Optional[Iterable[str]]=None) -> Dict[str, Any]:
    path,golden=load_golden(cfg,golden_path); aliases=_project_alias_map(cfg)
    limit=int(cfg.knowledge_evaluation.get("limit") or 20)
    selected=list(modes or ["filename_search","source_only_fts","canonical_first_fts"])
    allowed={"filename_search","source_only_fts","canonical_first_fts"}
    unknown=[m for m in selected if m not in allowed]
    if unknown: raise ValueError(f"unsupported eval mode(s): {', '.join(unknown)}")
    per_mode: Dict[str, Any] = {}
    for mode in selected:
        qrows=[]
        for g in golden:
            t0=time.perf_counter()
            if mode=="filename_search": hits=_filename_search(cfg,str(g["question"]),limit)
            elif mode=="source_only_fts": hits=search(cfg,str(g["question"]),layer="source",limit=limit,record_telemetry=False,scope="global")
            else: hits=search(cfg,str(g["question"]),limit=limit,record_telemetry=False,scope="global")
            elapsed=(time.perf_counter()-t0)*1000.0
            rank=_match_rank(g,hits,aliases,limit)
            qrows.append({"id":g["id"],"answer_type":g["answer_type"],"category":g.get("category",""),"rank":rank,"matched":bool(rank),"hit_count":len(hits),"latency_ms":round(elapsed,3)})
        per_mode[mode]={"metrics":_metrics(qrows),"per_question":qrows}
    result={"schema":"tp-spec.knowledge-golden-eval/v1","status":"PASS","generated_at":now_iso(),"golden_set":str(path),"golden_count":len(golden),"retrieval_authority":str(cfg.knowledge_retrieval.get("strategy") or "canonical-first-fts5"),"vector_mode":str(cfg.knowledge_projection.get("vector_mode") or "retired-compatible"),"modes":per_mode}
    if output:
        out=Path(output)
        if not out.is_absolute(): out=cfg.paths.knowledge_physical_root/out
    else:
        root=_resolve_path(cfg.paths.knowledge_physical_root,cfg.knowledge_evaluation.get("output_root"),".ai-kb/eval")
        out=root/"golden-eval.json"
    out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    result["output"]=str(out)
    return result
