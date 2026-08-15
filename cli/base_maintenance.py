# -*- coding: utf-8 -*-
"""TP-Spec-Coding installation/binding health and convergence commands.

The project-side ``.tp-spec`` directory owns runtime/task state. Base program
assets and central Wiki/Knowledge data are resolved via installation config +
registries. Legacy Junctions are compatibility-only and are removed only after
an equivalent resolved target is proven.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import yaml

from cli import db as dbmod
from cli.content_systems import load_content_systems, same_path
from cli.path_identity import canonical_path, path_identity_key
from cli.environment import (
    BINDING_SCHEMA,
    INSTALLATION_SCHEMA,
    INVENTORY_SCHEMA,
    default_binding_path,
    default_installation_path,
    default_inventory_path,
    load_installation_config,
    load_project_binding,
    load_workspace_inventory,
    resolve_base_root,
    validate_base_root,
    write_installation_config,
    write_project_binding,
    write_workspace_inventory,
)
from cli.knowledge.common import load_project_registry, resolve_knowledge_project
from cli.project_portability import normalize_project_portability, project_portability_plan
from cli.project_surface import project_surface_plan, sync_project_surface
from cli.runtime_portability import apply_runtime_rebind, runtime_rebind_plan
from cli.active_task_portability import scan_active_task_portability
from cli.installation_lifecycle import configure_installation, installation_doctor, installation_migration
from cli.namespace_migration import namespace_plan, migrate_namespace
from cli.wiki.registry import load_registry as load_wiki_registry, resolve_targets, resolve_workspace_identity, resolve_workspace_wiki_root
from cli.version import active_version

BASE_LINK_DIRS = ("agents", "cli", "docs", "governance", "scripts", "skills", "templates", "automation")
CONTENT_LINK_DIRS = ("wiki", "knowledge")
SCAN_SKIP = {".git", ".idea", ".vscode", "node_modules", "target", "build", "dist", "__pycache__", ".pytest_cache"}
PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _emit(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def _candidate_link(path: Path, expected: Optional[Path]) -> Dict[str, Any]:
    lexists = os.path.lexists(path)
    is_symlink = path.is_symlink()
    is_junction = False
    try:
        checker = getattr(path, "is_junction", None)
        if checker:
            is_junction = bool(checker())
    except OSError:
        is_junction = False
    link_like = is_symlink or is_junction
    resolved: Optional[Path] = None
    if lexists:
        try:
            resolved = path.resolve(strict=False)
        except OSError:
            resolved = None
    matches = bool(link_like and resolved is not None and expected is not None and same_path(resolved, expected))
    if not lexists:
        state = "ABSENT"
    elif link_like and matches:
        state = "LEGACY_LINK_SAFE_REMOVE"
    elif link_like:
        state = "LEGACY_LINK_TARGET_MISMATCH"
    else:
        state = "REAL_PROJECT_LOCAL_PATH"
    return {
        "path": str(path),
        "expected": str(expected) if expected else None,
        "exists": bool(lexists),
        "is_symlink": is_symlink,
        "is_junction": is_junction,
        "resolved": str(resolved) if resolved else None,
        "matches_expected": matches,
        "state": state,
    }


def _safe_remove_link(path: Path) -> None:
    """Remove only the link/junction object, never a real directory target."""
    if path.is_symlink():
        path.unlink()
        return
    checker = getattr(path, "is_junction", None)
    if checker and checker():
        os.rmdir(path)
        return
    raise ValueError(f"refusing to remove non-link path: {path}")


def _runtime_project_status(workspace: Path, project_id: str) -> Dict[str, Any]:
    """Read project Runtime contract without creating or mutating SQLite."""
    candidates: List[Path] = []
    if project_id:
        candidates.append(workspace / ".tp-spec" / "db" / f"{project_id}.db")
    for row in dbmod.list_projects():
        try:
            root = row.get("root_path")
            if root and same_path(Path(str(root)), workspace):
                raw = row.get("db_path")
                if raw:
                    candidates.append(Path(dbmod._resolve_project_db_abs(str(raw))))
        except Exception:
            continue
    seen: Set[str] = set()
    for candidate in candidates:
        cp = canonical_path(candidate)
        key = path_identity_key(cp)
        if key in seen:
            continue
        seen.add(key)
        if not cp.is_file():
            continue
        try:
            conn = dbmod.connect_readonly(str(cp))
            try:
                ok, details = dbmod.verify_schema(conn)
                if not ok:
                    return {"exists": True, "db_path": str(cp), "valid": False, "issues": details, "base_version": "", "schema_version": None}
                row = conn.execute("SELECT project_id, root_path, base_version, schema_version FROM project WHERE project_id=?", (project_id,)).fetchone() if project_id else None
                if row is None:
                    return {"exists": True, "db_path": str(cp), "valid": False, "issues": [f"project row missing for {project_id or '<unresolved>'}"], "base_version": "", "schema_version": None}
                return {"exists": True, "db_path": str(cp), "valid": True, "issues": [], "root_path": str(row["root_path"] or ""), "base_version": str(row["base_version"] or ""), "schema_version": row["schema_version"]}
            finally:
                conn.close()
        except Exception as exc:
            return {"exists": True, "db_path": str(cp), "valid": False, "issues": [f"{type(exc).__name__}: {exc}"], "base_version": "", "schema_version": None}
    return {"exists": False, "db_path": str((workspace / ".tp-spec" / "db" / f"{project_id}.db").resolve(strict=False)) if project_id else None, "valid": False, "issues": [], "base_version": "", "schema_version": None}


def _simple_content_override_redundant(workspace: Path, cfg, installation) -> Dict[str, Any]:
    path = workspace / ".tp-spec" / "config" / "content-systems.yaml"
    if not path.is_file() or not installation.exists:
        return {"path": str(path), "exists": path.is_file(), "redundant": False, "reason": "missing override or installation"}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except Exception as exc:
        return {"path": str(path), "exists": True, "redundant": False, "reason": f"parse error: {exc}"}
    allowed_top = {"schema", "systems"}
    if set(data) - allowed_top:
        return {"path": str(path), "exists": True, "redundant": False, "reason": "contains non-root project overrides"}
    systems = data.get("systems") or {}
    if not isinstance(systems, dict) or set(systems) - {"wiki", "knowledge"}:
        return {"path": str(path), "exists": True, "redundant": False, "reason": "contains non-root system overrides"}
    for name in ("wiki", "knowledge"):
        sec = systems.get(name) or {}
        if not isinstance(sec, dict) or set(sec) - {"root", "enabled"}:
            return {"path": str(path), "exists": True, "redundant": False, "reason": f"systems.{name} contains extra overrides"}
    def resolved_override_root(raw: str) -> Optional[Path]:
        if not raw:
            return None
        expanded = os.path.expandvars(os.path.expanduser(raw))
        candidate = Path(expanded)
        if not candidate.is_absolute():
            candidate = workspace / candidate
        return candidate.resolve(strict=False)

    wr = str((systems.get("wiki") or {}).get("root") or "").strip()
    kr = str((systems.get("knowledge") or {}).get("root") or "").strip()
    wr_path = resolved_override_root(wr)
    kr_path = resolved_override_root(kr)
    if wr_path and installation.wiki_root and not same_path(wr_path, installation.wiki_root):
        return {"path": str(path), "exists": True, "redundant": False, "reason": "wiki root differs from installation"}
    if kr_path and installation.knowledge_root and not same_path(kr_path, installation.knowledge_root):
        return {"path": str(path), "exists": True, "redundant": False, "reason": "knowledge root differs from installation"}
    return {"path": str(path), "exists": True, "redundant": True, "reason": "roots are fully covered by installation config"}


def resolve_workspace(workspace_root: "str | Path", *, installation_config: "str | Path | None" = None, content_config: "str | Path | None" = None) -> Dict[str, Any]:
    workspace = Path(workspace_root).resolve(strict=False)
    cfg = load_content_systems(workspace, config_path=content_config, installation_config_path=installation_config)
    installation = load_installation_config(installation_config)
    binding = load_project_binding(workspace)
    base_root = resolve_base_root(workspace, installation_path=installation_config)
    base_health = validate_base_root(base_root)

    wiki_identity: Dict[str, Any]
    wiki_workspace_root: Optional[Path]
    wiki_targets: List[Dict[str, Any]] = []
    try:
        wiki_identity = resolve_workspace_identity(cfg)
        wiki_workspace_root = resolve_workspace_wiki_root(cfg)
        wiki_targets = [t.as_dict() for t in resolve_targets(cfg)]
    except Exception as exc:
        wiki_identity = {"resolved": False, "workspace_id": "", "source": "error", "error": f"{type(exc).__name__}: {exc}"}
        wiki_workspace_root = None

    try:
        knowledge = resolve_knowledge_project(cfg, require=False)
    except Exception as exc:
        knowledge = {"resolved": False, "project_id": "", "project_root": None, "shared_ids": [], "error": f"{type(exc).__name__}: {exc}"}

    expected: Dict[str, Optional[Path]] = {name: base_root / name for name in BASE_LINK_DIRS}
    expected["wiki"] = wiki_workspace_root
    expected["knowledge"] = Path(knowledge["project_root"]) if knowledge.get("project_root") else None
    legacy = {name: _candidate_link(workspace / ".tp-spec" / name, target) for name, target in expected.items()}

    project_id = binding.project_id or str(knowledge.get("project_id") or "") or str(wiki_identity.get("workspace_id") or "")
    if not project_id:
        candidate = re.sub(r"[^a-z0-9-]+", "-", workspace.name.casefold()).strip("-")
        project_id = candidate if PROJECT_ID_RE.match(candidate or "") else ""
    runtime = _runtime_project_status(workspace, project_id)
    runtime_portability = runtime_rebind_plan(workspace, project_id)
    active_task_portability = scan_active_task_portability(workspace)

    return {
        "schema": "tp-spec.base-resolution/v1",
        "workspace_root": str(workspace),
        "project_id": project_id,
        "base": base_health,
        "installation": {
            "path": str(installation.path),
            "exists": installation.exists,
            "base_root": str(installation.base_root) if installation.base_root else None,
            "wiki_system_root": str(installation.wiki_root) if installation.wiki_root else None,
            "knowledge_system_root": str(installation.knowledge_root) if installation.knowledge_root else None,
        },
        "binding": {
            "path": str(binding.path),
            "exists": binding.exists,
            "project_id": binding.project_id,
            "wiki_id": binding.wiki_id,
            "knowledge_id": binding.knowledge_id,
            "base_version": binding.base_version,
        },
        "wiki": {
            "system_root": str(cfg.paths.wiki_system_root),
            "workspace_root": str(wiki_workspace_root) if wiki_workspace_root else None,
            "identity": wiki_identity,
            "repo_targets": wiki_targets,
        },
        "knowledge": {
            "system_root": str(cfg.paths.knowledge_physical_root),
            "project_root": str(knowledge.get("project_root")) if knowledge.get("project_root") else None,
            "project_id": knowledge.get("project_id") or "",
            "shared_ids": knowledge.get("shared_ids") or [],
            "resolved": bool(knowledge.get("resolved")),
            "source": knowledge.get("source") or "",
            "error": knowledge.get("error"),
            "default_retrieval_scope": str(cfg.knowledge_retrieval.get("default_scope") or "project"),
            "include_shared": bool(cfg.knowledge_retrieval.get("include_shared", True)),
            "global_fallback": bool(cfg.knowledge_retrieval.get("global_fallback", False)),
        },
        "runtime": runtime,
        "runtime_portability": runtime_portability,
        "active_task_portability": active_task_portability,
        "legacy_paths": legacy,
        "project_content_override": _simple_content_override_redundant(workspace, cfg, installation),
        "project_portability": project_portability_plan(workspace, installation_config=installation_config),
        "project_surface": project_surface_plan(workspace, project_id=project_id),
    }


def workspace_doctor(workspace_root: "str | Path", *, installation_config: "str | Path | None" = None) -> Dict[str, Any]:
    r = resolve_workspace(workspace_root, installation_config=installation_config)
    issues: List[str] = []
    warnings: List[str] = []
    if not r["base"]["valid"]:
        issues.append("resolved Base root is invalid")
    if not r["installation"]["exists"]:
        warnings.append("user installation config missing; compatibility resolution is in use")
    runtime = r.get("runtime") or {}
    if runtime.get("exists"):
        if not runtime.get("valid"):
            issues.append("project Runtime database is not healthy: " + "; ".join(runtime.get("issues") or []))
        elif runtime.get("base_version") and runtime.get("base_version") != active_version():
            issues.append(f"Runtime project contract={runtime.get('base_version')} != active {active_version()}; run project upgrade-contract before binding sync")
    else:
        warnings.append("project Runtime database not found; Base binding can be planned independently, project bootstrap remains explicit")
    runtime_portability = r.get("runtime_portability") or {}
    if runtime_portability.get("status") == "BLOCKED":
        issues.extend([f"Runtime portability: {msg}" for msg in runtime_portability.get("blockers") or []])
    elif runtime_portability.get("status") == "REBIND_AVAILABLE":
        warnings.append(f"Runtime machine root needs rebind: {runtime_portability.get('previous_root')} -> {runtime_portability.get('current_root')}")
    active_task_portability = r.get("active_task_portability") or {}
    if active_task_portability.get("status") == "REVIEW_REQUIRED":
        warnings.append(f"active task artifacts contain {len(active_task_portability.get('findings') or [])} actionable legacy Junction reference(s)")
    if not r["wiki"]["workspace_root"]:
        issues.append("Wiki workspace root unresolved")
    elif not Path(r["wiki"]["workspace_root"]).is_dir():
        issues.append("resolved Wiki workspace root does not exist")
    if not r["knowledge"]["resolved"]:
        warnings.append("Knowledge project scope unresolved; project-scoped search requires binding/registry mapping")
    elif not Path(r["knowledge"]["project_root"]).is_dir():
        issues.append("resolved Knowledge project root does not exist")
    if r["binding"]["exists"] and r["binding"]["base_version"] and r["binding"]["base_version"] != active_version():
        issues.append(f"project binding base_version={r['binding']['base_version']} != active {active_version()}")
    for name, info in r["legacy_paths"].items():
        if info["state"] == "LEGACY_LINK_TARGET_MISMATCH":
            issues.append(f"legacy link target mismatch: {name}")
        elif info["state"] == "LEGACY_LINK_SAFE_REMOVE":
            warnings.append(f"legacy link is no longer required after binding migration: {name}")
        elif info["state"] == "REAL_PROJECT_LOCAL_PATH" and name in BASE_LINK_DIRS:
            warnings.append(f"project-local Base-owned path exists and must not be auto-deleted: {name}")
    portability = r.get("project_portability") or {}
    surface = r.get("project_surface") or {}
    if portability.get("status") == "BLOCKED":
        issues.extend([f"project portability: {msg}" for msg in portability.get("blockers") or []])
    elif portability.get("status") == "SYNC_AVAILABLE":
        warnings.append("project-local Content Systems config contains removable machine-specific/redundant values")
    if surface.get("status") == "BLOCKED":
        issues.extend([f"project entry surface: {msg}" for msg in surface.get("blockers") or []])
    elif surface.get("status") == "SYNC_AVAILABLE":
        warnings.append("project README/AGENTS/.tp-spec README entry surface needs Base sync")
    binding_version_mismatch = bool(r["binding"]["exists"] and r["binding"]["base_version"] and r["binding"]["base_version"] != active_version())
    runtime_version_mismatch = bool(r.get("runtime",{}).get("exists") and r.get("runtime",{}).get("valid") and r.get("runtime",{}).get("base_version") and r.get("runtime",{}).get("base_version") != active_version())
    legacy_safe = any(info["state"] == "LEGACY_LINK_SAFE_REMOVE" for info in r["legacy_paths"].values())
    project_sync_available = r.get("project_portability",{}).get("status") == "SYNC_AVAILABLE" or r.get("project_surface",{}).get("status") == "SYNC_AVAILABLE"
    runtime_rebind_required = r.get("runtime_portability",{}).get("status") == "REBIND_AVAILABLE"
    active_task_review_required = r.get("active_task_portability",{}).get("status") == "REVIEW_REQUIRED"
    if not r["base"]["valid"] or any("legacy link target mismatch" in issue or "Runtime database is not healthy" in issue or "Runtime portability:" in issue or "project portability:" in issue or "project entry surface:" in issue for issue in issues):
        semantic_health = "UNSAFE"
    elif binding_version_mismatch or runtime_version_mismatch or runtime_rebind_required or active_task_review_required:
        semantic_health = "SYNC_REQUIRED"
    elif not r["installation"]["exists"]:
        semantic_health = "REPAIR_REQUIRED"
    elif not r["binding"]["exists"] or legacy_safe or project_sync_available:
        semantic_health = "SYNC_AVAILABLE"
    else:
        semantic_health = "HEALTHY"
    r["schema"] = "tp-spec.base-doctor/v1"
    r["status"] = "PASS" if not issues else "FAIL"
    r["health"] = semantic_health
    r["issues"] = issues
    r["warnings"] = warnings
    return r


def migration_plan_for_workspace(workspace_root: "str | Path", *, installation_config: "str | Path | None" = None) -> Dict[str, Any]:
    r = resolve_workspace(workspace_root, installation_config=installation_config)
    blockers: List[str] = []
    actions: List[Dict[str, Any]] = []
    if not r["base"]["valid"]:
        blockers.append("Base root invalid")
    if not r["installation"]["exists"]:
        blockers.append("installation config missing; configure global Base/Wiki/Knowledge roots first")
    if not r["wiki"]["workspace_root"]:
        blockers.append("Wiki workspace root unresolved")
    if not r["knowledge"]["resolved"] and r["legacy_paths"]["knowledge"]["exists"]:
        blockers.append("Knowledge project root unresolved while a legacy knowledge link exists")
    runtime = r.get("runtime") or {}
    if runtime.get("exists") and not runtime.get("valid"):
        blockers.append("project Runtime database is unhealthy; repair before Base binding migration")
    elif runtime.get("exists") and runtime.get("base_version") and runtime.get("base_version") != active_version():
        blockers.append(f"Runtime contract {runtime.get('base_version')} must be upgraded to {active_version()} before Base binding sync")
    runtime_portability = r.get("runtime_portability") or {}
    if runtime_portability.get("status") == "BLOCKED":
        blockers.extend([f"Runtime portability: {msg}" for msg in runtime_portability.get("blockers") or []])
    elif runtime_portability.get("status") == "REBIND_AVAILABLE":
        actions.append({
            "action": "REBIND_RUNTIME_ROOT",
            "db_path": runtime_portability.get("db_path"),
            "from": runtime_portability.get("previous_root"),
            "to": runtime_portability.get("current_root"),
        })
    active_task_portability = r.get("active_task_portability") or {}
    if active_task_portability.get("status") == "REVIEW_REQUIRED":
        actions.append({
            "action": "REVIEW_ACTIVE_TASK_LEGACY_REFERENCES",
            "count": len(active_task_portability.get("findings") or []),
            "findings": active_task_portability.get("findings") or [],
        })
    for name, info in r["legacy_paths"].items():
        if info["state"] == "LEGACY_LINK_TARGET_MISMATCH":
            blockers.append(f"{name} legacy link points to a different physical target")
        elif info["state"] == "LEGACY_LINK_SAFE_REMOVE":
            actions.append({"action":"REMOVE_LEGACY_LINK_AFTER_VERIFY","name":name,"path":info["path"],"target":info["resolved"]})
        elif info["state"] == "REAL_PROJECT_LOCAL_PATH" and name in BASE_LINK_DIRS:
            actions.append({"action":"MANUAL_REVIEW_REAL_PATH","name":name,"path":info["path"]})
    if not r["binding"]["exists"]:
        actions.insert(0, {"action":"WRITE_PROJECT_BINDING","path":r["binding"]["path"],"project_id":r["project_id"],"wiki_id":r["wiki"]["identity"].get("workspace_id") or "","knowledge_id":r["knowledge"].get("project_id") or ""})
    if r.get("project_portability",{}).get("status") == "BLOCKED":
        blockers.extend([f"project portability: {msg}" for msg in r["project_portability"].get("blockers") or []])
    elif r.get("project_portability",{}).get("status") == "SYNC_AVAILABLE":
        actions.append({"action":"NORMALIZE_PROJECT_CONTENT_CONFIG","path":r["project_portability"]["config_path"]})
    if r.get("project_surface",{}).get("status") == "BLOCKED":
        blockers.extend([f"project entry surface: {msg}" for msg in r["project_surface"].get("blockers") or []])
    elif r.get("project_surface",{}).get("status") == "SYNC_AVAILABLE":
        actions.append({"action":"SYNC_PROJECT_ENTRY_SURFACE","files":[row["path"] for row in r["project_surface"].get("files") or [] if row.get("changed")]})
    return {
        "schema":"tp-spec.base-migration-plan/v1",
        "status":"BLOCKED" if blockers else "READY",
        "workspace_root":r["workspace_root"],
        "project_id":r["project_id"],
        "blockers":blockers,
        "actions":actions,
        "resolution":r,
        "principle":"write binding -> re-resolve exact roots -> only then remove matching Junction/symlink objects; never delete real project-local directories",
    }


def _read_registry_workspace_roots(installation_config: Optional[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    installation = load_installation_config(installation_config)
    if installation.wiki_root:
        p=installation.wiki_root/"00-system"/"repo-registry.yaml"
        if p.is_file():
            try:
                data=yaml.safe_load(p.read_text(encoding="utf-8-sig")) or {}
                for ws in data.get("workspaces") or []:
                    if isinstance(ws,dict) and ws.get("workspace_root"):
                        rows.append({"id":str(ws.get("id") or ""),"root":str(ws["workspace_root"]),"enabled":True,"source":"wiki-registry"})
            except Exception:
                pass
    if installation.knowledge_root:
        p=installation.knowledge_root/"00-system"/"project-registry.yaml"
        if p.is_file():
            try:
                data=yaml.safe_load(p.read_text(encoding="utf-8-sig")) or {}
                for project in data.get("projects") or []:
                    if not isinstance(project,dict): continue
                    for raw in project.get("workspace_roots") or []:
                        rows.append({"id":str(project.get("id") or ""),"root":str(raw),"enabled":str(project.get("status") or "active")!="archived","source":"knowledge-registry"})
            except Exception:
                pass
    for p in dbmod.list_projects():
        root=p.get("root_path")
        if root:
            rows.append({"id":str(p.get("project_id") or ""),"root":str(root),"enabled":True,"source":"runtime-registry"})
    return rows


def _discover_under(search_root: Path, max_depth: int) -> List[Dict[str, Any]]:
    out=[]
    base_parts=len(search_root.resolve(strict=False).parts)
    for current, dirs, files in os.walk(search_root):
        cur=Path(current)
        depth=len(cur.resolve(strict=False).parts)-base_parts
        dirs[:] = [d for d in dirs if d not in SCAN_SKIP]
        if depth > max_depth:
            dirs[:] = []
            continue
        if ".tp-spec" in dirs:
            out.append({"id":"","root":str(cur.resolve(strict=False)),"enabled":True,"source":"filesystem-discovery"})
            dirs.remove(".tp-spec")
    return out


def _binding_id_for_root(root: Path) -> str:
    try:
        binding = load_project_binding(root)
        return binding.project_id if binding.exists else ""
    except Exception:
        return ""


def inventory_rows(*, installation_config: Optional[str]=None, inventory_path: Optional[str]=None, search_roots: Iterable[str]=(), max_depth: int=5) -> List[Dict[str, Any]]:
    rows=[]
    inv=load_workspace_inventory(inventory_path)
    for row in inv.workspaces:
        rows.append({**row,"source":"workspace-inventory"})
    rows.extend(_read_registry_workspace_roots(installation_config))
    for raw in search_roots:
        p=canonical_path(raw)
        if p.is_dir(): rows.extend(_discover_under(p,max_depth))
    merged: Dict[str, Dict[str, Any]]={}
    for row in rows:
        root=str(row.get("root") or row.get("workspace_root") or "").strip()
        if not root: continue
        rp=canonical_path(root); key=path_identity_key(rp)
        cur=merged.setdefault(key,{"id":str(row.get("id") or ""),"root":str(rp),"enabled":bool(row.get("enabled",True)),"sources":[]})
        if not cur["id"] and row.get("id"): cur["id"]=str(row["id"])
        src=str(row.get("source") or "unknown")
        if src not in cur["sources"]: cur["sources"].append(src)

    # Reconcile stale machine paths by stable project identity.  If exactly one
    # candidate has a matching portable project-binding, it wins.  If not, an
    # existing root wins only when unique.  Multiple live clones remain visible
    # and are marked as an identity conflict instead of being silently collapsed.
    by_id: Dict[str, List[Dict[str, Any]]] = {}
    anonymous: List[Dict[str, Any]] = []
    for item in merged.values():
        pid=str(item.get("id") or "").strip()
        if pid:
            by_id.setdefault(pid,[]).append(item)
        else:
            anonymous.append(item)
    reconciled: List[Dict[str, Any]] = list(anonymous)
    for pid, items in by_id.items():
        if len(items)==1:
            reconciled.append(items[0]); continue
        bound=[item for item in items if _binding_id_for_root(Path(item["root"]))==pid]
        chosen: Optional[Dict[str, Any]]=bound[0] if len(bound)==1 else None
        if chosen is None:
            existing=[item for item in items if Path(item["root"]).exists()]
            if len(existing)==1:
                chosen=existing[0]
        if chosen is not None:
            all_sources=[]
            for item in items:
                for src in item.get("sources") or []:
                    if src not in all_sources: all_sources.append(src)
            chosen=dict(chosen); chosen["sources"]=all_sources; chosen["reconciled_stale_roots"]=[item["root"] for item in items if item["root"]!=chosen["root"]]
            reconciled.append(chosen)
        else:
            for item in items:
                item=dict(item); item["identity_conflict"]="DUPLICATE_PROJECT_ID"; reconciled.append(item)
    return sorted(reconciled,key=lambda x:path_identity_key(x["root"]))


def reconcile_inventory_project(project_id: str, workspace_root: Path, inventory_path: Optional[str]=None) -> Optional[Path]:
    inv=load_workspace_inventory(inventory_path)
    if not inv.exists:
        return None
    rows=[dict(row) for row in inv.workspaces if str(row.get("id") or "") != project_id]
    rows.append({"id":project_id,"root":str(canonical_path(workspace_root)),"enabled":True})
    return write_workspace_inventory(rows,path=inventory_path or inv.path)


def _all_workspaces(args) -> List[Path]:
    if getattr(args,"all",False):
        rows=inventory_rows(installation_config=getattr(args,"installation_config",None),inventory_path=getattr(args,"inventory",None))
        return [Path(r["root"]) for r in rows if r.get("enabled",True)]
    return [Path(getattr(args,"workspace_root",".")).resolve(strict=False)]


def cmd_configure(args) -> int:
    try:
        result = configure_installation(
            base_root=args.base_root,
            wiki_root=args.wiki_root,
            knowledge_root=args.knowledge_root,
            installation_config=args.installation_config,
        )
        _emit(result)
        return 0 if result.get("status") == "PASS" else 1
    except Exception as exc:
        _emit({"schema":INSTALLATION_SCHEMA,"status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_installation_doctor(args) -> int:
    try:
        result = installation_doctor(args.installation_config)
        _emit(result)
        return 0 if result.get("status") == "PASS" else 1
    except Exception as exc:
        _emit({"schema":"tp-spec.installation-health/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_installation_migrate(args) -> int:
    try:
        result = installation_migration(args.installation_config, apply=bool(args.apply))
        _emit(result)
        return 1 if result.get("status") == "BLOCKED" else 0
    except Exception as exc:
        _emit({"schema":"tp-spec.installation-migration/v1","status":"BLOCKED","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_namespace_migrate(args) -> int:
    try:
        result = migrate_namespace(args.workspace_root, installation_config=args.installation_config, apply=bool(args.apply)) if args.apply else namespace_plan(args.workspace_root, installation_config=args.installation_config)
        _emit(result)
        return 1 if result.get("status") == "BLOCKED" else 0
    except Exception as exc:
        _emit({"schema":"tp-spec.namespace-migration/v1","status":"BLOCKED","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_resolve(args) -> int:
    try: _emit(resolve_workspace(args.workspace_root,installation_config=args.installation_config)); return 0
    except Exception as exc: _emit({"schema":"tp-spec.base-resolution/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_doctor(args) -> int:
    try:
        installation = installation_doctor(args.installation_config)
        rows=[workspace_doctor(p,installation_config=args.installation_config) for p in _all_workspaces(args)]
        status="PASS" if installation.get("status")=="PASS" and all(r["status"]=="PASS" for r in rows) else "FAIL"
        _emit({"schema":"tp-spec.base-doctor-batch/v1","status":status,"installation":installation,"projects":len(rows),"healthy":sum(1 for r in rows if r["status"]=="PASS"),"results":rows}); return 0 if status=="PASS" else 1
    except Exception as exc: _emit({"schema":"tp-spec.base-doctor-batch/v1","status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_inventory(args) -> int:
    try:
        rows=inventory_rows(installation_config=args.installation_config,inventory_path=args.inventory,search_roots=args.search_root or [],max_depth=args.max_depth)
        path=None
        if args.write:
            path=write_workspace_inventory(rows,path=args.inventory)
        _emit({"schema":INVENTORY_SCHEMA,"status":"PASS","read_only":not args.write,"count":len(rows),"path":str(path or (args.inventory or default_inventory_path())),"workspaces":rows}); return 0
    except Exception as exc: _emit({"schema":INVENTORY_SCHEMA,"status":"FAIL","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_migration_plan(args) -> int:
    try:
        rows=[migration_plan_for_workspace(p,installation_config=args.installation_config) for p in _all_workspaces(args)]
        status="READY" if all(r["status"]=="READY" for r in rows) else "BLOCKED"
        _emit({"schema":"tp-spec.base-migration-plan-batch/v1","status":status,"projects":len(rows),"ready":sum(1 for r in rows if r["status"]=="READY"),"results":rows}); return 0 if status=="READY" else 1
    except Exception as exc: _emit({"schema":"tp-spec.base-migration-plan-batch/v1","status":"BLOCKED","error":f"{type(exc).__name__}: {exc}"}); return 1


def _migrate_one(workspace: Path, args) -> Dict[str, Any]:
    plan=migration_plan_for_workspace(workspace,installation_config=args.installation_config)
    if plan["status"]!="READY":
        return {"workspace_root":str(workspace),"status":"BLOCKED","blockers":plan["blockers"],"changes":[]}
    r=plan["resolution"]
    changes=[]
    if not args.apply:
        return {"workspace_root":str(workspace),"status":"DRY_RUN","changes":plan["actions"],"blockers":[]}
    project_id=str(r.get("project_id") or "")
    if not PROJECT_ID_RE.match(project_id):
        return {"workspace_root":str(workspace),"status":"BLOCKED","blockers":[f"cannot infer valid project id: {project_id!r}"],"changes":[]}
    binding_path=write_project_binding(
        workspace,
        project_id=project_id,
        wiki_id=str(r["wiki"]["identity"].get("workspace_id") or ""),
        knowledge_id=str(r["knowledge"].get("project_id") or ""),
        base_version=active_version(),
    )
    changes.append({"action":"WRITE_PROJECT_BINDING","path":str(binding_path)})
    # Re-resolve after binding write; this is the safety boundary before link removal.
    after=resolve_workspace(workspace,installation_config=args.installation_config)
    if not after["base"]["valid"] or not after["wiki"]["workspace_root"]:
        return {"workspace_root":str(workspace),"status":"BLOCKED_AFTER_BINDING","blockers":["post-binding resolver verification failed"],"changes":changes}
    runtime_rebind = apply_runtime_rebind(workspace, project_id)
    if runtime_rebind.get("status") == "BLOCKED":
        return {"workspace_root":str(workspace),"status":"BLOCKED_AFTER_BINDING","blockers":runtime_rebind.get("blockers") or ["Runtime rebind blocked"],"changes":changes}
    if runtime_rebind.get("action") == "REBIND_RUNTIME_ROOT":
        changes.append({"action":"REBIND_RUNTIME_ROOT","db_path":runtime_rebind.get("db_path"),"from":runtime_rebind.get("previous_root"),"to":runtime_rebind.get("current_root"),"registry":runtime_rebind.get("registry_written")})
        inv_path = reconcile_inventory_project(project_id, workspace, getattr(args,"inventory",None))
        if inv_path:
            changes.append({"action":"RECONCILE_WORKSPACE_INVENTORY","path":str(inv_path),"project_id":project_id})
    if args.remove_legacy_links:
        for name, info in after["legacy_paths"].items():
            if info["state"]=="LEGACY_LINK_SAFE_REMOVE":
                p=Path(info["path"])
                _safe_remove_link(p)
                changes.append({"action":"REMOVE_LEGACY_LINK","name":name,"path":str(p),"target_preserved":info["resolved"]})
            elif info["state"]=="LEGACY_LINK_TARGET_MISMATCH":
                return {"workspace_root":str(workspace),"status":"BLOCKED_AFTER_BINDING","blockers":[f"link mismatch after binding: {name}"],"changes":changes}
    portability = normalize_project_portability(workspace, installation_config=args.installation_config, apply=True)
    if portability.get("status") == "BLOCKED":
        return {"workspace_root":str(workspace),"status":"BLOCKED_AFTER_BINDING","blockers":portability.get("blockers") or ["project portability normalization blocked"],"changes":changes}
    if portability.get("applied_action"):
        changes.append({"action":portability["applied_action"],"path":portability["config_path"]})
    surface = sync_project_surface(workspace, project_id=project_id, apply=True)
    if surface.get("status") == "BLOCKED":
        return {"workspace_root":str(workspace),"status":"BLOCKED_AFTER_BINDING","blockers":surface.get("blockers") or ["project entry surface sync blocked"],"changes":changes}
    changes.extend({"action":row["action"],"path":row["path"]} for row in surface.get("changes") or [])
    final=workspace_doctor(workspace,installation_config=args.installation_config)
    return {"workspace_root":str(workspace),"status":"PASS" if final["status"]=="PASS" else "WARN","changes":changes,"post_doctor":final}


def cmd_migrate(args) -> int:
    try:
        rows=[_migrate_one(p,args) for p in _all_workspaces(args)]
        bad=[r for r in rows if r["status"].startswith("BLOCKED")]
        status="BLOCKED" if bad else ("DRY_RUN" if not args.apply else "PASS")
        _emit({"schema":"tp-spec.base-migration/v1","status":status,"apply":bool(args.apply),"projects":len(rows),"results":rows}); return 1 if bad else 0
    except Exception as exc: _emit({"schema":"tp-spec.base-migration/v1","status":"BLOCKED","error":f"{type(exc).__name__}: {exc}"}); return 1


def cmd_sync_project(args) -> int:
    try:
        results=[]
        for workspace in _all_workspaces(args):
            resolution=resolve_workspace(workspace,installation_config=args.installation_config)
            project_id=str(resolution.get("project_id") or "")
            runtime_plan=resolution.get("runtime_portability") or runtime_rebind_plan(workspace,project_id)
            if runtime_plan.get("status")=="BLOCKED":
                results.append({"workspace_root":str(workspace),"status":"BLOCKED","runtime_portability":runtime_plan,"portability":None,"surface":None,"active_task_portability":resolution.get("active_task_portability")}); continue
            runtime_result=runtime_plan
            if args.apply and runtime_plan.get("status")=="REBIND_AVAILABLE":
                runtime_result=apply_runtime_rebind(workspace,project_id)
                if runtime_result.get("status")=="BLOCKED":
                    results.append({"workspace_root":str(workspace),"status":"BLOCKED","runtime_portability":runtime_result,"portability":None,"surface":None,"active_task_portability":resolution.get("active_task_portability")}); continue
                inv_path=reconcile_inventory_project(project_id,workspace,getattr(args,"inventory",None))
                if inv_path:
                    runtime_result=dict(runtime_result); runtime_result["inventory_reconciled"]=str(inv_path)
            portability=normalize_project_portability(workspace,installation_config=args.installation_config,apply=bool(args.apply))
            if portability.get("status")=="BLOCKED":
                results.append({"workspace_root":str(workspace),"status":"BLOCKED","runtime_portability":runtime_result,"portability":portability,"surface":None,"active_task_portability":resolution.get("active_task_portability")}); continue
            surface=sync_project_surface(workspace,project_id=project_id,apply=bool(args.apply))
            if surface.get("status")=="BLOCKED":
                status="BLOCKED"
            else:
                active=scan_active_task_portability(workspace)
                pending_runtime = (runtime_result.get("status")=="REBIND_AVAILABLE")
                pending_surface = surface.get("status")!="CURRENT" or portability.get("status")!="CURRENT"
                if active.get("status")=="REVIEW_REQUIRED":
                    status="SYNC_REQUIRED"
                elif pending_runtime or pending_surface:
                    status="SYNC_AVAILABLE"
                else:
                    status="PASS" if args.apply else "CURRENT"
                resolution["active_task_portability"]=active
            results.append({"workspace_root":str(workspace),"status":status,"runtime_portability":runtime_result,"portability":portability,"surface":surface,"active_task_portability":resolution.get("active_task_portability")})
        bad=[r for r in results if r["status"]=="BLOCKED"]
        if bad:
            overall="BLOCKED"
        elif any(r["status"]=="SYNC_REQUIRED" for r in results):
            overall="SYNC_REQUIRED"
        elif any(r["status"]=="SYNC_AVAILABLE" for r in results):
            overall="SYNC_AVAILABLE"
        else:
            overall="PASS" if args.apply else "CURRENT"
        _emit({"schema":"tp-spec.base-project-sync/v1","status":overall,"apply":bool(args.apply),"projects":len(results),"results":results})
        return 1 if bad else 0
    except Exception as exc:
        _emit({"schema":"tp-spec.base-project-sync/v1","status":"BLOCKED","error":f"{type(exc).__name__}: {exc}"}); return 1


def _common_workspace(p: argparse.ArgumentParser) -> None:
    p.add_argument("--workspace-root",default=".")
    p.add_argument("--installation-config",default=None)
    p.add_argument("--inventory",default=None)
    p.add_argument("--all",action="store_true",help="operate on enabled workspaces from the user inventory/registries")


def add_base_subparsers(root_subparsers) -> None:
    base=root_subparsers.add_parser("base",help="TP-Spec-Coding installation/project binding health and convergence")
    sub=base.add_subparsers(dest="base_cmd",required=True)
    p=sub.add_parser("configure",help="Create/update machine-local Base/Wiki/Knowledge installation roots")
    p.add_argument("--base-root",default=None); p.add_argument("--wiki-root",required=False,default=None); p.add_argument("--knowledge-root",required=False,default=None); p.add_argument("--installation-config",default=None); p.set_defaults(func=cmd_configure)
    p=sub.add_parser("installation-doctor",help="Validate the machine-local installation profile and local runtime registry placement")
    p.add_argument("--installation-config",default=None); p.set_defaults(func=cmd_installation_doctor)
    p=sub.add_parser("installation-migrate",help="Plan/apply recognized machine-local installation state migrations")
    p.add_argument("--installation-config",default=None); p.add_argument("--apply",action="store_true"); p.set_defaults(func=cmd_installation_migrate)
    p=sub.add_parser("namespace-migrate",help="Plan/apply one-shot legacy namespace cutover to tp-spec/.tp-spec, including resolved central Wiki metadata")
    p.add_argument("--workspace-root",default="."); p.add_argument("--installation-config",default=None); p.add_argument("--apply",action="store_true"); p.set_defaults(func=cmd_namespace_migrate)
    p=sub.add_parser("resolve",help="Resolve Base + project-scoped Wiki/Knowledge roots"); _common_workspace(p); p.set_defaults(func=cmd_resolve)
    p=sub.add_parser("doctor",help="Check installation/binding/Runtime portability/legacy-link health for one/all projects"); _common_workspace(p); p.set_defaults(func=cmd_doctor)
    p=sub.add_parser("inventory",help="Collect workspace roots from registries/inventory and optional bounded discovery"); p.add_argument("--installation-config",default=None); p.add_argument("--inventory",default=None); p.add_argument("--search-root",action="append",default=[]); p.add_argument("--max-depth",type=int,default=5); p.add_argument("--write",action="store_true"); p.set_defaults(func=cmd_inventory)
    p=sub.add_parser("migration-plan",help="Plan Junction-to-resolver convergence without writes"); _common_workspace(p); p.set_defaults(func=cmd_migration_plan)
    p=sub.add_parser("sync-project",help="Synchronize Runtime machine binding, portable project config, and project entry surface"); _common_workspace(p); p.add_argument("--apply",action="store_true"); p.set_defaults(func=cmd_sync_project)
    p=sub.add_parser("migrate",help="Write binding, rebind portable Runtime locator, normalize project config/entry docs, and optionally remove verified legacy links"); _common_workspace(p); p.add_argument("--apply",action="store_true"); p.add_argument("--remove-legacy-links",action="store_true"); p.add_argument("--remove-redundant-content-config",action="store_true",help="deprecated compatibility flag; portability normalization now runs on apply"); p.set_defaults(func=cmd_migrate)
