# -*- coding: utf-8 -*-
"""Snapshot scanning, change classification, and fail-safe baseline staging."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
import hashlib
import json
import os
import tempfile

from .source import (discover_source_files, normalized_hash,
                     read_source_bytes, resolve_repo_relative, sha256_bytes,
                     source_selected, _is_excluded)
from .stable_source import SourceError, bind_source, source_view

SNAPSHOT_SCHEMA = "tp-spec.wiki-snapshot/v1"
CHANGESET_SCHEMA = "tp-spec.wiki-changeset/v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            tmp = Path(stream.name)
            stream.write(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, path)
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()



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


def _digest(value: Any) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def prepare_source_config(
    repo_root: Path, wiki_repo_root: Path, source_cfg: Dict[str, Any],
    snapshot_cfg: Dict[str, Any], quality_cfg: Dict[str, Any], coverage_cfg: Dict[str, Any],
    *, staged: bool = False, committed: bool = False,
) -> Dict[str, Any]:
    """Resolve once. Follow-up commands consume the staged SHA, not a moved ref."""
    paths = snapshot_paths(wiki_repo_root)
    recorded = {}
    if committed:
        recorded = _read_json(paths["baseline"])
    elif staged:
        recorded = _read_json(paths["pending"]) or _read_json(paths["baseline"])
    public = {k: v for k, v in source_cfg.items() if not k.startswith("_")}
    result = bind_source(repo_root, public, identity=recorded.get("source") or None)
    source_rules = {name: sha256_bytes((Path(__file__).parent / name).read_bytes())
                    for name in ("source.py", "stable_source.py")}
    result["_source_policy_digest"] = _digest({"config": public, "rules": source_rules})
    base = Path(__file__).resolve().parents[2]
    rule_paths = set((base / "cli/wiki").glob("*.py"))
    for folder in ("wiki/rules", "agents/tp-wiki", "automation/wiki"):
        rule_paths.update((base / folder).rglob("*.md"))
    rule_paths.update((base / "wiki/schema").glob("*.yaml"))
    rules = {path.relative_to(base).as_posix(): sha256_bytes(path.read_bytes()) for path in sorted(rule_paths)}
    result["_maintenance_digest"] = _digest({"source": public, "snapshot": snapshot_cfg,
        "quality": quality_cfg, "coverage": coverage_cfg, "rules": rules})
    if (staged and not committed and paths["pending"].is_file() and
            recorded.get("maintenance_digest") != result["_maintenance_digest"]):
        raise SourceError("MAINTENANCE_POLICY_CHANGED: run wiki scan/maintain again before consuming staged results")
    if recorded and not recorded.get("source") and source_view(repo_root, result).mode == "GIT_REF":
        raise SourceError("SOURCE_INITIALIZATION_REQUIRED: legacy baseline has no commit; run wiki maintain --initialize-source")
    return result


def build_current_snapshot(repo_id: str, repo_root: Path, source_cfg: Dict[str, Any], old: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Git reuses unchanged blob fingerprints; filesystem always hashes actual bytes."""
    view = source_view(repo_root, source_cfg)
    old = old or {}
    source_policy = source_cfg.get("_source_policy_digest") or _digest({k: v for k, v in source_cfg.items() if not k.startswith("_")})
    same_policy = old.get("source_policy_digest") == source_policy
    old_files = old.get("files") or {}
    files: Dict[str, Any] = {}
    properties_mode = str(source_cfg.get("properties_normalization") or "keys")
    git_changes = None
    if view.mode == "GIT_REF" and old.get("source"):
        # Check history even when a config change requires a fresh inventory.
        git_changes = view.diff(old["source"])
    incremental = git_changes is not None and same_policy
    if incremental:
        files = {rel: dict(row) for rel, row in old_files.items()}
        for change in git_changes:
            rel = change["file"]
            if change["after_mode"] == "160000" and not _is_excluded(rel, source_cfg):
                raise SourceError(f"GITLINK_NEEDS_REVIEW: {rel}; register and scope it explicitly")
            if change["after_mode"] == "000000" or not source_selected(rel, source_cfg):
                files.pop(rel, None)
                continue
            if change["after_mode"] not in {"100644", "100755"}:
                raise SourceError(f"GIT_ENTRY_UNSUPPORTED: {rel} mode={change['after_mode']}")
            data = view.blob(change["after_oid"])
            norm, encoding, decode_status = normalized_hash(rel, data, properties_mode)
            files[rel] = {"size": len(data), "mtime_ns": 0, "content_hash": sha256_bytes(data),
                          "normalized_hash": norm, "encoding": encoding, "decode_status": decode_status,
                          "git_blob": change["after_oid"], "git_mode": change["after_mode"]}
    else:
        for rel in discover_source_files(repo_root, source_cfg):
            data = read_source_bytes(repo_root, rel, source_cfg)
            raw_hash = sha256_bytes(data)
            mtime_ns = 0 if view.mode == "GIT_REF" else resolve_repo_relative(repo_root, rel).stat().st_mtime_ns
            previous = old_files.get(rel) or {}
            if same_policy and previous.get("content_hash") == raw_hash:
                row = dict(previous)
                row.update(size=len(data), mtime_ns=mtime_ns)
            else:
                norm, encoding, decode_status = normalized_hash(rel, data, properties_mode)
                row = {"size": len(data), "mtime_ns": mtime_ns, "content_hash": raw_hash,
                       "normalized_hash": norm, "encoding": encoding, "decode_status": decode_status}
            if view.mode == "GIT_REF":
                mode, _, oid = view.tree()[rel]
                row.update(git_blob=oid, git_mode=mode)
            files[rel] = row
    return {
        "schema": SNAPSHOT_SCHEMA, "repo_id": repo_id, "captured_at": utc_now(),
        "snapshot_id": _snapshot_id(repo_id, files), "files": files,
        "source": view.identity(), "source_policy_digest": source_policy,
        "maintenance_digest": source_cfg.get("_maintenance_digest", ""),
        "scan_mode": "COMMIT_DIFF" if incremental else ("GIT_INVENTORY" if view.mode == "GIT_REF" else "FILESYSTEM_HASH"),
    }


