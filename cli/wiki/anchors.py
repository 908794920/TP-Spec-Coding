# -*- coding: utf-8 -*-
"""Deterministic citation line-anchor persistence and cosmetic relocation.

A Wiki citation's ``line=`` attribute is precise provenance, not prose.  A source
file can remain semantically identical while comments/blank lines move code to new
physical lines.  Raw/normalized fingerprinting correctly classifies that as
COSMETIC, but the old line number must still be relocated without spending model
Tokens.

The committed anchor baseline stores only hashed line signatures for *cited*
source files plus citation coordinates.  No source text is copied into the Wiki.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import hashlib
import json
import os
import re
import unicodedata

import yaml

from .source import decode_text, normalize_text, resolve_repo_relative

ANCHOR_SCHEMA = "ai-work.wiki-cite-anchors/v1"
_CITE_TAG = re.compile(r"<cite\b[^>]*?/?>", re.I)
_PATH_ATTR = re.compile(r"\bpath=[\"']([^\"']+)[\"']", re.I)
_LINE_ATTR = re.compile(r"\bline=[\"']([^\"']+)[\"']", re.I)


def _meta(wiki_repo_root: Path, name: str) -> Path:
    return wiki_repo_root / "meta" / name


def anchor_path(wiki_repo_root: Path) -> Path:
    return _meta(wiki_repo_root, "wiki-cite-anchors.json")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _manifest(wiki_repo_root: Path) -> Dict[str, Any]:
    path = _meta(wiki_repo_root, "wiki-manifest.yaml")
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _parse_line(raw: Any) -> Optional[Tuple[int, int]]:
    text = str(raw or "").strip()
    if not text:
        return None
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", text)
    if not m:
        return None
    start = int(m.group(1))
    end = int(m.group(2) or start)
    return (start, end) if start >= 1 and end >= start else None


def _line_signature(path: str, raw: str, properties_mode: str) -> str:
    # Reuse the same language-aware normalization family as the file fingerprint.
    # A single physical line is enough for alignment; blank/comment-only lines that
    # normalize away are intentionally omitted from the sequence.
    normalized = normalize_text(path, raw, properties_mode=properties_mode)
    normalized = unicodedata.normalize("NFC", normalized).strip("\n")
    if not normalized.strip():
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def source_line_entries(repo_root: Path, rel: str, source_cfg: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str, str]:
    full = resolve_repo_relative(repo_root, rel)
    data = full.read_bytes()
    text, encoding, status = decode_text(data)
    if text is None or status == "uncertain":
        raise ValueError(f"cannot build citation anchors for uncertain encoding: {rel}")
    properties_mode = str(source_cfg.get("properties_normalization") or "keys")
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    entries: List[Dict[str, Any]] = []
    for line_no, raw in enumerate(text.split("\n"), 1):
        sig = _line_signature(rel, raw, properties_mode)
        if sig:
            entries.append({"line": line_no, "sig": sig})
    return entries, encoding, status


def build_anchor_state(
    *,
    wiki_repo_root: Path,
    repo_root: Path,
    source_cfg: Dict[str, Any],
    snapshot_id: str,
) -> Dict[str, Any]:
    manifest = _manifest(wiki_repo_root)
    documents = manifest.get("documents") or []
    citations: List[Dict[str, Any]] = []
    cited_sources: set[str] = set()
    document_hashes: Dict[str, str] = {}

    for doc in documents if isinstance(documents, list) else []:
        if not isinstance(doc, dict):
            continue
        document = str(doc.get("path") or "").replace("\\", "/")
        if document:
            doc_path = wiki_repo_root / Path(document)
            if doc_path.is_file():
                document_hashes[document] = hashlib.sha256(doc_path.read_bytes()).hexdigest()
        rows = doc.get("citations") or []
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or not row.get("file"):
                continue
            line_range = None
            if isinstance(row.get("line_start"), int):
                line_range = (int(row["line_start"]), int(row.get("line_end") or row["line_start"]))
            else:
                line_range = _parse_line(row.get("line_raw"))
            if not line_range:
                continue
            source = str(row["file"]).replace("\\", "/")
            citations.append({
                "document": document,
                "citation_index": index,
                "source": source,
                "line_start": line_range[0],
                "line_end": line_range[1],
            })
            cited_sources.add(source)

    sources: Dict[str, Any] = {}
    for source in sorted(cited_sources):
        full = resolve_repo_relative(repo_root, source)
        if not full.is_file():
            # Quality verification should already have failed. Keep commit fail-closed
            # if this function is called despite a forged receipt.
            raise ValueError(f"cannot commit citation anchors: source missing: {source}")
        entries, encoding, status = source_line_entries(repo_root, source, source_cfg)
        data = full.read_bytes()
        from .source import normalized_hash, sha256_bytes
        norm, _, _ = normalized_hash(source, data, str(source_cfg.get("properties_normalization") or "keys"))
        sources[source] = {
            "content_hash": sha256_bytes(data),
            "normalized_hash": norm,
            "encoding": encoding,
            "decode_status": status,
            "semantic_lines": entries,
        }

    return {
        "schema": ANCHOR_SCHEMA,
        "snapshot_id": snapshot_id,
        "documents": document_hashes,
        "sources": sources,
        "citations": citations,
    }


def write_anchor_state(wiki_repo_root: Path, state: Dict[str, Any]) -> Path:
    path = anchor_path(wiki_repo_root)
    _write_json(path, state)
    return path


def _mapping(old_entries: List[Dict[str, Any]], new_entries: List[Dict[str, Any]]) -> Dict[int, int]:
    old_sigs = [str(x.get("sig") or "") for x in old_entries]
    new_sigs = [str(x.get("sig") or "") for x in new_entries]
    matcher = SequenceMatcher(a=old_sigs, b=new_sigs, autojunk=False)
    mapped: Dict[int, int] = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            old_row = old_entries[block.a + offset]
            new_row = new_entries[block.b + offset]
            mapped[int(old_row["line"])] = int(new_row["line"])
    return mapped


def _relocate_range(start: int, end: int, mapping: Dict[int, int]) -> Optional[Tuple[int, int]]:
    if start in mapping and end in mapping:
        a, b = mapping[start], mapping[end]
        return (a, b) if a <= b else None
    # Cite endpoints should normally be substantive code lines. If an endpoint was
    # a blank/comment line, anchor the range to the nearest mapped substantive lines
    # *inside the old range* rather than guessing outside the cited subject.
    inside = sorted((old, new) for old, new in mapping.items() if start <= old <= end)
    if inside:
        a, b = inside[0][1], inside[-1][1]
        return (a, b) if a <= b else None
    return None


def _tag_attrs(tag: str) -> Tuple[str, Optional[Tuple[int, int]]]:
    p = _PATH_ATTR.search(tag)
    l = _LINE_ATTR.search(tag)
    return (p.group(1).replace("\\", "/") if p else "", _parse_line(l.group(1)) if l else None)


def plan_cosmetic_citation_relocations(
    *,
    wiki_repo_root: Path,
    repo_root: Path,
    source_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Return deterministic line-tag replacements required by current COSMETIC changes.

    This is read-only. ``manifest-refresh`` applies the returned replacements; L1
    verification calls the same planner to ensure the refresh cannot be skipped.
    """
    changeset = _read_json(_meta(wiki_repo_root, "wiki-change-set.json"))
    if not changeset:
        return {"status": "NO_STAGED_CHANGESET", "replacements": [], "cosmetic_sources": []}
    cosmetic = {str(c.get("file") or "").replace("\\", "/") for c in changeset.get("changes", []) if c.get("kind") == "COSMETIC"}
    if not cosmetic:
        return {"status": "NO_COSMETIC_SOURCES", "replacements": [], "cosmetic_sources": []}

    manifest = _manifest(wiki_repo_root)
    live_cited = set()
    for doc in manifest.get("documents") or []:
        if not isinstance(doc, dict):
            continue
        for cite in doc.get("citations") or []:
            if isinstance(cite, dict) and cite.get("file"):
                source = str(cite["file"]).replace("\\", "/")
                if source in cosmetic and (isinstance(cite.get("line_start"), int) or cite.get("line_raw")):
                    live_cited.add(source)
    if not live_cited:
        return {"status": "NO_CITED_COSMETIC_SOURCES", "replacements": [], "cosmetic_sources": sorted(cosmetic)}

    anchors = _read_json(anchor_path(wiki_repo_root))
    baseline = _read_json(_meta(wiki_repo_root, "wiki-snapshot.json"))
    expected_snapshot = str(changeset.get("baseline_snapshot_id") or "")
    if anchors.get("schema") != ANCHOR_SCHEMA or not anchors:
        raise ValueError("citation anchor baseline missing for cited cosmetic source; rebuild/verify once before deterministic cosmetic finalize")
    if str(anchors.get("snapshot_id") or "") != expected_snapshot or str(baseline.get("snapshot_id") or "") != expected_snapshot:
        raise ValueError("citation anchor baseline is stale for the current source baseline")

    old_sources = anchors.get("sources") or {}
    current_maps: Dict[str, Dict[int, int]] = {}
    for source in sorted(live_cited):
        old = old_sources.get(source)
        if not isinstance(old, dict):
            raise ValueError(f"citation anchor source missing from baseline: {source}")
        # COSMETIC means normalized identity must be unchanged. Validate the anchor
        # against the staged BEFORE fingerprint before trusting line alignment.
        change = next((c for c in changeset.get("changes", []) if c.get("file") == source and c.get("kind") == "COSMETIC"), None)
        before_norm = str(((change or {}).get("before") or {}).get("normalized_hash") or "")
        after_norm = str(((change or {}).get("after") or {}).get("normalized_hash") or "")
        if not before_norm or before_norm != after_norm or str(old.get("normalized_hash") or "") != before_norm:
            raise ValueError(f"citation anchor normalized identity mismatch: {source}")
        new_entries, _, _ = source_line_entries(repo_root, source, source_cfg)
        current_maps[source] = _mapping(list(old.get("semantic_lines") or []), new_entries)

    anchors_by_doc: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for row in anchors.get("citations") or []:
        if not isinstance(row, dict) or str(row.get("source") or "") not in live_cited:
            continue
        anchors_by_doc.setdefault(str(row.get("document") or ""), {})[int(row.get("citation_index") or 0)] = row

    replacements: List[Dict[str, Any]] = []
    baseline_doc_hashes = anchors.get("documents") if isinstance(anchors.get("documents"), dict) else {}
    for document, rows in anchors_by_doc.items():
        path = wiki_repo_root / Path(document)
        if not path.is_file():
            raise ValueError(f"citation anchor document missing: {document}")
        # Automatic relocation is only safe while the Wiki document itself is byte-identical
        # to the committed anchor subject. If an AI/human semantic update changed the document
        # (including citation order), the new citations are authoritative and L1 will validate
        # their current paths/lines after manifest refresh. Never apply stale positional anchors.
        committed_doc_hash = str(baseline_doc_hashes.get(document) or "")
        current_doc_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if committed_doc_hash and current_doc_hash != committed_doc_hash:
            continue
        text = path.read_text(encoding="utf-8")
        tags = list(_CITE_TAG.finditer(text))
        for index, anchor in sorted(rows.items()):
            if index >= len(tags):
                raise ValueError(f"citation anchor occurrence missing: {document}#{index}")
            match = tags[index]
            source, current_range = _tag_attrs(match.group(0))
            expected_source = str(anchor.get("source") or "")
            old_range = (int(anchor.get("line_start") or 0), int(anchor.get("line_end") or 0))
            # If AI already changed the citation sequence during a semantic update,
            # do not overwrite its prose-level decision with a stale positional anchor.
            if source != expected_source or current_range != old_range:
                continue
            new_range = _relocate_range(old_range[0], old_range[1], current_maps[expected_source])
            if not new_range:
                raise ValueError(f"cannot deterministically relocate citation: {document}#{index} {expected_source}:{old_range[0]}-{old_range[1]}")
            if new_range == old_range:
                continue
            old_tag = match.group(0)
            line_text = str(new_range[0]) if new_range[0] == new_range[1] else f"{new_range[0]}-{new_range[1]}"
            new_tag = _LINE_ATTR.sub(lambda m: f'line="{line_text}"', old_tag, count=1)
            replacements.append({
                "document": document,
                "citation_index": index,
                "source": expected_source,
                "old_line_start": old_range[0],
                "old_line_end": old_range[1],
                "new_line_start": new_range[0],
                "new_line_end": new_range[1],
                "start": match.start(),
                "end": match.end(),
                "old_tag": old_tag,
                "new_tag": new_tag,
            })

    return {"status": "READY", "replacements": replacements, "cosmetic_sources": sorted(cosmetic)}


def apply_cosmetic_citation_relocations(
    *,
    wiki_repo_root: Path,
    repo_root: Path,
    source_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    plan = plan_cosmetic_citation_relocations(wiki_repo_root=wiki_repo_root, repo_root=repo_root, source_cfg=source_cfg)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in plan.get("replacements") or []:
        grouped.setdefault(str(row["document"]), []).append(row)
    for document, rows in grouped.items():
        path = wiki_repo_root / Path(document)
        text = path.read_text(encoding="utf-8")
        # Apply from the back so byte/character offsets remain valid.
        for row in sorted(rows, key=lambda x: int(x["start"]), reverse=True):
            start, end = int(row["start"]), int(row["end"])
            if text[start:end] != row["old_tag"]:
                raise ValueError(f"citation tag changed during deterministic relocation: {document}#{row['citation_index']}")
            text = text[:start] + str(row["new_tag"]) + text[end:]
        path.write_text(text, encoding="utf-8", newline="\n")
    return {
        "status": plan.get("status"),
        "cosmetic_sources": plan.get("cosmetic_sources") or [],
        "relocated": len(plan.get("replacements") or []),
        "documents": sorted(grouped),
    }
