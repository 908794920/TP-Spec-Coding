# -*- coding: utf-8 -*-
"""Machine-local Runtime binding reconciliation for portable projects.

Portable project identity lives in ``project-binding.yaml``.  The SQLite
``project.root_path`` and runtime registry are machine-local locators/caches and
may legitimately change when a workspace is moved or copied to another machine.
This module reconciles those locators without rewriting task history.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from cli import db as dbmod
from cli.path_identity import canonical_path, same_path


def runtime_db_path(workspace_root: "str | Path", project_id: str) -> Path:
    return canonical_path(workspace_root) / ".ai-work" / "db" / f"{project_id}.db"


def _transient_files(db_path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for suffix in ("-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            try:
                size = p.stat().st_size
            except OSError:
                size = None
            rows.append({
                "path": str(p),
                "kind": "sqlite-transient",
                "portable_truth": False,
                "size_bytes": size,
            })
    return rows


def _registry_entry(project_id: str, registry_path: Optional[str]) -> Optional[Dict[str, Any]]:
    for item in dbmod.list_projects(registry_path=registry_path):
        if str(item.get("project_id") or "") == project_id:
            return dict(item)
    return None


def runtime_rebind_plan(
    workspace_root: "str | Path",
    project_id: str,
    *,
    registry_path: Optional[str] = None,
) -> Dict[str, Any]:
    workspace = canonical_path(workspace_root)
    db_path = runtime_db_path(workspace, project_id)
    result: Dict[str, Any] = {
        "schema": "ai-work.runtime-portability/v1",
        "workspace_root": str(workspace),
        "project_id": project_id,
        "db_path": str(db_path),
        "status": "ABSENT",
        "rebind_required": False,
        "previous_root": None,
        "current_root": str(workspace),
        "registry_path": str(dbmod.registry_read_path(registry_path)),
        "blockers": [],
        "transient_files": _transient_files(db_path),
    }
    if not project_id:
        result["status"] = "BLOCKED"
        result["blockers"].append("project id unresolved")
        return result
    if not db_path.is_file():
        return result
    try:
        conn = dbmod.connect_readonly(str(db_path))
        try:
            ok, details = dbmod.verify_schema(conn)
            if not ok:
                result["status"] = "BLOCKED"
                result["blockers"].extend(details)
                return result
            row = conn.execute(
                "SELECT project_id, project_name, root_path, base_version, schema_version "
                "FROM project WHERE project_id=?",
                (project_id,),
            ).fetchone()
        finally:
            conn.close()
    except Exception as exc:
        result["status"] = "BLOCKED"
        result["blockers"].append(f"Runtime DB unreadable: {type(exc).__name__}: {exc}")
        return result
    if row is None:
        result["status"] = "BLOCKED"
        result["blockers"].append(f"Runtime DB has no project row for {project_id}")
        return result
    previous = str(row["root_path"] or "").strip()
    result.update({
        "project_name": str(row["project_name"] or project_id),
        "base_version": str(row["base_version"] or ""),
        "schema_version": row["schema_version"],
        "previous_root": previous or None,
    })
    if previous:
        try:
            if same_path(Path(previous), workspace):
                result["status"] = "CURRENT"
                return result
        except Exception:
            pass

    # A still-existing former workspace is ambiguous: it may be a second live
    # clone rather than a move.  Never steal its Runtime identity automatically.
    if previous and os.path.isabs(previous):
        old = Path(previous)
        try:
            if old.exists():
                result["blockers"].append(
                    f"previous Runtime root still exists ({previous}); duplicate workspace identity requires human review"
                )
        except OSError:
            result["blockers"].append(f"previous Runtime root cannot be inspected: {previous}")

    reg = _registry_entry(project_id, registry_path)
    if reg:
        result["registry_entry"] = reg
        reg_root = str(reg.get("root_path") or "").strip()
        if reg_root:
            try:
                matches_current = same_path(Path(reg_root), workspace)
            except Exception:
                matches_current = False
            if not matches_current and os.path.isabs(reg_root):
                try:
                    if Path(reg_root).exists():
                        result["blockers"].append(
                            f"runtime registry maps {project_id} to another existing workspace ({reg_root})"
                        )
                except OSError:
                    result["blockers"].append(f"runtime registry root cannot be inspected: {reg_root}")

    if result["blockers"]:
        result["status"] = "BLOCKED"
        return result
    result["status"] = "REBIND_AVAILABLE"
    result["rebind_required"] = True
    return result


def apply_runtime_rebind(
    workspace_root: "str | Path",
    project_id: str,
    *,
    registry_path: Optional[str] = None,
) -> Dict[str, Any]:
    plan = runtime_rebind_plan(workspace_root, project_id, registry_path=registry_path)
    if plan["status"] in {"ABSENT", "CURRENT"}:
        return plan
    if plan["status"] != "REBIND_AVAILABLE":
        return plan

    workspace = canonical_path(workspace_root)
    db_path = Path(plan["db_path"])
    conn = dbmod.connect(str(db_path))
    try:
        with dbmod.transactional(conn):
            conn.execute(
                "UPDATE project SET root_path=?, updated_at=? WHERE project_id=?",
                (str(workspace), dbmod.now_iso(), project_id),
            )
    finally:
        conn.close()

    # The registry is a machine-local resolver cache.  Re-registering writes to
    # the modern machine-local path by default and keeps project identity stable.
    registry_written = dbmod.register_project(
        project_id=project_id,
        project_name=str(plan.get("project_name") or project_id),
        db_path=str(db_path),
        root_path=str(workspace),
        base_version=str(plan.get("base_version") or ""),
        schema_version=int(plan.get("schema_version") or dbmod.EXPECTED_SCHEMA_VERSION),
        registry_path=registry_path,
    )
    final = runtime_rebind_plan(workspace, project_id, registry_path=str(registry_written))
    final["action"] = "REBIND_RUNTIME_ROOT"
    final["registry_written"] = str(registry_written)
    final["previous_root"] = plan.get("previous_root")
    return final
