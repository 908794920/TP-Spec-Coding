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
    return canonical_path(workspace_root) / ".tp-spec" / "db" / f"{project_id}.db"


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
    path = dbmod.registry_read_path(registry_path)
    if path.exists() and not path.is_file():
        raise ValueError(f"runtime registry is not a file: {path}")
    items = dbmod._read_registry_payload(path)["projects"]
    if any(not isinstance(item, dict) or not item.get("project_id") for item in items):
        raise ValueError(f"runtime registry contains an invalid project entry: {path}")
    identities = [str(item["project_id"]) for item in items]
    if len(set(identities)) != len(identities):
        raise ValueError(f"runtime registry contains duplicate project identities: {path}")
    return next((dict(item) for item in items if str(item["project_id"]) == project_id), None)


def runtime_rebind_plan(
    workspace_root: "str | Path",
    project_id: str,
    *,
    registry_path: Optional[str] = None,
) -> Dict[str, Any]:
    workspace = canonical_path(workspace_root)
    db_path = runtime_db_path(workspace, project_id)
    result: Dict[str, Any] = {
        "schema": "tp-spec.runtime-portability/v1",
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
    root_current = bool(previous and same_path(Path(previous), workspace))

    # A still-existing former workspace is ambiguous: it may be a second live
    # clone rather than a move.  Never steal its Runtime identity automatically.
    if not root_current and previous and os.path.isabs(previous):
        old = Path(previous)
        try:
            if old.exists():
                result["blockers"].append(
                    f"previous Runtime root still exists ({previous}); duplicate workspace identity requires human review"
                )
        except OSError:
            result["blockers"].append(f"previous Runtime root cannot be inspected: {previous}")

    try:
        reg = _registry_entry(project_id, registry_path)
    except (OSError, ValueError) as exc:
        result["status"] = "BLOCKED"
        result["blockers"].append(f"Runtime registry unreadable: {exc}")
        return result
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

        reg_db = str(reg.get("db_path") or "").strip()
        if reg_db and os.path.isabs(reg_db) and not same_path(Path(reg_db), db_path):
            try:
                if Path(reg_db).exists():
                    result["blockers"].append(
                        f"runtime registry maps {project_id} to another existing database ({reg_db})"
                    )
            except OSError:
                result["blockers"].append(f"runtime registry database cannot be inspected: {reg_db}")

    if result["blockers"]:
        result["status"] = "BLOCKED"
        return result
    registry_current = bool(reg and str(reg.get("root_path") or "")
                            and same_path(Path(reg["root_path"]), workspace)
                            and str(reg.get("db_path") or "")
                            and same_path(Path(reg["db_path"]), db_path)
                            and str(reg.get("base_version") or "") == result["base_version"]
                            and reg.get("schema_version") == result["schema_version"])
    result["status"] = "CURRENT" if root_current and registry_current else "REBIND_AVAILABLE"
    result["rebind_required"] = not root_current
    result["registry_sync_required"] = not registry_current
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
    if plan["rebind_required"]:
        conn = dbmod.connect(str(db_path))
        try:
            with dbmod.transactional(conn):
                latest_plan = runtime_rebind_plan(workspace, project_id, registry_path=registry_path)
                if latest_plan["status"] == "BLOCKED":
                    return latest_plan
                current = conn.execute("SELECT root_path, base_version, schema_version FROM project WHERE project_id=?",
                                       (project_id,)).fetchone()
                if (current is None or str(current["root_path"] or "") != str(plan["previous_root"] or "")
                        or str(current["base_version"] or "") != plan["base_version"]
                        or current["schema_version"] != plan["schema_version"]):
                    return {**plan, "status": "BLOCKED", "blockers": ["RUNTIME_BINDING_CHANGED: replan before rebind"]}
                conn.execute(
                    "UPDATE project SET root_path=?, updated_at=? WHERE project_id=?",
                    (str(workspace), dbmod.now_iso(), project_id),
                )
        finally:
            conn.close()

    # The cache can be repaired after a committed root update without updating
    # the ledger again. A CURRENT DB root alone never proves cache convergence.
    try:
        latest_plan = runtime_rebind_plan(workspace, project_id, registry_path=registry_path)
        if (latest_plan["status"] not in {"CURRENT", "REBIND_AVAILABLE"}
                or latest_plan.get("rebind_required")
                or latest_plan.get("base_version") != plan.get("base_version")
                or latest_plan.get("schema_version") != plan.get("schema_version")):
            return {**latest_plan, "status": "BLOCKED", "facts_committed": bool(plan["rebind_required"]),
                    "blockers": latest_plan.get("blockers") or ["RUNTIME_BINDING_CHANGED: replan before cache update"]}
        registry_written = dbmod.register_project(
            project_id=project_id,
            project_name=str(plan.get("project_name") or project_id),
            db_path=str(db_path),
            root_path=str(workspace),
            base_version=str(plan.get("base_version") or ""),
            schema_version=int(plan.get("schema_version") or dbmod.EXPECTED_SCHEMA_VERSION),
            registry_path=registry_path,
        )
    except Exception as exc:
        return {**plan, "status": "SYNC_REQUIRED", "facts_committed": True,
                "rebind_required": False, "registry_sync_required": True,
                "warnings": [f"Registry update failed: {type(exc).__name__}: {exc}"],
                "recovery": "Repeat base sync-project --apply for the same workspace; do not repeat business work."}
    final = runtime_rebind_plan(workspace, project_id, registry_path=str(registry_written))
    final["action"] = "REBIND_RUNTIME_ROOT" if plan["rebind_required"] else "RECONCILE_RUNTIME_REGISTRY"
    final["registry_written"] = str(registry_written)
    final["previous_root"] = plan.get("previous_root")
    return final