def no_change_fast_path(wiki_repo_root: Path, repo_root: Path, source_cfg: Dict[str, Any], *, repair: bool = False) -> Dict[str, Any] | None:
    """No source discovery, planner or AI dispatch is reachable on this path."""
    if repair:
        return None
    paths = snapshot_paths(wiki_repo_root)
    view = source_view(repo_root, source_cfg)
    if view.mode != "GIT_REF":
        return None
    if any(paths[name].exists() for name in ("pending", "changeset", "plan", "verification", "audit_plan", "audit")):
        return None
    baseline = _read_json(paths["baseline"])
    completion = baseline.get("completion") or {}
    if (baseline.get("source") != view.identity() or not baseline.get("maintenance_digest") or
            baseline["maintenance_digest"] != source_cfg.get("_maintenance_digest") or
            completion.get("status") != "SUCCESS" or
            completion.get("subject_digest") != wiki_subject_digest(wiki_repo_root)):
        return None
    return {"state": "NO_CHANGE", "fast_path": True, "source": view.identity(),
            "snapshot_id": baseline.get("snapshot_id"), "plan": None,
            "requires_ai_update": False, "llm_dispatch": False, "source_scanned": False}


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


def stage_scan(
    repo_id: str, repo_root: Path, wiki_repo_root: Path,
    source_cfg: Dict[str, Any], snapshot_cfg: Dict[str, Any], *,
    initialize_source: bool = False, repair: bool = False, documents: List[str] | None = None,
) -> Dict[str, Any]:
    paths = snapshot_paths(wiki_repo_root)
    baseline = _read_json(paths["baseline"])
    view = source_view(repo_root, source_cfg)
    prior_source = baseline.get("source") or {}
    # Legacy non-Git hashes remain usable without inventing a commit or requiring
    # an extra migration permission. Git adoption/scope changes need explicit init.
    migration = bool(baseline and (
        (not prior_source and view.mode == "GIT_REF") or
        (prior_source and (prior_source.get("source_mode") != view.mode or
                           prior_source.get("repo_prefix", "") != view.prefix))))
    if migration and not initialize_source:
        raise SourceError("SOURCE_INITIALIZATION_REQUIRED: legacy/changed source identity; run wiki scan/maintain --initialize-source; old baseline is preserved until validation succeeds")
    if documents and not repair:
        raise ValueError("--document requires --repair")
    if repair:
        from .manifest import load_manifest
        declared = {d.get("path") for d in load_manifest(wiki_repo_root).get("documents", []) if isinstance(d, dict)}
        if set(documents or []) - declared:
            raise ValueError("repair document is not declared in the current Wiki manifest")
    current = build_current_snapshot(repo_id, repo_root, source_cfg, old={} if migration else baseline)
    classified = classify_changes({} if migration else baseline, current, snapshot_cfg)
    classified["initial"] = not bool(baseline) or migration
    policy_changed = bool(baseline and baseline.get("maintenance_digest") != current.get("maintenance_digest"))
    completion = baseline.get("completion") or {}
    subject_changed = bool(completion.get("subject_digest") and completion["subject_digest"] != wiki_subject_digest(wiki_repo_root))
    reasons = []
    if migration:
        reasons.append("SOURCE_INITIALIZATION")
    if policy_changed:
        reasons.append("MAINTENANCE_POLICY_CHANGED")
    if subject_changed:
        reasons.append("WIKI_SUBJECT_CHANGED")
    if baseline and completion.get("status") != "SUCCESS":
        reasons.append("PREVIOUS_SUCCESS_NOT_RECORDED")
    if repair:
        reasons.append("EXPLICIT_REPAIR")
    if not paths["changeset"].is_file() and any(
            _read_json(paths[name]).get("result") == "FAIL" for name in ("verification", "audit")):
        reasons.append("PREVIOUS_VALIDATION_FAILED")
    request = {"baseline": baseline.get("snapshot_id"), "candidate": current["snapshot_id"],
               "source": current["source"], "maintenance_digest": current["maintenance_digest"],
               "refresh_reasons": reasons, "repair_documents": sorted(set(documents or []))}
    change_set_id = _digest(request)[:24]
    existing = _read_json(paths["changeset"])
    previous_pending = _read_json(paths["pending"])
    # A retry keeps the original repair scope and its receipts. Wiki edits during
    # a pending run are expected, not a reason to restage and lose a valid audit.
    resumable = (existing and previous_pending and
        existing.get("baseline_snapshot_id") == baseline.get("snapshot_id") and
        existing.get("candidate_snapshot_id") == previous_pending.get("snapshot_id") and
        existing.get("source") == previous_pending.get("source") and
        existing.get("maintenance_digest") == previous_pending.get("maintenance_digest") and
        previous_pending.get("snapshot_id") == _snapshot_id(repo_id, previous_pending.get("files") or {}) and
        previous_pending.get("snapshot_id") == current["snapshot_id"] and
        previous_pending.get("source") == current["source"] and
        previous_pending.get("maintenance_digest") == current["maintenance_digest"])
    if resumable and (not repair or existing.get("repair_documents", []) == request["repair_documents"] and "EXPLICIT_REPAIR" in existing.get("refresh_reasons", [])):
        return existing
    changeset = {
        "schema": CHANGESET_SCHEMA, "repo_id": repo_id, "repo_root": str(repo_root),
        "wiki_repo_root": str(wiki_repo_root), "created_at": utc_now(),
        "change_set_id": change_set_id, "baseline_snapshot_id": baseline.get("snapshot_id"),
        "candidate_snapshot_id": current["snapshot_id"], "baseline_source": baseline.get("source"),
        "source": current["source"], "maintenance_digest": current["maintenance_digest"],
        "refresh_reasons": reasons, "repair_documents": request["repair_documents"],
        "scan_mode": current["scan_mode"], **classified,
    }
    wiki_repo_root.mkdir(parents=True, exist_ok=True)
    _write_json(paths["pending"], current)
    _write_json(paths["changeset"], changeset)
    for name in ("plan", "verification", "audit_plan", "audit"):
        if paths[name].exists():
            paths[name].unlink()
    return changeset


