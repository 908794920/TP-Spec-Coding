"""Durable subject identities captured at successful baseline commits."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import hashlib
import json
import re

import yaml

MANIFEST = "meta/wiki-manifest.yaml"


def subject_files(root: Path) -> dict[str, str]:
    from .snapshot import _VOLATILE_META_NAMES
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and not (
                p.relative_to(root).as_posix().startswith("meta/") and p.name in _VOLATILE_META_NAMES)}


def files_digest(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for rel, value in sorted(files.items()):
        digest.update(rel.encode("utf-8") + b"\0" + bytes.fromhex(value) + b"\n")
    return digest.hexdigest()


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _manifest_parts(data: bytes) -> dict:
    manifest = yaml.safe_load(data)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("documents"), list):
        raise ValueError("manifest documents are unavailable")
    global_fields = deepcopy(manifest)
    documents = {}
    for doc in global_fields.pop("documents"):
        if not isinstance(doc, dict) or not isinstance(doc.get("path"), str):
            raise ValueError("manifest document identities are invalid")
        rel = doc["path"].replace("\\", "/")
        if rel in documents:
            raise ValueError("manifest document identities are duplicated")
        doc["path"] = rel
        # These fields are derived from the exact document/source by manifest-refresh.
        for key in ("content_hash", "sections", "citations"):
            doc.pop(key, None)
        for dep in doc.get("dependencies") or []:
            if isinstance(dep, dict):
                for key in ("content_hash", "normalized_hash", "encoding"):
                    dep.pop(key, None)
        documents[rel] = _hash(doc)
    machine = {key: global_fields.pop(key, None) for key in
               ("source", "source_change_set_id", "candidate_snapshot_id")}
    global_fields.pop("generated_at", None)
    provenance = global_fields.get("provenance") or {}
    if not isinstance(provenance, dict):
        raise ValueError("manifest provenance is not a mapping")
    refresh = provenance.get("manifest_refresh")
    if isinstance(refresh, dict):
        refresh.pop("refreshed_at", None)
    stats = global_fields.get("stats")
    if isinstance(stats, dict):
        for key in ("total_documents", "total_citations", "cite_relocations_last_refresh"):
            stats.pop(key, None)
    return {"global": _hash(global_fields), "documents": documents, "machine": machine}


def capture_subject(root: Path) -> dict:
    manifest = (root / MANIFEST).read_bytes()
    files = subject_files(root)
    if files.get(MANIFEST) != hashlib.sha256(manifest).hexdigest():
        raise ValueError("manifest changed while capturing durable subject inventory")
    return {"format": 1, "files": files, "manifest": _manifest_parts(manifest)}


def subject_scope(root: Path, changeset: dict) -> dict:
    """Only a success-captured inventory can narrow an unexpected subject change."""
    from .snapshot import _read_json, snapshot_paths
    baseline = _read_json(snapshot_paths(root)["baseline"])
    completion = baseline.get("completion") or {}
    before = completion.get("subject_inventory") or {}

    def unproven(reason):
        return {"status": "UNPROVEN", "documents": [], "reason": reason}

    try:
        current_files = subject_files(root)
        if (completion.get("status") == "SUCCESS" and
                files_digest(current_files) == completion.get("subject_digest")):
            return {"status": "EXACT", "documents": [], "reason": "successful durable bytes restored"}
        if before.get("format") != 1 or not isinstance(before.get("files"), dict):
            return unproven("successful baseline has no matching durable subject inventory")
        files = before["files"]
        if (completion.get("status") != "SUCCESS" or before.get("format") != 1 or
                not isinstance(files, dict) or any(not isinstance(k, str) or
                    not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for k, v in files.items()) or
                files_digest(files) != completion.get("subject_digest")):
            return unproven("successful baseline has no matching durable subject inventory")
        current = capture_subject(root)
        changed = {rel for rel in set(files) | set(current["files"])
                   if files.get(rel) != current["files"].get(rel)}
        if not changed:
            return {"status": "EXACT", "documents": [], "reason": "successful durable bytes restored"}
        unknown = changed - {MANIFEST} - {rel for rel in changed if rel.endswith(".md") and not rel.startswith("meta/")}
        if unknown:
            return unproven("durable paths outside Wiki documents changed: " + ", ".join(sorted(unknown)))
        deleted = {rel for rel in changed if rel != MANIFEST and rel not in current["files"]}
        if deleted:
            return unproven("deleted Wiki documents need an explicit structural review: " + ", ".join(sorted(deleted)))
        old_manifest, new_manifest = before["manifest"], current["manifest"]
        if old_manifest["global"] != new_manifest["global"]:
            return unproven("global manifest declarations changed")
        for key, expected in (("source", changeset.get("source")),
                              ("source_change_set_id", changeset.get("change_set_id")),
                              ("candidate_snapshot_id", changeset.get("candidate_snapshot_id"))):
            actual = new_manifest["machine"][key]
            if actual != old_manifest["machine"][key] and actual != expected:
                return unproven("manifest machine identity does not match the staged " + key)
        old_docs, new_docs = old_manifest["documents"], new_manifest["documents"]
        if set(old_docs) - set(new_docs):
            return unproven("manifest document declarations were removed")
        affected = (changed - {MANIFEST}) | {rel for rel in set(old_docs) | set(new_docs)
                                          if old_docs.get(rel) != new_docs.get(rel)}
        return {"status": "DOCUMENTS" if affected else "MACHINE_ONLY",
                "documents": sorted(affected), "reason": "difference from successful subject inventory"}
    except (KeyError, TypeError, ValueError, OSError, yaml.YAMLError):
        return unproven("durable subject inventory or current manifest is unavailable/invalid")
