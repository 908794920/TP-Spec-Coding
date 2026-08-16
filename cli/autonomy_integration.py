# -*- coding: utf-8 -*-
"""Prepare/review/apply bridge from Autonomous staging to Canonical Git repos.

Prepare is always isolated. Apply is a user-session operation with an explicit
integration id; it uses a journaled, recoverable per-repository ref transition.
Multiple Git repositories are coordinated but are not claimed to be ACID atomic.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from . import autonomy_batch, autonomy_git, autonomy_profile
from . import db as dbmod
from .path_identity import canonical_path, same_path


SCHEMA = "tp-spec.autonomy-integration/v1"
APPLY_PILOTED = True  # guarded by the Phase-6 fault-injection regression suite


class AutonomyIntegrationError(RuntimeError):
    pass


class AutonomyIntegrationFault(AutonomyIntegrationError):
    pass


def _profile_root(profile_id: str) -> tuple[Dict[str, Any], Path, Path]:
    profile = autonomy_profile.load_profile(profile_id)
    auto_root = canonical_path((profile.get("autonomous") or {}).get("workspace_root") or "")
    canonical_root = canonical_path((profile.get("canonical") or {}).get("workspace_root") or "")
    if not auto_root.is_dir():
        raise AutonomyIntegrationError(f"AUTONOMY_WORKSPACE_NOT_INITIALIZED: {auto_root}")
    return profile, auto_root, canonical_root


def _integration_parent(auto_root: Path) -> Path:
    return auto_root / ".tp-spec" / "autonomy" / "integration"


def _next_id(auto_root: Path) -> str:
    date = dbmod.now_iso()[:10].replace("-", "")
    prefix = f"INTEGRATION-{date}-"
    maximum = 0
    parent = _integration_parent(auto_root)
    if parent.is_dir():
        for p in parent.iterdir():
            if not p.is_dir() or not p.name.startswith(prefix):
                continue
            try: maximum = max(maximum, int(p.name.rsplit("-", 1)[1]))
            except (ValueError, IndexError): pass
    return f"{prefix}{maximum + 1}"


def _root(auto_root: Path, integration_id: str) -> Path:
    return _integration_parent(auto_root) / integration_id


def _manifest(auto_root: Path, integration_id: str) -> Path:
    return _root(auto_root, integration_id) / "manifest.json"


def _atomic_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def load_integration(profile_id: str, integration_id: str) -> Dict[str, Any]:
    _, auto_root, _ = _profile_root(profile_id)
    path = _manifest(auto_root, integration_id)
    if not path.is_file():
        raise AutonomyIntegrationError(f"AUTONOMY_INTEGRATION_NOT_FOUND: {integration_id}")
    try: data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc: raise AutonomyIntegrationError(f"AUTONOMY_INTEGRATION_INVALID: {integration_id}: {exc}")
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("profile_id") != profile_id:
        raise AutonomyIntegrationError(f"AUTONOMY_INTEGRATION_INVALID: {integration_id}")
    return data


def _save(auto_root: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    data["updated_at"] = dbmod.now_iso()
    _atomic_json(_manifest(auto_root, str(data["integration_id"])), data)
    return data


def _mutable(profile: Dict[str, Any], auto_root: Path, canonical_root: Path) -> List[Tuple[str, Path, Path, str]]:
    rows = []
    for entry in (((profile.get("canonical") or {}).get("repositories") or {}).get("mutable") or []):
        rel = str(entry.get("path") or "")
        rid = str(entry.get("id") or Path(rel).name)
        branch = str(entry.get("branch") or "")
        auto_repo = canonical_path(auto_root / rel)
        canonical_repo = canonical_path(canonical_root / rel)
        if not autonomy_git.is_git_repo(auto_repo) or not autonomy_git.is_git_repo(canonical_repo):
            raise AutonomyIntegrationError(f"INTEGRATION_REPO_INVALID: {rid}")
        rows.append((rid, auto_repo, canonical_repo, branch))
    return rows


def _git_commits(repo: Path, base: str, head: str) -> List[str]:
    if not base or not head or base == head:
        return []
    raw = autonomy_git.git(repo, "rev-list", "--reverse", f"{base}..{head}")
    return [x.strip() for x in raw.splitlines() if x.strip()]


def _ensure_identity(repo: Path) -> None:
    if not autonomy_git.git(repo, "config", "user.name", check=False).strip():
        autonomy_git.git(repo, "config", "user.name", "TP-Spec Integration")
    if not autonomy_git.git(repo, "config", "user.email", check=False).strip():
        autonomy_git.git(repo, "config", "user.email", "tp-spec-integration@local.invalid")


def prepare(profile_id: str, batch_ids: Iterable[str]) -> Dict[str, Any]:
    profile, auto_root, canonical_root = _profile_root(profile_id)
    selected: List[Dict[str, Any]] = []
    for raw in batch_ids:
        bid = str(raw or "").strip()
        if not bid: continue
        batch = autonomy_batch.load_batch(profile_id, bid)
        if batch.get("status") not in {"READY_FOR_INTEGRATION", "PARTIAL_READY"}:
            raise AutonomyIntegrationError(f"INTEGRATION_BATCH_NOT_READY: {bid}")
        selected.append(batch)
    if not selected:
        raise AutonomyIntegrationError("INTEGRATION_BATCH_REQUIRED")

    integration_id = _next_id(auto_root)
    iroot = _root(auto_root, integration_id)
    repo_root = iroot / "repos"
    repo_root.mkdir(parents=True, exist_ok=False)
    repositories: Dict[str, Any] = {}
    try:
        for rid, auto_repo, canonical_repo, branch in _mutable(profile, auto_root, canonical_root):
            if autonomy_git.dirty(canonical_repo):
                raise AutonomyIntegrationError(f"INTEGRATION_CANONICAL_DIRTY: {rid}")
            if autonomy_git.branch(canonical_repo) != branch:
                raise AutonomyIntegrationError(
                    f"INTEGRATION_CANONICAL_BRANCH_MISMATCH: {rid}: {autonomy_git.branch(canonical_repo)!r} != {branch!r}"
                )
            pre = autonomy_git.head(canonical_repo)
            candidate = repo_root / rid
            autonomy_git.clone_independent(canonical_repo, candidate, branch=branch, staging_branch=None)
            _ensure_identity(candidate)
            source_ranges: List[Dict[str, Any]] = []
            for batch in selected:
                binding = (batch.get("repositories") or {}).get(rid)
                if not isinstance(binding, dict):
                    continue
                base = str(binding.get("base_head") or "")
                head = str(binding.get("head") or base)
                commits = _git_commits(auto_repo, base, head)
                if commits:
                    # Import objects from the independent Autonomous repo, then replay
                    # the exact Task/Batch commit sequence onto current Canonical.
                    autonomy_git.git(candidate, "fetch", "--no-tags", str(auto_repo), head)
                    for commit in commits:
                        try:
                            autonomy_git.git(candidate, "cherry-pick", commit)
                        except Exception as exc:
                            autonomy_git.git(candidate, "cherry-pick", "--abort", check=False)
                            raise AutonomyIntegrationError(f"INTEGRATION_CONFLICT: {rid}: {batch.get('batch_id')}: {exc}")
                source_ranges.append({"batch_id": batch.get("batch_id"), "base": base, "head": head, "commits": commits})
            target = autonomy_git.head(candidate)
            repositories[rid] = {
                "canonical_path": str(canonical_repo),
                "candidate_path": str(candidate),
                "branch": branch,
                "pre_ref": pre,
                "target_ref": target,
                "prepare_status": "READY",
                "apply_status": "PENDING",
                "source_ranges": source_ranges,
            }
    except Exception:
        shutil.rmtree(iroot, ignore_errors=True)
        raise

    now = dbmod.now_iso()
    data = {
        "schema": SCHEMA, "integration_id": integration_id, "profile_id": profile_id,
        "batch_ids": [str(x.get("batch_id")) for x in selected],
        "status": "NEEDS_VERIFICATION", "integration_root": str(iroot),
        "repositories": repositories,
        "verification": {"decision": "PENDING", "evidence": []},
        "apply_piloted": bool(APPLY_PILOTED),
        "created_at": now, "updated_at": now,
    }
    return _save(auto_root, data)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""): h.update(chunk)
    return h.hexdigest()


def _inside(child: Path, parent: Path) -> bool:
    c = canonical_path(child); p = canonical_path(parent)
    try: c.relative_to(p); return True
    except ValueError: return False


def record_verification(profile_id: str, integration_id: str, *, decision: str, evidence: Iterable[str]) -> Dict[str, Any]:
    profile, auto_root, _ = _profile_root(profile_id)
    data = load_integration(profile_id, integration_id)
    decision0 = str(decision or "").upper()
    if decision0 not in {"PASS", "FAIL"}:
        raise AutonomyIntegrationError("INTEGRATION_VERIFICATION_DECISION_INVALID: PASS|FAIL")
    evidence_root = canonical_path(_root(auto_root, integration_id) / "evidence")
    rows: List[Dict[str, Any]] = []
    for raw in evidence:
        path = canonical_path(raw)
        if not path.is_file() or path.stat().st_size <= 0:
            raise AutonomyIntegrationError(f"INTEGRATION_EVIDENCE_INVALID: {path}")
        if not _inside(path, evidence_root):
            raise AutonomyIntegrationError(f"INTEGRATION_EVIDENCE_OUTSIDE_ROOT: {path}")
        rows.append({"path": str(path), "sha256": _sha256(path), "bytes": path.stat().st_size})
    if decision0 == "PASS" and not rows:
        raise AutonomyIntegrationError("INTEGRATION_EVIDENCE_REQUIRED")
    data["verification"] = {"decision": decision0, "evidence": rows, "recorded_at": dbmod.now_iso(), "actor": "tp-verification-engineering"}
    data["status"] = "READY_TO_INTEGRATE" if decision0 == "PASS" else "VERIFICATION_FAILED"
    return _save(auto_root, data)


def _fault(point: str) -> None:
    if os.environ.get("TP_SPEC_AUTONOMY_FAULT", "") == point:
        raise AutonomyIntegrationFault(f"AUTONOMY_FAULT_INJECTED: {point}")


def _repo_current_matches(row: Dict[str, Any], *, expected: str) -> bool:
    repo = canonical_path(row["canonical_path"])
    return autonomy_git.head(repo) == expected


def apply(profile_id: str, integration_id: str) -> Dict[str, Any]:
    if not APPLY_PILOTED:
        raise AutonomyIntegrationError("APPLY_NOT_PILOTED")
    _, auto_root, _ = _profile_root(profile_id)
    data = load_integration(profile_id, integration_id)
    verification = data.get("verification") or {}
    if verification.get("decision") != "PASS":
        raise AutonomyIntegrationError("INTEGRATION_VERIFICATION_REQUIRED")
    if data.get("status") == "INTEGRATION_COMMITTED":
        return data
    if data.get("status") not in {"READY_TO_INTEGRATE", "APPLYING", "RECOVERY_REQUIRED"}:
        raise AutonomyIntegrationError(f"INTEGRATION_NOT_APPLICABLE: {data.get('status')}")

    # Reconcile already-transitioned refs first.  This makes retry deterministic
    # even if a process died after update-ref or after worktree reset but before
    # persisting the journal step.
    any_applied = False
    for rid, row in data["repositories"].items():
        canonical = canonical_path(row["canonical_path"])
        pre = str(row["pre_ref"]); target = str(row["target_ref"])
        current = autonomy_git.head(canonical)
        if current == target:
            autonomy_git.git(canonical, "reset", "--hard", target)
            row["apply_status"] = "APPLIED"; any_applied = True
        elif current == pre:
            if row.get("apply_status") == "APPLIED": row["apply_status"] = "PENDING"
        else:
            code = "INTEGRATION_RECOVERY_REQUIRED" if any_applied else "PREPARE_STALE"
            data["status"] = "RECOVERY_REQUIRED" if any_applied else "READY_TO_INTEGRATE"
            _save(auto_root, data)
            raise AutonomyIntegrationError(f"{code}: {rid}: current {current} expected {pre} or {target}")

    data["status"] = "APPLYING"; data["apply_started_at"] = data.get("apply_started_at") or dbmod.now_iso()
    _save(auto_root, data)

    for rid, row in data["repositories"].items():
        canonical = canonical_path(row["canonical_path"]); candidate = canonical_path(row["candidate_path"])
        branch = str(row["branch"]); pre = str(row["pre_ref"]); target = str(row["target_ref"])
        if row.get("apply_status") == "APPLIED":
            continue
        if autonomy_git.branch(canonical) != branch:
            data["status"] = "RECOVERY_REQUIRED" if any_applied else "READY_TO_INTEGRATE"; _save(auto_root, data)
            raise AutonomyIntegrationError(f"PREPARE_STALE: {rid}: canonical branch changed")
        if autonomy_git.dirty(canonical):
            data["status"] = "RECOVERY_REQUIRED" if any_applied else "READY_TO_INTEGRATE"; _save(auto_root, data)
            raise AutonomyIntegrationError(f"PREPARE_STALE: {rid}: canonical worktree dirty")
        current = autonomy_git.head(canonical)
        if current != pre:
            data["status"] = "RECOVERY_REQUIRED" if any_applied else "READY_TO_INTEGRATE"; _save(auto_root, data)
            raise AutonomyIntegrationError(f"PREPARE_STALE: {rid}: current {current} expected {pre}")
        _fault(f"before_ref:{rid}")
        # Import the prepared object without adding a persistent remote.
        autonomy_git.git(canonical, "fetch", "--no-tags", str(candidate), target)
        internal_ref = f"refs/tp-spec/integration/{integration_id}/{rid}"
        autonomy_git.git(canonical, "update-ref", internal_ref, target)
        autonomy_git.git(canonical, "update-ref", f"refs/heads/{branch}", target, pre)
        _fault(f"after_ref:{rid}")
        autonomy_git.git(canonical, "reset", "--hard", target)
        row["apply_status"] = "APPLIED"; row["applied_at"] = dbmod.now_iso(); any_applied = True
        _save(auto_root, data)
        _fault(f"after_repo:{rid}")

    data["status"] = "INTEGRATION_COMMITTED"; data["committed_at"] = dbmod.now_iso()
    return _save(auto_root, data)


def capability() -> Dict[str, Any]:
    return {
        "schema": "tp-spec.autonomy-integration-capability/v1",
        "prepare": "ENABLED", "review": "ENABLED",
        "apply": "ENABLED" if APPLY_PILOTED else "APPLY_NOT_PILOTED",
        "unsafe_override": False,
    }
