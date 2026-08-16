# -*- coding: utf-8 -*-
"""Long-lived physically isolated workspaces for Autonomous Maintenance."""
from __future__ import annotations

import os
import yaml
import uuid
from pathlib import Path
from typing import Any, Dict, List

from . import autonomy_git, autonomy_profile
from . import db as dbmod
from .environment import write_project_binding
from .path_identity import canonical_path, same_path
from .version import active_version


class AutonomyWorkspaceError(ValueError):
    pass


def _scope_entries(profile: Dict[str, Any]):
    repos = ((profile.get("canonical") or {}).get("repositories") or {})
    for scope in ("mutable", "support"):
        for item in repos.get(scope) or []:
            yield scope, item


def _ensure_runtime(profile: Dict[str, Any]) -> str:
    root = canonical_path((profile.get("autonomous") or {}).get("workspace_root"))
    runtime_id = str((profile.get("autonomous") or {}).get("runtime_project_id") or "")
    canonical_id = str((profile.get("canonical") or {}).get("project_id") or "")
    root.mkdir(parents=True, exist_ok=True)
    tp = root / ".tp-spec"
    (tp / "db").mkdir(parents=True, exist_ok=True)
    (tp / "tasks").mkdir(parents=True, exist_ok=True)
    (tp / "tasksHistory").mkdir(parents=True, exist_ok=True)
    (tp / ".execution").mkdir(parents=True, exist_ok=True)
    (tp / "autonomy" / "cycles").mkdir(parents=True, exist_ok=True)
    (tp / "autonomy" / "batches").mkdir(parents=True, exist_ok=True)
    (tp / "autonomy" / "handoff").mkdir(parents=True, exist_ok=True)
    db_path = tp / "db" / f"{runtime_id}.db"

    # Prevent the autonomous Runtime identity from silently moving to a second live root.
    for row in dbmod.list_projects():
        if row.get("project_id") != runtime_id:
            continue
        old_root = str(row.get("root_path") or "")
        if old_root and not same_path(old_root, root) and Path(old_root).exists():
            raise AutonomyWorkspaceError(
                f"AUTONOMY_RUNTIME_IDENTITY_CONFLICT: {runtime_id} already bound to {old_root}"
            )

    if db_path.exists():
        conn = dbmod.connect_readonly(str(db_path))
        try:
            ok, details = dbmod.verify_schema(conn)
            row = conn.execute("SELECT project_id, root_path, base_version FROM project WHERE project_id=?", (runtime_id,)).fetchone()
        finally:
            conn.close()
        if not ok or row is None:
            raise AutonomyWorkspaceError(f"AUTONOMY_RUNTIME_INVALID: {db_path}: {details if not ok else 'project row missing'}")
        if not same_path(row["root_path"], root):
            raise AutonomyWorkspaceError(f"AUTONOMY_RUNTIME_ROOT_MISMATCH: {row['root_path']} != {root}")
        if str(row["base_version"] or "") != active_version():
            raise AutonomyWorkspaceError(
                f"AUTONOMY_RUNTIME_CONTRACT_MISMATCH: {row['base_version']} != {active_version()}"
            )
    else:
        conn = dbmod.connect(str(db_path))
        try:
            dbmod.init_schema(conn)
            now = dbmod.now_iso()
            with dbmod.transactional(conn):
                conn.execute(
                    "INSERT INTO project (project_id,project_name,root_path,base_version,schema_version,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                    (runtime_id, runtime_id, str(root), active_version(), dbmod.EXPECTED_SCHEMA_VERSION, now, now),
                )
        finally:
            conn.close()
    dbmod.register_project(
        project_id=runtime_id, db_path=str(db_path), root_path=str(root),
        base_version=active_version(), schema_version=dbmod.EXPECTED_SCHEMA_VERSION,
        project_name=runtime_id,
    )
    binding = root / ".tp-spec" / "config" / "project-binding.yaml"
    if not binding.exists():
        write_project_binding(
            root, project_id=runtime_id, wiki_id=canonical_id,
            knowledge_id=canonical_id, base_version=active_version(),
        )
    # Autonomous Runtime has its own Task identity but reuses Canonical content
    # identities read-only.  Persist this distinction in the portable binding so
    # content-system mutators can fail closed instead of relying on Skill prose.
    data = yaml.safe_load(binding.read_text(encoding="utf-8-sig")) or {}
    expected_meta = {
        "profile_id": str(profile.get("profile_id") or ""),
        "canonical_project_id": canonical_id,
        "context_mode": "canonical_read_only",
    }
    if data.get("autonomy") != expected_meta:
        data["autonomy"] = expected_meta
        tmp = binding.with_name(f".{binding.name}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
        os.replace(tmp, binding)
    return str(db_path)


def initialize_workspace(profile_id: str) -> Dict[str, Any]:
    profile = autonomy_profile.load_profile(profile_id)
    errors = autonomy_profile.validate_profile(profile, check_paths=True)
    if errors:
        raise AutonomyWorkspaceError(errors[0])
    root = canonical_path((profile.get("autonomous") or {}).get("workspace_root"))
    canonical = canonical_path((profile.get("canonical") or {}).get("workspace_root"))
    autonomy_profile.validate_isolation(canonical, root)
    existed_before = root.exists() and (root / ".tp-spec").exists()
    root.mkdir(parents=True, exist_ok=True)
    repo_rows: List[Dict[str, Any]] = []
    staging_branch = str(((profile.get("autonomous") or {}).get("staging") or {}).get("branch") or "")
    for scope, item in _scope_entries(profile):
        rel = str(item.get("path") or "")
        src = canonical_path(canonical / rel)
        dst = canonical_path(root / rel)
        if not dst.exists():
            autonomy_git.clone_independent(
                src, dst, branch=str(item.get("branch") or ""),
                staging_branch=staging_branch if scope == "mutable" else None,
            )
        elif not autonomy_git.is_git_repo(dst):
            raise AutonomyWorkspaceError(f"AUTONOMY_REPO_INVALID: {dst}")
        if scope == "mutable" and autonomy_git.branch(dst) != staging_branch:
            raise AutonomyWorkspaceError(
                f"AUTONOMY_STAGING_BRANCH_MISMATCH: {dst} is on {autonomy_git.branch(dst)!r}, expected {staging_branch!r}"
            )
        repo_rows.append({
            "id": str(item.get("id") or Path(rel).name), "scope": scope,
            "path": str(dst), "branch": autonomy_git.branch(dst), "head": autonomy_git.head(dst),
        })
    db_path = _ensure_runtime(profile)
    return {
        "schema": "tp-spec.autonomy-workspace/v1",
        "profile_id": profile_id,
        "workspace_root": str(root),
        "runtime_project_id": (profile.get("autonomous") or {}).get("runtime_project_id"),
        "db_path": db_path,
        "reused": bool(existed_before),
        "repositories": repo_rows,
    }


def _drift_for_repo(profile_id: str, profile: Dict[str, Any], scope: str, item: Dict[str, Any], *, refresh: bool) -> Dict[str, Any]:
    root = canonical_path((profile.get("autonomous") or {}).get("workspace_root"))
    canonical = canonical_path((profile.get("canonical") or {}).get("workspace_root"))
    rel = str(item.get("path") or "")
    repo = canonical_path(root / rel)
    source = canonical_path(canonical / rel)
    staging_head = autonomy_git.head(repo)
    target_ref = f"refs/tp-spec/canonical-observed/{profile_id}/{str(item.get('id') or Path(rel).name)}"
    if refresh:
        canonical_head = autonomy_git.fetch_local_ref(repo, source, str(item.get("branch") or ""), target_ref)
    else:
        try:
            canonical_head = autonomy_git.head(repo, target_ref)
        except Exception:
            canonical_head = staging_head
    common = autonomy_git.merge_base(repo, canonical_head, staging_head)
    cfiles = set(autonomy_git.changed_files(repo, common, canonical_head))
    sfiles = set(autonomy_git.changed_files(repo, common, staging_head))
    return {
        "last_common_base": common,
        "canonical_observed_head": canonical_head,
        "staging_head": staging_head,
        "canonical_commits_since_common_base": autonomy_git.commit_count(repo, common, canonical_head),
        "staging_commits_since_common_base": autonomy_git.commit_count(repo, common, staging_head),
        "changed_file_overlap_count": len(cfiles & sfiles),
    }


def workspace_status(profile_id: str, *, refresh_canonical: bool = True) -> Dict[str, Any]:
    profile = autonomy_profile.load_profile(profile_id)
    root = canonical_path((profile.get("autonomous") or {}).get("workspace_root"))
    if not root.is_dir():
        raise AutonomyWorkspaceError(f"AUTONOMY_WORKSPACE_NOT_INITIALIZED: {root}")
    rows: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for scope, item in _scope_entries(profile):
        rel = str(item.get("path") or "")
        repo = canonical_path(root / rel)
        if not autonomy_git.is_git_repo(repo):
            warnings.append(f"REPO_MISSING:{item.get('id')}")
            continue
        is_dirty = autonomy_git.dirty(repo)
        row: Dict[str, Any] = {
            "id": str(item.get("id") or Path(rel).name), "scope": scope,
            "path": str(repo), "branch": autonomy_git.branch(repo),
            "head": autonomy_git.head(repo), "dirty": is_dirty,
        }
        if scope == "support" and is_dirty:
            warnings.append("SUPPORT_REPO_MUTATED")
        if scope == "mutable":
            row["drift"] = _drift_for_repo(profile_id, profile, scope, item, refresh=refresh_canonical)
        rows.append(row)
    return {
        "schema": "tp-spec.autonomy-workspace-status/v1", "profile_id": profile_id,
        "workspace_root": str(root), "repositories": rows, "warnings": warnings,
    }
