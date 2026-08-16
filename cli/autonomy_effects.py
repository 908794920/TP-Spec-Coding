# -*- coding: utf-8 -*-
"""Runtime guards for declared workflow stage effects in Autonomous Maintenance.

Stage Effects are an executable contract, not prose. Mutable repositories may
change only when the dispatched stage declares ``repo_mutation``; support
repositories are read-only for every stage. Guards survive cycle boundaries so
an interrupted executor cannot bypass verification by starting a later cycle.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

from . import autonomy_git, autonomy_profile

GUARD_SCHEMA = "tp-spec.autonomy-stage-effect-guard/v1"


class AutonomyEffectError(RuntimeError):
    pass


def _root(profile: Dict[str, Any]) -> Path:
    return Path(str((profile.get("autonomous") or {}).get("workspace_root") or "")).resolve()


def _repos(profile: Dict[str, Any], scope: str) -> List[Tuple[str, Path]]:
    root = _root(profile)
    result: List[Tuple[str, Path]] = []
    entries = (((profile.get("canonical") or {}).get("repositories") or {}).get(scope) or [])
    for entry in entries:
        rid = str(entry.get("id") or "").strip()
        rel = str(entry.get("path") or "").strip()
        if rid and rel:
            result.append((rid, (root / rel).resolve()))
    return result


def _guard_path(profile: Dict[str, Any], task_id: str) -> Path:
    task = str(task_id or "").strip()
    if not task or any(x in task for x in ("/", "\\", "..")):
        raise AutonomyEffectError(f"AUTONOMY_TASK_ID_INVALID: {task_id!r}")
    return _root(profile) / ".tp-spec" / "autonomy" / "stage-guards" / f"{task}.json"


def _atomic_write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _read(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AutonomyEffectError(f"AUTONOMY_STAGE_GUARD_INVALID: {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != GUARD_SCHEMA:
        raise AutonomyEffectError(f"AUTONOMY_STAGE_GUARD_INVALID: {path}")
    return data


def _support_fingerprints(profile: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for rid, repo in _repos(profile, "support"):
        if autonomy_git.dirty(repo):
            raise AutonomyEffectError(f"SUPPORT_REPO_MUTATION: support repository is dirty: {rid}:{repo}")
        out[rid] = autonomy_git.repo_state_fingerprint(repo)
    return out


def arm_stage_guard(
    profile_id: str,
    task_id: str,
    *,
    cycle_id: str,
    generation: int,
    stage: str,
    role_id: str,
    declared_effects: List[str],
) -> Dict[str, Any]:
    """Snapshot the repo invariants for one dispatched workflow stage."""
    profile = autonomy_profile.load_profile(profile_id)
    effects = sorted({str(x) for x in declared_effects if str(x)})
    mutable = {}
    if "repo_mutation" not in effects:
        mutable = {rid: autonomy_git.repo_state_fingerprint(repo) for rid, repo in _repos(profile, "mutable")}
    data: Dict[str, Any] = {
        "schema": GUARD_SCHEMA,
        "profile_id": profile_id,
        "task_id": task_id,
        "cycle_id": cycle_id,
        "generation": int(generation),
        "stage": str(stage or ""),
        "role_id": str(role_id or ""),
        "declared_effects": effects,
        "mutable_repo_fingerprints": mutable,
        "support_repo_fingerprints": _support_fingerprints(profile),
    }
    _atomic_write(_guard_path(profile, task_id), data)
    return data


def arm_no_mutation_guard(
    profile_id: str,
    task_id: str,
    *,
    cycle_id: str,
    generation: int,
    stage: str,
    role_id: str,
) -> Dict[str, Any]:
    """Compatibility helper used by focused tests and callers."""
    return arm_stage_guard(
        profile_id, task_id, cycle_id=cycle_id, generation=generation,
        stage=stage, role_id=role_id, declared_effects=[],
    )


def _assert_fingerprints(
    current: Dict[str, Path], expected: Dict[str, Any], *, error_prefix: str,
) -> None:
    for rid, before in expected.items():
        repo = current.get(str(rid))
        if repo is None:
            raise AutonomyEffectError(f"AUTONOMY_STAGE_GUARD_REPO_MISSING: {rid}")
        after = autonomy_git.repo_state_fingerprint(repo)
        if after != str(before):
            if error_prefix == "SUPPORT_REPO_MUTATION":
                raise AutonomyEffectError(f"SUPPORT_REPO_MUTATION: support repository changed: {rid}:{repo}")
            raise AutonomyEffectError(f"UNDECLARED_REPO_MUTATION: effects:[] stage changed mutable repo {repo}")


def verify_pending_guard(profile_id: str, task_id: str) -> Dict[str, Any] | None:
    """Verify and clear the previously dispatched stage guard.

    Guard provenance can belong to an earlier cycle: the invariant is about the
    dispatched stage, not the generation that later verifies it.
    """
    profile = autonomy_profile.load_profile(profile_id)
    path = _guard_path(profile, task_id)
    guard = _read(path)
    if not guard:
        return None
    if guard.get("profile_id") != profile_id or guard.get("task_id") != task_id:
        raise AutonomyEffectError(f"AUTONOMY_STAGE_GUARD_IDENTITY_MISMATCH: {path}")

    mutable_expected = guard.get("mutable_repo_fingerprints") or {}
    support_expected = guard.get("support_repo_fingerprints") or {}
    if not isinstance(mutable_expected, dict) or not isinstance(support_expected, dict):
        raise AutonomyEffectError(f"AUTONOMY_STAGE_GUARD_INVALID: {path}")

    _assert_fingerprints(dict(_repos(profile, "support")), support_expected, error_prefix="SUPPORT_REPO_MUTATION")
    _assert_fingerprints(dict(_repos(profile, "mutable")), mutable_expected, error_prefix="UNDECLARED_REPO_MUTATION")
    path.unlink(missing_ok=True)
    return guard
