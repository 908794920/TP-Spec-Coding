# -*- coding: utf-8 -*-
"""Snapshot scanning, change classification, and fail-safe baseline staging."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
import hashlib
import json
import os

from .source import discover_source_files, fingerprint_file, normalized_hash, resolve_repo_relative, sha256_bytes

SNAPSHOT_SCHEMA = "ai-work.wiki-snapshot/v1"
CHANGESET_SCHEMA = "ai-work.wiki-changeset/v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)



_VOLATILE_META_NAMES = {
    "wiki-snapshot.json",
    "wiki-snapshot.pending.json",
    "wiki-change-set.json",
    "wiki-rebuild-plan.json",
    "wiki-verification.json",
    "wiki-semantic-audit-plan.json",
    "wiki-semantic-audit.json",
    "wiki-cite-anchors.json",
    "wiki-coverage.json",
}

def wiki_subject_digest(wiki_repo_root: Path) -> str:
    """Bind verification/audit to the exact durable Wiki subject, excluding run receipts."""
    digest = hashlib.sha256()
    if not wiki_repo_root.exists():
        return digest.hexdigest()
    files = []
    for path in wiki_repo_root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(wiki_repo_root).as_posix()
        if rel.startswith("meta/") and path.name in _VOLATILE_META_NAMES:
            continue
        files.append((rel, path))
    for rel, path in sorted(files):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\n")
    return digest.hexdigest()

def snapshot_paths(wiki_repo_root: Path) -> Dict[str, Path]:
    meta = wiki_repo_root / "meta"
    return {
        "baseline": meta / "wiki-snapshot.json",
        "pending": meta / "wiki-snapshot.pending.json",
        "changeset": meta / "wiki-change-set.json",
        "plan": meta / "wiki-rebuild-plan.json",
        "verification": meta / "wiki-verification.json",
        "audit_plan": meta / "wiki-semantic-audit-plan.json",
        "audit": meta / "wiki-semantic-audit.json",
        "anchors": meta / "wiki-cite-anchors.json",
    }


def _snapshot_id(repo_id: str, files: Dict[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(repo_id.encode("utf-8"))
    for rel in sorted(files):
        row = files[rel]
        digest.update(rel.encode("utf-8"))
        digest.update(str(row.get("content_hash", "")).encode("ascii", "ignore"))
        digest.update(str(row.get("normalized_hash", "")).encode("ascii", "ignore"))
    return digest.hexdigest()[:24]


def build_current_snapshot(repo_id: str, repo_root: Path, source_cfg: Dict[str, Any], old: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build a source snapshot without trusting mtime/size as content identity.

    Re-downloads, archive extraction and sync tools can preserve timestamps while replacing
    bytes. We therefore SHA-256 every eligible file on each scan. If the raw hash is still
    identical, the prior normalized fingerprint/encoding result is reused so unchanged files
    are not decoded/normalized again. This keeps the old fast-metadata information without
    allowing same-size/same-mtime edits to disappear.
    """
    old_files = (old or {}).get("files", {}) if isinstance(old, dict) else {}
    files: Dict[str, Any] = {}
    properties_mode = str(source_cfg.get("properties_normalization") or "keys")
    for rel in discover_source_files(repo_root, source_cfg):
        full = resolve_repo_relative(repo_root, rel)
        stat = full.stat()
        data = full.read_bytes()
        raw_hash = sha256_bytes(data)
        previous = old_files.get(rel) if isinstance(old_files, dict) else None
        if previous and str(previous.get("content_hash") or "").lower() == raw_hash:
            row = dict(previous)
            row["size"] = stat.st_size
            row["mtime_ns"] = stat.st_mtime_ns
            row["content_hash"] = raw_hash
            files[rel] = row
            continue
        norm, encoding, decode_status = normalized_hash(rel, data, properties_mode=properties_mode)
        files[rel] = {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "content_hash": raw_hash,
            "normalized_hash": norm,
            "encoding": encoding,
            "decode_status": decode_status,
        }
    return {
        "schema": SNAPSHOT_SCHEMA,
        "repo_id": repo_id,
        "captured_at": utc_now(),
        "snapshot_id": _snapshot_id(repo_id, files),
        "files": files,
    }