def validate_staged_source(wiki_repo_root: Path, repo_root: Path, source_cfg: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    paths = snapshot_paths(wiki_repo_root)
    changeset = _read_json(paths["changeset"])
    pending = _read_json(paths["pending"])
    if not changeset or not pending:
        raise ValueError("no complete staged Wiki scan; run wiki scan first")
    if (changeset.get("candidate_snapshot_id") != pending.get("snapshot_id") or
            changeset.get("source") != pending.get("source") or
            changeset.get("maintenance_digest") != pending.get("maintenance_digest") or
            pending.get("snapshot_id") != _snapshot_id(str(pending.get("repo_id") or ""), pending.get("files") or {})):
        raise ValueError("staged Wiki scan is inconsistent; run wiki scan again")
    if pending.get("source") != source_view(repo_root, source_cfg).identity():
        raise ValueError("source is not pinned to the staged snapshot")
    if pending.get("maintenance_digest") != source_cfg.get("_maintenance_digest", ""):
        raise ValueError("maintenance configuration/rules changed after scan; run wiki scan again")
    return changeset, pending


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
    if repo_root is not None and source_cfg is not None:
        changeset, pending = validate_staged_source(wiki_repo_root, repo_root, source_cfg)
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
    verification: Dict[str, Any] = {}
    audit: Dict[str, Any] = {}
    current_subject = wiki_subject_digest(wiki_repo_root)
    if require_verification:
        verification = _read_json(paths["verification"])
        if verification.get("change_set_id") != changeset.get("change_set_id") or verification.get("result") != "PASS":
            raise ValueError("baseline blocked: current change set has no PASS verification")
        current_subject = wiki_subject_digest(wiki_repo_root)
        if verification.get("source") != pending.get("source") or verification.get("maintenance_digest") != pending.get("maintenance_digest"):
            raise ValueError("baseline blocked: verification does not bind the staged source and maintenance policy")
        if verification.get("subject_digest") != current_subject:
            raise ValueError("baseline blocked: Wiki/manifest changed after verification; run wiki verify again")
        requires_audit = bool(verification.get("semantic_audit_required"))
        if requires_audit:
            audit = _read_json(paths["audit"])
            if audit.get("change_set_id") != changeset.get("change_set_id") or audit.get("result") != "PASS":
                raise ValueError("baseline blocked: semantic audit PASS required for this change set")
            if audit.get("source") != pending.get("source") or audit.get("maintenance_digest") != pending.get("maintenance_digest"):
                raise ValueError("baseline blocked: semantic audit does not bind the staged source and policy")
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
    plan = _read_json(paths["plan"])
    pending["completion"] = {
        "status": "SUCCESS" if require_verification else "UNVERIFIED",
        "committed_at": utc_now(), "change_set_id": changeset.get("change_set_id"),
        "subject_digest": current_subject,
        "verification": {k: verification.get(k) for k in ("result", "verified_at", "subject_digest", "semantic_audit_required")},
        "audit": {k: audit.get(k) for k in ("result", "recorded_at", "subject_digest", "documents", "topology_reviewed")} if audit else None,
        "affected_documents": [d.get("document") for d in plan.get("affected_documents", [])],
    }
    _write_json(paths["baseline"], pending)
    # The baseline is already committed. A failed receipt cleanup must not be
    # reported as an uncommitted run; maintain will revalidate remaining state.
    cleanup_pending = []
    for name in ("verification", "audit_plan", "audit", "plan", "changeset", "pending"):
        try:
            paths[name].unlink(missing_ok=True)
        except OSError as exc:
            cleanup_pending.append({"name": name, "error": str(exc)})
    return {"result": "COMMITTED", "snapshot_id": pending.get("snapshot_id"),
            "source": pending.get("source"), "baseline_advanced": True,
            "cleanup_pending": cleanup_pending}
