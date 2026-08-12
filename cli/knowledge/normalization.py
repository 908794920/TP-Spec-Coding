# -*- coding: utf-8 -*-
"""Deterministic normalization for legacy Knowledge canonical frontmatter.

Only transformations with a single semantics-preserving interpretation are
applied automatically. Ambiguous vocabulary/evidence/meaning is emitted as a
review queue for tp-knowledge instead of being guessed.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import json
import re

import yaml

from .common import FRONTMATTER_RE, KIND_CODES, collect_notes, meta_paths, now_iso, stable_hash, write_json

CONFIDENCE_MAP = {"high": 0.90, "medium": 0.60, "low": 0.30}
KIND_ALIAS = {"ops": "operation"}
RELATION_ALIAS = {"relates_to": "related_to"}
CODE_TO_KIND = {code: kind for kind, code in KIND_CODES.items()}
ID_KIND_RE = re.compile(r"^[A-Z][A-Z0-9]*-([A-Z]+)-\d{3,}$")
SAFE_RELATIONS = {
    "part_of", "implements", "depends_on", "calls", "reads", "writes",
    "triggered_by", "supersedes", "source_refs", "verifies", "related_to",
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _infer_kind(note_id: str) -> Optional[str]:
    m = ID_KIND_RE.match(note_id or "")
    if not m:
        return None
    return CODE_TO_KIND.get(m.group(1))


def _relation_name(name: Any) -> str:
    text = str(name or "").strip()
    return RELATION_ALIAS.get(text, text)


def _normalize_relations(raw: Any) -> Tuple[Any, List[Dict[str, Any]], List[str]]:
    ops: List[Dict[str, Any]] = []
    review: List[str] = []
    if raw is None:
        return raw, ops, review
    if isinstance(raw, dict):
        out: List[Dict[str, Any]] = []
        for old_type, targets in raw.items():
            rtype = _relation_name(old_type)
            values = targets if isinstance(targets, list) else [targets]
            if rtype not in SAFE_RELATIONS:
                review.append(f"relation type requires semantic review: {old_type}")
                # Preserve it structurally so lint can report the semantic vocabulary issue.
            for value in values:
                if isinstance(value, str):
                    out.append({"type": rtype, "target": value})
                elif isinstance(value, dict) and value.get("target"):
                    item = dict(value)
                    item["type"] = _relation_name(item.get("type") or rtype)
                    out.append(item)
                else:
                    review.append(f"relation value cannot be normalized safely: {old_type}={value!r}")
        ops.append({"field": "relations", "action": "dict_to_array", "count": len(out)})
        return out, ops, review
    if isinstance(raw, list):
        out=[]; changed=False
        for idx, value in enumerate(raw):
            if not isinstance(value, dict):
                review.append(f"relations/{idx} is not an object")
                out.append(value); continue
            item=dict(value)
            old=str(item.get("type") or "")
            new=_relation_name(old)
            if new != old:
                item["type"] = new; changed=True
                ops.append({"field": f"relations/{idx}/type", "action": "alias", "from": old, "to": new})
            if new and new not in SAFE_RELATIONS:
                review.append(f"relation type requires semantic review: {new}")
            out.append(item)
        return out if changed else raw, ops, review
    review.append("relations is neither array nor legacy mapping")
    return raw, ops, review


def plan_note(note: Dict[str, Any]) -> Dict[str, Any]:
    fm = note.get("frontmatter")
    rel = str(note.get("rel_path") or "")
    result: Dict[str, Any] = {
        "path": rel,
        "before_sha256": note.get("sha256"),
        "safe_operations": [],
        "review": [],
        "changed": False,
    }
    if not isinstance(fm, dict):
        result["review"].append(note.get("parse_error") or "frontmatter missing")
        return result
    new = deepcopy(fm)

    if "canonical" not in new:
        new["canonical"] = True
        result["safe_operations"].append({"field":"canonical","action":"set_missing","value":True})

    kind = str(new.get("kind") or "").strip()
    normalized_kind = KIND_ALIAS.get(kind)
    if kind == "canonical":
        normalized_kind = _infer_kind(str(new.get("id") or ""))
        if not normalized_kind:
            result["review"].append("kind='canonical' but canonical ID does not encode a known kind")
    if normalized_kind and normalized_kind != kind:
        new["kind"] = normalized_kind
        result["safe_operations"].append({"field":"kind","action":"normalize","from":kind,"to":normalized_kind,"basis":"stable canonical ID/kind alias"})

    confidence = new.get("confidence")
    if isinstance(confidence, str) and confidence.strip().casefold() in CONFIDENCE_MAP:
        old=confidence; mapped=CONFIDENCE_MAP[confidence.strip().casefold()]
        new["confidence"] = mapped
        result["safe_operations"].append({"field":"confidence","action":"legacy_qualitative_encoding","from":old,"to":mapped,"scale":"legacy-qualitative-v1"})
    elif confidence is None:
        result["review"].append("required confidence missing; do not fabricate")

    if "last_verified" not in new or not str(new.get("last_verified") or "").strip():
        result["review"].append("required last_verified missing; requires real verification date")

    aliases = new.get("aliases")
    if isinstance(aliases, list):
        normalized=[]; changed=False
        for value in aliases:
            if isinstance(value, str): normalized.append(value)
            else: normalized.append(str(value)); changed=True
        if changed:
            new["aliases"] = normalized
            result["safe_operations"].append({"field":"aliases","action":"scalar_to_string"})

    rels, rel_ops, rel_review = _normalize_relations(new.get("relations"))
    if rel_ops:
        new["relations"] = rels
        result["safe_operations"].extend(rel_ops)
    result["review"].extend(rel_review)

    # source_refs remains required for compatibility. Adding an empty list is safe
    # only when structured evidence already exists; otherwise absence is meaningful.
    if "source_refs" not in new:
        evidence = new.get("evidence_refs")
        if isinstance(evidence, list) and evidence:
            new["source_refs"] = []
            result["safe_operations"].append({"field":"source_refs","action":"set_empty_with_structured_evidence"})
        else:
            result["review"].append("source_refs missing and no structured evidence exists")

    source_refs = new.get("source_refs")
    evidence_refs = new.get("evidence_refs")
    if (not isinstance(source_refs, list) or not source_refs) and (not isinstance(evidence_refs, list) or not evidence_refs):
        result["review"].append("canonical has no usable source/evidence reference")
    if new.get("evidence_type") and (not evidence_refs):
        result["review"].append("legacy evidence_type exists without structured evidence ref; requires source/code lookup")

    result["changed"] = new != fm
    result["frontmatter_after"] = new
    return result


def _render_frontmatter(original_text: str, fm: Dict[str, Any]) -> str:
    match = FRONTMATTER_RE.match(original_text.lstrip("\ufeff"))
    if not match:
        raise ValueError("cannot rewrite note without valid frontmatter")
    body = original_text.lstrip("\ufeff")[match.end():]
    y = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip()
    return f"---\n{y}\n---\n{body}"


def normalization_plan(cfg) -> Dict[str, Any]:
    canonical, _ = collect_notes(cfg.paths.knowledge_physical_root, cfg)
    rows = [plan_note(n) for n in canonical]
    safe = [r for r in rows if r["changed"]]
    review = [r for r in rows if r["review"]]
    return {
        "schema": "ai-work.knowledge-normalization-plan/v1",
        "status": "READY" if safe else ("REVIEW_ONLY" if review else "NO_CHANGE"),
        "read_only": True,
        "root": str(cfg.paths.knowledge_physical_root),
        "canonical_documents": len(canonical),
        "safe_documents": len(safe),
        "safe_operations": sum(len(r["safe_operations"]) for r in safe),
        "review_documents": len(review),
        "safe_changes": [{k:v for k,v in r.items() if k != "frontmatter_after"} for r in safe],
        "review_queue": [{"path":r["path"],"reasons":r["review"]} for r in review],
        "confidence_mapping": {"scale":"legacy-qualitative-v1", **CONFIDENCE_MAP, "meaning":"compatibility encoding, not measured probability"},
        "automatic_scope": [
            "legacy relations mapping -> relation object array",
            "relates_to -> related_to",
            "ops -> operation",
            "kind=canonical -> kind inferred from stable ID code when unambiguous",
            "high/medium/low confidence -> documented compatibility encoding",
            "numeric alias -> string",
            "missing canonical=true for canonical-layer documents",
            "missing source_refs=[] only when structured evidence_refs is already non-empty",
        ],
        "never_auto": ["implemented_by/evolves_into or other unknown relation semantics", "missing confidence", "missing last_verified", "missing evidence", "relation kind-contract semantic changes"],
    }


def apply_normalization(cfg) -> Dict[str, Any]:
    canonical, _ = collect_notes(cfg.paths.knowledge_physical_root, cfg)
    plans = [plan_note(n) for n in canonical]
    changed=[]
    for note, plan in zip(canonical, plans):
        if not plan["changed"]:
            continue
        path: Path = note["path"]
        before_text = note["text"]
        if _sha(before_text) != plan["before_sha256"]:
            raise ValueError(f"normalization subject changed before apply: {plan['path']}")
        after_text = _render_frontmatter(before_text, plan["frontmatter_after"])
        tmp = path.with_suffix(path.suffix + ".normalize.tmp")
        tmp.write_text(after_text, encoding="utf-8", newline="\n")
        tmp.replace(path)
        changed.append({
            "path": plan["path"],
            "before_sha256": plan["before_sha256"],
            "after_sha256": _sha(after_text),
            "operations": plan["safe_operations"],
        })
    review=[{"path":r["path"],"reasons":r["review"]} for r in plans if r["review"]]
    receipt = {
        "schema":"ai-work.knowledge-normalization-receipt/v1",
        "status":"APPLIED" if changed else "NO_CHANGE",
        "applied_at":now_iso(),
        "root":str(cfg.paths.knowledge_physical_root),
        "changed_documents":changed,
        "changed_count":len(changed),
        "review_queue":review,
        "review_count":len(review),
    }
    receipt["receipt_id"] = stable_hash(receipt)
    mp=meta_paths(cfg)
    write_json(mp["root"] / "knowledge-normalization-receipt.json", receipt)
    write_json(mp["root"] / "knowledge-normalization-review.json", {"schema":"ai-work.knowledge-normalization-review/v1","generated_at":receipt["applied_at"],"items":review})
    return receipt