def classify_changes(old: Dict[str, Any], current: Dict[str, Any], snapshot_cfg: Dict[str, Any]) -> Dict[str, Any]:
    old_files = old.get("files", {}) if old else {}
    new_files = current.get("files", {})
    initial = not bool(old_files)
    changes: List[Dict[str, Any]] = []

    for rel in sorted(set(old_files) | set(new_files)):
        before = old_files.get(rel)
        after = new_files.get(rel)
        if before is None:
            changes.append({"file": rel, "kind": "STRUCTURAL", "reason": "added", "after": after})
            continue
        if after is None:
            changes.append({"file": rel, "kind": "DELETED", "reason": "deleted", "before": before})
            continue
        if before.get("content_hash") == after.get("content_hash"):
            if before.get("mtime_ns") != after.get("mtime_ns"):
                changes.append({"file": rel, "kind": "TOUCHED_ONLY", "reason": "metadata-only", "before": before, "after": after})
            continue
        if before.get("normalized_hash") == after.get("normalized_hash"):
            kind = "COSMETIC"
            reason = "normalized-equivalent"
        elif after.get("decode_status") == "uncertain" or before.get("decode_status") == "uncertain":
            kind = "UNCERTAIN"
            reason = "undecodable-or-ambiguous"
        else:
            kind = "SEMANTIC"
            reason = "normalized-content-changed"
        changes.append({"file": rel, "kind": kind, "reason": reason, "before": before, "after": after})

    counts: Dict[str, int] = {}
    for change in changes:
        counts[change["kind"]] = counts.get(change["kind"], 0) + 1
    total_current = max(1, len(new_files))
    raw_changed = sum(v for k, v in counts.items() if k not in {"TOUCHED_ONLY"})
    semantic_like = sum(counts.get(k, 0) for k in ("SEMANTIC", "STRUCTURAL", "DELETED", "UNCERTAIN"))
    cosmetic = counts.get("COSMETIC", 0)
    mass_min = int(snapshot_cfg.get("mass_change_min_files", 50))
    mass_ratio = float(snapshot_cfg.get("mass_change_ratio", 0.35))
    bulk_cosmetic_ratio = float(snapshot_cfg.get("bulk_cosmetic_ratio", 0.80))
    changed_ratio = raw_changed / total_current
    cosmetic_ratio = cosmetic / max(1, raw_changed)

    guard = {"status": "OK", "changed_ratio": changed_ratio, "cosmetic_ratio": cosmetic_ratio}
    if not initial and raw_changed >= mass_min and changed_ratio >= mass_ratio:
        if cosmetic_ratio >= bulk_cosmetic_ratio and semantic_like < max(5, int(raw_changed * (1 - bulk_cosmetic_ratio)) + 1):
            guard["status"] = "BULK_COSMETIC_DRIFT"
        else:
            guard["status"] = "MASS_CHANGE_REVIEW_REQUIRED"

    return {
        "initial": initial,
        "counts": counts,
        "changes": changes,
        "guard": guard,
        "source_file_count": len(new_files),
        "raw_changed_count": raw_changed,
        "semantic_like_count": semantic_like,
    }


def stage_scan(repo_id: str, repo_root: Path, wiki_repo_root: Path, source_cfg: Dict[str, Any], snapshot_cfg: Dict[str, Any]) -> Dict[str, Any]:
    paths = snapshot_paths(wiki_repo_root)
    baseline = _read_json(paths["baseline"])
    current = build_current_snapshot(repo_id, repo_root, source_cfg, old=baseline)
    classified = classify_changes(baseline, current, snapshot_cfg)
    change_set_id = hashlib.sha256((str(baseline.get("snapshot_id", "none")) + ":" + current["snapshot_id"]).encode("utf-8")).hexdigest()[:24]
    changeset = {
        "schema": CHANGESET_SCHEMA,
        "repo_id": repo_id,
        "repo_root": str(repo_root),
        "wiki_repo_root": str(wiki_repo_root),
        "created_at": utc_now(),
        "change_set_id": change_set_id,
        "baseline_snapshot_id": baseline.get("snapshot_id"),
        "candidate_snapshot_id": current["snapshot_id"],
        **classified,
    }
    wiki_repo_root.mkdir(parents=True, exist_ok=True)
    _write_json(paths["pending"], current)
    _write_json(paths["changeset"], changeset)
    # Any previous plan/verification/audit belongs to a different staged scan.
    for name in ("plan", "verification", "audit_plan", "audit"):
        p = paths[name]
        if p.exists():
            p.unlink()
    return changeset


def discard_staged(wiki_repo_root: Path) -> None:
    """Discard transient run state while preserving the committed baseline."""
    paths = snapshot_paths(wiki_repo_root)
    for name in ("pending", "changeset", "plan", "verification", "audit_plan", "audit"):
        p = paths[name]
        if p.exists():
            p.unlink()


def read_staged(wiki_repo_root: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    paths = snapshot_paths(wiki_repo_root)
    return _read_json(paths["changeset"]), _read_json(paths["pending"])


def commit_baseline(wiki_repo_root: Path, *, repo_id: str | None = None, repo_root: Path | None = None, source_cfg: Dict[str, Any] | None = None, require_verification: bool = True) -> Dict[str, Any]:
    paths = snapshot_paths(wiki_repo_root)
    changeset = _read_json(paths["changeset"])
    pending = _read_json(paths["pending"])
    if not changeset or not pending:
        raise ValueError("no staged wiki scan; run wiki scan first")
    guard_status = str((changeset.get("guard") or {}).get("status") or "OK")
    if guard_status == "MASS_CHANGE_REVIEW_REQUIRED":
        plan = _read_json(paths["plan"])
        if plan.get("change_set_id") != changeset.get("change_set_id") or not plan.get("mass_change_approved"):
            raise ValueError("baseline blocked: mass-change guard has no explicit approved plan")
    if any(c.get("kind") == "UNCERTAIN" for c in changeset.get("changes", [])):
        raise ValueError("baseline blocked: uncertain source changes remain unresolved")
    if repo_root is not None and source_cfg is not None:
        rid = repo_id or str(changeset.get("repo_id") or pending.get("repo_id") or "repo")
        current = build_current_snapshot(rid, repo_root, source_cfg, old=pending)
        if current.get("snapshot_id") != pending.get("snapshot_id"):
            raise ValueError("baseline blocked: source changed after staged scan; run wiki scan again")
    if require_verification:
        verification = _read_json(paths["verification"])
        if verification.get("change_set_id") != changeset.get("change_set_id") or verification.get("result") != "PASS":
            raise ValueError("baseline blocked: current change set has no PASS verification")
        current_subject = wiki_subject_digest(wiki_repo_root)
        if verification.get("subject_digest") != current_subject:
            raise ValueError("baseline blocked: Wiki/manifest changed after verification; run wiki verify again")
        requires_audit = bool(verification.get("semantic_audit_required"))
        if requires_audit:
            audit = _read_json(paths["audit"])
            if audit.get("change_set_id") != changeset.get("change_set_id") or audit.get("result") != "PASS":
                raise ValueError("baseline blocked: semantic audit PASS required for this change set")
            if audit.get("subject_digest") != current_subject:
                raise ValueError("baseline blocked: semantic audit does not bind the current Wiki subject")
    # Build the next cite-anchor baseline *before* advancing the source snapshot.
    # The anchor file carries the candidate snapshot_id; if a crash occurs before
    # the baseline replace, the mismatch makes it unusable rather than silently
    # binding old source state to new line anchors.
    if repo_root is not None and source_cfg is not None:
        from .anchors import build_anchor_state, write_anchor_state
        anchor_state = build_anchor_state(
            wiki_repo_root=wiki_repo_root, repo_root=repo_root, source_cfg=source_cfg,
            snapshot_id=str(pending.get("snapshot_id") or ""),
        )
        write_anchor_state(wiki_repo_root, anchor_state)
    _write_json(paths["baseline"], pending)
    for name in ("pending", "changeset", "plan", "verification", "audit_plan", "audit"):
        p = paths[name]
        if p.exists():
            p.unlink()
    return {"result": "COMMITTED", "snapshot_id": pending.get("snapshot_id")}
