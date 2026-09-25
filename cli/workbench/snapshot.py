# -*- coding: utf-8 -*-
"""Build read-only snapshots for the local TP-Spec workbench.

This layer is presentation-only.  It reads installation/configuration files,
registries and Runtime databases without creating schemas, mutating ledgers or
inventing project/task identity.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import json
import sqlite3

import yaml

from cli import autonomy_profile
from cli import db as dbmod
from cli import event_presentation
from cli import event_contract
from cli import event_policies
from cli import environment
from cli import orchestration
from cli.workbench.evidence_view import build_evidence_view
from cli.content_systems import load_content_systems
from cli.knowledge import common as knowledge_common
from cli.path_identity import canonical_path, same_path
from cli.version import active_version
from cli.wiki import registry as wiki_registry

# States that get their own counter in `task_statistics`. Anything else (including a retired task)
# falls into `other` and is named in `other_states`, so the breakdown always adds up to `total`.
_STATE_BUCKETS = ("new", "active", "blocked", "completed", "cancelled")


def _problem(code: str, message: str, *, severity: str = "warning") -> Dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _health(problems: Iterable[Dict[str, str]], *, unavailable: bool = False) -> str:
    rows = list(problems)
    if unavailable:
        return "unavailable"
    if rows:
        return "degraded"
    return "healthy"


def _read_registry(registry_path: Optional[str] = None) -> Tuple[Path, List[Dict[str, Any]], Optional[str]]:
    path = dbmod.registry_read_path(registry_path)
    if not path.is_file():
        return path, [], None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return path, [], str(exc)
    if not isinstance(data, dict) or not isinstance(data.get("projects", []), list):
        return path, [], "registry root/projects must be an object/list"
    return path, [dict(row) for row in data.get("projects", []) if isinstance(row, dict)], None


def _registered_db_path(entry: Dict[str, Any]) -> Optional[Path]:
    raw = str(entry.get("db_path") or "").strip()
    if not raw:
        return None
    # Reuse the Runtime registry's existing legacy-relative compatibility rule.
    resolver = getattr(dbmod, "_resolve_project_db_abs", None)
    if callable(resolver):
        try:
            return canonical_path(resolver(raw))
        except Exception:
            pass
    path = Path(raw)
    if path.is_absolute():
        return canonical_path(path)
    return canonical_path(Path(dbmod.__file__).resolve().parents[1] / path)


def _runtime_health(db_path: Optional[Path], *, connection: Optional[sqlite3.Connection] = None) -> Tuple[str, List[str]]:
    if db_path is None:
        return "unconfigured", ["runtime db path missing"]
    if not db_path.is_file():
        return "missing", ["runtime database missing"]
    try:
        conn = connection if connection is not None else dbmod.connect_readonly(str(db_path))
        try:
            ok, details = dbmod.verify_schema(conn)
            return ("available" if ok else "invalid"), list(details)
        finally:
            if connection is None:
                conn.close()
    except sqlite3.Error as exc:
        return "unreadable", [str(exc)]


def _registered_project_view(entry: Dict[str, Any]) -> Dict[str, Any]:
    root_text = str(entry.get("root_path") or "").strip()
    root = canonical_path(root_text) if root_text else None
    db_path = _registered_db_path(entry)
    runtime_status, runtime_issues = _runtime_health(db_path)
    return {
        "project_id": str(entry.get("project_id") or ""),
        "name": str(entry.get("project_name") or entry.get("project_id") or ""),
        "root_path": str(root) if root else "",
        "root_exists": bool(root and root.exists()),
        "db_path": str(db_path) if db_path else "",
        "runtime_status": runtime_status,
        "runtime_issues": runtime_issues,
        "base_version": str(entry.get("base_version") or ""),
        "schema_version": entry.get("schema_version"),
    }


def _workspace_view(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(entry.get("id") or ""),
        "root": str(entry.get("root") or ""),
        "enabled": bool(entry.get("enabled")) if "enabled" in entry else None,
        "enabled_declared": "enabled" in entry,
    }


def _autonomy_profile_view(profile: Dict[str, Any]) -> Dict[str, Any]:
    canonical = profile.get("canonical") or {}
    autonomous = profile.get("autonomous") or {}
    policy = profile.get("policy") or {}
    discovery = policy.get("discovery") or {}
    workflow = profile.get("workflow") or {}
    return {
        "profile_id": str(profile.get("profile_id") or ""),
        "enabled": bool(profile.get("enabled")) if "enabled" in profile else None,
        "enabled_declared": "enabled" in profile,
        "canonical_root": str(canonical.get("workspace_root") or ""),
        "autonomous_root": str(autonomous.get("workspace_root") or ""),
        "confirmation_policy": str(workflow.get("confirmation_policy") or ""),
        "difficulty_ceiling": str(policy.get("difficulty_ceiling") or ""),
        "max_new_tasks_per_cycle": int(discovery.get("max_new_tasks_per_cycle")) if discovery.get("max_new_tasks_per_cycle") is not None else None,
    }


def _read_autonomy_profiles(user_root: Path) -> Tuple[List[Dict[str, Any]], Path, Optional[str]]:
    profiles_root = user_root / "autonomy" / "profiles"
    if not profiles_root.is_dir():
        return [], profiles_root, None
    profiles: List[Dict[str, Any]] = []
    try:
        for path in sorted(profiles_root.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict):
                raise ValueError(f"{path}: profile must be a mapping")
            errors = autonomy_profile.validate_profile(raw, check_paths=False)
            if errors:
                raise ValueError(f"{path}: {errors[0]}")
            profiles.append(raw)
    except Exception as exc:
        return [], profiles_root, str(exc)
    return sorted(profiles, key=lambda profile: str(profile.get("profile_id") or "")), profiles_root, None


def _read_skill_topology(base_root: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    try:
        topology = orchestration.load_role_topology(base_root)
        nodes = topology.get("nodes") or {}
        edges = topology.get("edges") or []
        return {
            "status": "available",
            "schema": str(topology.get("schema") or ""),
            "root_id": str(topology.get("root_id") or ""),
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "error": "",
        }, None
    except Exception as exc:
        return {
            "status": "unavailable",
            "schema": "",
            "root_id": "",
            "nodes": {},
            "edges": [],
            "node_count": 0,
            "edge_count": 0,
            "error": str(exc),
        }, str(exc)


def build_global_snapshot(
    *,
    home: "str | Path | None" = None,
    installation_path: "str | Path | None" = None,
    registry_path: Optional[str] = None,
    active_base_root: "str | Path | None" = None,
) -> Dict[str, Any]:
    problems: List[Dict[str, str]] = []
    version = active_version(active_base_root)
    user_root = environment.user_tp_spec_root(home)

    try:
        installation = environment.load_installation_config(installation_path, home=home)
        installation_error = ""
    except Exception as exc:
        installation = None
        installation_error = str(exc)
        problems.append(_problem("INSTALLATION_INVALID", f"全局安装配置不可读：{exc}", severity="error"))

    base_root = (installation.base_root if installation else None) or environment.current_base_root()
    base_check = environment.validate_base_root(base_root)
    base_configured = bool(installation and installation.exists and installation.base_root)
    if not installation or not installation.exists:
        problems.append(_problem("INSTALLATION_MISSING", "~/.tp-spec/installation.yaml 未配置"))
    if not base_check.get("valid"):
        problems.append(_problem("BASE_INVALID", f"Base 路径缺少必要文件：{', '.join(base_check.get('missing') or [])}", severity="error"))
    base_version = str(base_check.get("version") or "")
    if base_version and base_version != version:
        problems.append(_problem("BASE_VERSION_MISMATCH", f"Base 版本 {base_version} 与当前 Contract {version} 不一致"))

    wiki_root = installation.wiki_root if installation else None
    knowledge_root = installation.knowledge_root if installation else None
    if wiki_root and not wiki_root.exists():
        problems.append(_problem("WIKI_PATH_MISSING", f"Wiki 路径不存在：{wiki_root}"))
    if knowledge_root and not knowledge_root.exists():
        problems.append(_problem("KNOWLEDGE_PATH_MISSING", f"Knowledge 路径不存在：{knowledge_root}"))

    try:
        inventory = environment.load_workspace_inventory(home=home)
        inventory_error = ""
    except Exception as exc:
        inventory = None
        inventory_error = str(exc)
        problems.append(_problem("WORKSPACE_INVENTORY_INVALID", f"Workspace Inventory 不可读：{exc}"))

    effective_registry_path = registry_path
    if effective_registry_path is None and home is not None:
        # An explicit Home is a fixture/isolation boundary. Do not fall back to
        # the process user's registry or the legacy Base-local registry.
        effective_registry_path = str(user_root / "registry.local.json")
    reg_path, entries, reg_error = _read_registry(effective_registry_path)
    if reg_error:
        problems.append(_problem("REGISTRY_INVALID", f"Registry 不可读：{reg_error}", severity="error"))
    elif not reg_path.is_file():
        problems.append(_problem("REGISTRY_MISSING", "Registry 未配置"))

    projects = [_registered_project_view(row) for row in entries]
    for row in projects:
        if row["root_path"] and not row["root_exists"]:
            problems.append(_problem("PROJECT_ROOT_MISSING", f"工程 {row['project_id']} 根目录不存在：{row['root_path']}"))
        if row["runtime_status"] not in {"available", "unconfigured"}:
            problems.append(_problem("PROJECT_RUNTIME_UNAVAILABLE", f"工程 {row['project_id']} Runtime 状态：{row['runtime_status']}"))

    autonomy_profiles, autonomy_root, autonomy_error = _read_autonomy_profiles(user_root)
    if autonomy_error:
        problems.append(_problem("AUTONOMY_PROFILE_INVALID", f"自治维护配置不可读：{autonomy_error}"))

    topology_root = Path(active_base_root) if active_base_root else base_root
    skill_topology, topology_error = _read_skill_topology(topology_root)
    skill_topology["source_root"] = str(topology_root)
    if topology_error:
        problems.append(_problem("SKILL_TOPOLOGY_INVALID", f"能力拓扑图谱不可读：{topology_error}"))

    return {
        "title": "TP-Spec 全局配置",
        "generated_at": dbmod.now_iso(),
        "health": _health(problems, unavailable=bool(installation_error and reg_error)),
        "version": version,
        "user_root": str(user_root),
        "base": {
            "configured": base_configured,
            "source": "installation_config" if base_configured else "environment_resolution",
            "contract_version": version,
            "base_version": base_version,
            "root": str(base_root),
            "exists": base_root.exists(),
            "valid": bool(base_check.get("valid")),
            "version_match": bool(base_version and base_version == version),
            "configuration_error": installation_error,
        },
        "wiki": {
            "configured": bool(wiki_root),
            "path": str(wiki_root) if wiki_root else "",
            "exists": bool(wiki_root and wiki_root.exists()),
            "status": "available" if wiki_root and wiki_root.exists() else ("missing" if wiki_root else "unconfigured"),
        },
        "knowledge": {
            "configured": bool(knowledge_root),
            "path": str(knowledge_root) if knowledge_root else "",
            "exists": bool(knowledge_root and knowledge_root.exists()),
            "status": "available" if knowledge_root and knowledge_root.exists() else ("missing" if knowledge_root else "unconfigured"),
        },
        "workspace": {
            "inventory_path": str(inventory.path) if inventory else str(environment.default_inventory_path(home)),
            "configured": bool(inventory and inventory.exists),
            "count": len(inventory.workspaces) if inventory else 0,
            "workspaces": [_workspace_view(row) for row in (inventory.workspaces if inventory else [])],
            "default_workspace": "",
            "default_workspace_status": "not_defined",
            "error": inventory_error,
        },
        "resolver": {
            "status": "healthy" if base_check.get("valid") else "degraded",
            "base_root": str(base_root),
        },
        "registry": {
            "path": str(reg_path),
            "exists": reg_path.is_file(),
            "status": "invalid" if reg_error else ("available" if reg_path.is_file() else "unconfigured"),
            "project_count": len(projects),
            "error": reg_error or "",
        },
        "registered_projects": projects,
        "autonomy": {
            "configured": bool(autonomy_profiles),
            "status": "invalid" if autonomy_error else ("available" if autonomy_profiles else "unconfigured"),
            "profiles_path": str(autonomy_root),
            "profile_count": len(autonomy_profiles),
            "profiles": [_autonomy_profile_view(profile) for profile in autonomy_profiles],
            "execution_mode": "",
            "execution_mode_declared": False,
            "error": autonomy_error or "",
        },
        "skill_topology": skill_topology,
        "problems": problems,
    }


def _resolve_project_identity(workspace: Path, entries: List[Dict[str, Any]]) -> Tuple[str, str, Optional[Dict[str, Any]], List[Dict[str, str]]]:
    problems: List[Dict[str, str]] = []
    try:
        binding = environment.load_project_binding(workspace)
    except Exception as exc:
        binding = None
        problems.append(_problem("PROJECT_BINDING_INVALID", f"Project Binding 不可读：{exc}", severity="error"))

    exact_matches: List[Dict[str, Any]] = []
    for row in entries:
        root_text = str(row.get("root_path") or "").strip()
        if not root_text:
            continue
        try:
            if same_path(Path(root_text), workspace):
                exact_matches.append(row)
        except Exception:
            continue
    if len(exact_matches) > 1:
        problems.append(_problem("PROJECT_ROOT_AMBIGUOUS", f"Registry 中有多个工程指向当前根目录：{workspace}", severity="error"))

    if binding and binding.project_id:
        by_id = [row for row in entries if str(row.get("project_id") or "") == binding.project_id]
        entry = by_id[0] if len(by_id) == 1 else None
        if len(by_id) > 1:
            problems.append(_problem("PROJECT_ID_DUPLICATE", f"Registry 中 project_id 重复：{binding.project_id}", severity="error"))
        if exact_matches and all(str(row.get("project_id") or "") != binding.project_id for row in exact_matches):
            problems.append(_problem("PROJECT_IDENTITY_CONFLICT", "Project Binding 与 Registry 根目录映射不一致", severity="error"))
        return binding.project_id, "project-binding", entry, problems

    if len(exact_matches) == 1:
        row = exact_matches[0]
        return str(row.get("project_id") or ""), "registry-root", row, problems

    problems.append(_problem("PROJECT_IDENTITY_UNRESOLVED", "当前项目身份无法确认：缺少 Project Binding，Registry 也没有唯一的根目录精确匹配"))
    return "", "unresolved", None, problems


def _read_knowledge_projection_status(db_path: Path) -> Dict[str, Any]:
    if not db_path.is_file():
        return {"status": "missing", "database": str(db_path), "documents": 0, "chunks": 0, "issues": ["projection database missing"]}
    try:
        uri = db_path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            tables = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            issues: List[str] = []
            if "documents" not in tables or "chunks" not in tables:
                issues.append("projection schema incomplete")
            documents = conn.execute("SELECT count(*) FROM documents").fetchone()[0] if "documents" in tables else 0
            chunks = conn.execute("SELECT count(*) FROM chunks").fetchone()[0] if "chunks" in tables else 0
            return {
                "status": "available" if not issues else "degraded",
                "database": str(db_path),
                "documents": int(documents),
                "chunks": int(chunks),
                "issues": issues,
            }
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {"status": "unreadable", "database": str(db_path), "documents": 0, "chunks": 0, "issues": [str(exc)]}


def _latest_event_summaries(conn: sqlite3.Connection, task_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    ids = [str(v) for v in task_ids if str(v)]
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id,task_id,event_type,summary,created_at FROM task_event WHERE task_id IN ({marks}) ORDER BY id",
        ids,
    ).fetchall()
    latest: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        latest[str(row["task_id"])] = dict(row)
    return latest


def _verification_attention(conn: sqlite3.Connection, task_ids: Iterable[str]) -> int:
    ids = [str(v) for v in task_ids if str(v)]
    if not ids:
        return 0
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id,task_id,detail_json,summary FROM task_event WHERE event_type='VERIFICATION_COMPLETED' AND task_id IN ({marks}) ORDER BY id",
        ids,
    ).fetchall()
    latest: Dict[str, str] = {}
    for row in rows:
        detail = _parse_detail(row["detail_json"])
        latest[str(row["task_id"])] = event_contract.normalize_event_semantics("VERIFICATION_COMPLETED", detail)["decision"]
    return sum(1 for decision in latest.values() if decision in {"FAIL", "NEEDS_FIX"})


def _task_list_row(
    row: sqlite3.Row,
    latest: Dict[str, Dict[str, Any]],
    *,
    retired: bool = False,
    work_items: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    event = latest.get(str(row["task_id"])) or {}
    return {
        "task_id": str(row["task_id"] or ""),
        "title": str(row["title"] or ""),
        "state": str(row["current_state"] or ""),
        "retired": retired,
        "runtime_status": "UNKNOWN",
        "work_items": work_items or {},
        "phase": str(row["current_stage"] or ""),
        "owner": str(row["owner_role"] or ""),
        "updated_at": str(row["updated_at"] or ""),
        "completed_at": str(row["completed_at"] or ""),
        "summary": str(event.get("summary") or ""),
        "summary_source": "latest_event" if str(event.get("summary") or "").strip() else "not_recorded",
    }


def build_project_snapshot(
    workspace_root: "str | Path" = ".",
    *,
    registry_path: Optional[str] = None,
    installation_path: "str | Path | None" = None,
    base_root: "str | Path | None" = None,
    connection: Optional[sqlite3.Connection] = None,
    registry_entries: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    workspace = canonical_path(workspace_root)
    problems: List[Dict[str, str]] = []
    reg_path, entries, reg_error = _read_registry(registry_path)
    if reg_error:
        problems.append(_problem("REGISTRY_INVALID", f"Registry 不可读：{reg_error}", severity="error"))

    if registry_entries is not None:
        entries = registry_entries
    project_id, identity_source, entry, identity_problems = _resolve_project_identity(workspace, entries)
    problems.extend(identity_problems)

    try:
        binding = environment.load_project_binding(workspace)
    except Exception:
        binding = None

    project: Dict[str, Any] = {
        "project_id": project_id,
        "name": str((entry or {}).get("project_name") or project_id),
        "root_path": str(workspace),
        "contract_version": active_version(),
        "base_version": str((binding.base_version if binding else "") or (entry or {}).get("base_version") or ""),
        "identity_source": identity_source,
        "binding": {
            "path": str(binding.path) if binding else str(environment.default_binding_path(workspace)),
            "exists": bool(binding and binding.exists),
            "project_id": str(binding.project_id) if binding else "",
        },
        "runtime_status": "unconfigured",
        "runtime_db": "",
    }

    wiki: Dict[str, Any] = {"status": "unavailable", "path": "", "exists": False, "registry": "", "identity": {"resolved": False}}
    knowledge: Dict[str, Any] = {
        "status": "unavailable",
        "path": "",
        "exists": False,
        "registry": "",
        "project_scope": {"resolved": False, "project_id": "", "path": ""},
        "shared_scope": {"ids": [], "count": 0},
        "projection": {"status": "unavailable"},
    }
    try:
        cfg = load_content_systems(workspace, installation_config_path=installation_path,
                                   base_config_path=Path(base_root) / "governance/content-systems.yaml" if base_root else None)
        try:
            wiki_identity = wiki_registry.resolve_workspace_identity(cfg)
        except Exception as exc:
            wiki_identity = {"resolved": False, "workspace_id": "", "source": "error", "error": str(exc)}
            problems.append(_problem("WIKI_RESOLVER_ERROR", f"Wiki Resolver 失败：{exc}"))
        wiki = {
            "status": "available" if cfg.paths.wiki_system_root.exists() else "unconfigured",
            "path": str(cfg.paths.wiki_system_root),
            "exists": cfg.paths.wiki_system_root.exists(),
            "registry": str(cfg.paths.wiki_registry),
            "registry_exists": cfg.paths.wiki_registry.is_file(),
            "identity": wiki_identity,
            "layout": cfg.paths.wiki_layout,
        }
        try:
            kp = knowledge_common.resolve_knowledge_project(cfg, require=False)
        except Exception as exc:
            kp = {"resolved": False, "project_id": "", "project_root": None, "shared_ids": [], "source": "error", "error": str(exc)}
            problems.append(_problem("KNOWLEDGE_RESOLVER_ERROR", f"Knowledge Resolver 失败：{exc}"))
        knowledge = {
            "status": "available" if cfg.paths.knowledge_physical_root.exists() else "unconfigured",
            "path": str(cfg.paths.knowledge_physical_root),
            "exists": cfg.paths.knowledge_physical_root.exists(),
            "registry": str(cfg.paths.knowledge_registry),
            "registry_exists": cfg.paths.knowledge_registry.is_file(),
            "project_scope": {
                "resolved": bool(kp.get("resolved")),
                "project_id": str(kp.get("project_id") or ""),
                "path": str(kp.get("project_root") or ""),
                "exists": bool(kp.get("project_root") and Path(str(kp.get("project_root"))).exists()),
                "source": str(kp.get("source") or ""),
            },
            "shared_scope": {"ids": list(kp.get("shared_ids") or []), "count": len(kp.get("shared_ids") or [])},
            "projection": _read_knowledge_projection_status(cfg.paths.knowledge_projection_db),
        }
    except Exception as exc:
        problems.append(_problem("CONTENT_RESOLVER_ERROR", f"Wiki/Knowledge 配置解析失败：{exc}", severity="error"))

    task_index: List[Dict[str, Any]] = []
    # `new`/`active`/`blocked`/`completed`/`cancelled`/`other` partition `total` exactly. `other` is
    # the catch-all for tasks those buckets cannot express (retired, or a state outside
    # _STATE_BUCKETS); `other_states` names what went into it so the number is never a mystery.
    # `verification_attention` is a cross-cutting metric over the same tasks — it is NOT additive.
    stats = {"total": 0, "new": 0, "active": 0, "blocked": 0, "completed": 0, "cancelled": 0,
             "other": 0, "other_states": {}, "verification_attention": 0}
    in_progress: List[Dict[str, Any]] = []
    archived: List[Dict[str, Any]] = []
    db_path = _registered_db_path(entry or {}) if entry else None
    if db_path:
        project["runtime_db"] = str(db_path)
        status, issues = _runtime_health(db_path, connection=connection)
        project["runtime_status"] = status
        if status != "available":
            problems.append(_problem("RUNTIME_UNAVAILABLE", f"Runtime 数据库状态：{status}；{'；'.join(issues)}"))
        else:
            try:
                conn = connection if connection is not None else dbmod.connect_readonly(str(db_path))
                try:
                    if not conn.in_transaction:
                        conn.execute("BEGIN")
                    rows = conn.execute(
                        "SELECT task_id,title,current_state,current_stage,owner_role,updated_at,completed_at FROM task WHERE project_id=? ORDER BY updated_at DESC, task_id DESC",
                        (project_id,),
                    ).fetchall()
                    ids = [str(row["task_id"]) for row in rows]
                    retired_ids = {
                        task_id for task_id in ids
                        if event_policies.is_task_retired(conn, task_id)
                    }
                    # One WorkItem query for this project; no per-task scans or repairs.
                    from ..workitem_cmd import summarize_work_items
                    item_rows = conn.execute(
                        "SELECT w.* FROM work_item w JOIN task t ON t.task_id=w.task_id "
                        "WHERE t.project_id=? ORDER BY w.created_at,w.item_id", (project_id,)
                    ).fetchall()
                    items_by_task = {}
                    for item in item_rows:
                        items_by_task.setdefault(str(item["task_id"]), []).append(item)
                    milestone_facts = {}
                    for row in rows:
                        tid = str(row["task_id"])
                        facts = summarize_work_items(conn, row, rows=items_by_task.get(tid, []), retired=tid in retired_ids)
                        milestone_facts[tid] = {key: facts[key] for key in ("counts", "consistency", "summary", "current")}
                        if facts["issues"]:
                            problems.append(_problem("WORKITEM_DRIFT", f"{tid}: {facts['summary']}"))
                    latest = _latest_event_summaries(conn, ids)
                    stats["total"] = len(rows)
                    for row in rows:
                        if str(row["task_id"]) in retired_ids:
                            stats["other"] += 1
                            stats["other_states"]["RETIRED"] = stats["other_states"].get("RETIRED", 0) + 1
                            continue
                        state = str(row["current_state"] or "").upper()
                        key = state.lower()
                        if key in _STATE_BUCKETS:
                            stats[key] += 1
                        else:
                            # Never drop a task silently: total must stay reconstructible.
                            stats["other"] += 1
                            name = state or "UNRECORDED"
                            stats["other_states"][name] = stats["other_states"].get(name, 0) + 1
                    current_ids = [task_id for task_id in ids if task_id not in retired_ids]
                    stats["verification_attention"] = _verification_attention(conn, current_ids)
                    in_progress = [
                        _task_list_row(row, latest, work_items=milestone_facts[str(row["task_id"])])
                        for row in rows
                        if str(row["task_id"]) not in retired_ids
                        and str(row["current_state"] or "") in {"NEW", "ACTIVE", "BLOCKED"}
                    ][:10]
                    archived = [
                        _task_list_row(
                            row,
                            latest,
                            retired=str(row["task_id"]) in retired_ids,
                            work_items=milestone_facts[str(row["task_id"])],
                        )
                        for row in rows
                        if str(row["current_state"] or "") in {"COMPLETED", "CANCELLED"}
                        or str(row["task_id"]) in retired_ids
                    ]
                    task_index = [_task_list_row(row, latest, retired=str(row["task_id"]) in retired_ids,
                                                  work_items=milestone_facts[str(row["task_id"])]) for row in rows]
                    prow = conn.execute("SELECT project_name,base_version FROM project WHERE project_id=?", (project_id,)).fetchone()
                    if prow is not None:
                        project["name"] = str(prow["project_name"] or project["name"])
                        project["base_version"] = str(project["base_version"] or prow["base_version"] or "")
                finally:
                    if connection is None:
                        conn.close()
            except sqlite3.Error as exc:
                project["runtime_status"] = "unreadable"
                problems.append(_problem("RUNTIME_READ_ERROR", f"Runtime 数据库只读查询失败：{exc}", severity="error"))
    elif project_id:
        problems.append(_problem("RUNTIME_UNREGISTERED", "当前项目没有可确认的 Runtime Registry 记录"))

    if project.get("base_version") and project["base_version"] != active_version():
        problems.append(_problem("PROJECT_VERSION_MISMATCH", f"项目 Base 版本 {project['base_version']} 与当前 Contract {active_version()} 不一致"))

    summary = (
        f"项目共有 {stats['total']} 个任务：进行中 {stats['active']}，阻塞 {stats['blocked']}，已完成 {stats['completed']}。任务结单不代表整个项目完成；在途状态不证明执行者正在运行。"
        if project_id else "当前项目身份无法可靠确认，未生成任务统计推断。"
    )
    return {
        "title": "当前项目概况",
        "generated_at": dbmod.now_iso(),
        "health": _health(problems, unavailable=not bool(project_id)),
        "project": project,
        "wiki": wiki,
        "knowledge": knowledge,
        "registry": {"path": str(reg_path), "exists": reg_path.is_file(), "status": "invalid" if reg_error else ("available" if reg_path.is_file() else "unconfigured")},
        "task_statistics": stats,
        "task_index": task_index,
        "in_progress_tasks": in_progress,
        "archived_tasks": archived,
        "summary": summary,
        "problems": problems,
    }


def _parse_detail(raw: Any) -> Dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _resolve_task_db_readonly(task_id: str, *, db_path: "str | Path | None" = None, registry_path: Optional[str] = None) -> Tuple[Optional[Path], List[Dict[str, str]]]:
    problems: List[Dict[str, str]] = []
    if db_path:
        path = canonical_path(db_path)
        if not path.is_file():
            problems.append(_problem("TASK_DB_MISSING", f"Runtime 数据库不存在：{path}", severity="error"))
            return None, problems
        return path, problems

    _reg_path, entries, reg_error = _read_registry(registry_path)
    if reg_error:
        problems.append(_problem("REGISTRY_INVALID", f"Registry 不可读：{reg_error}", severity="error"))
        return None, problems
    matches: List[Path] = []
    for entry in entries:
        candidate = _registered_db_path(entry)
        if not candidate or not candidate.is_file():
            continue
        try:
            conn = dbmod.connect_readonly(str(candidate))
            try:
                row = conn.execute("SELECT task_id FROM task WHERE task_id=?", (task_id,)).fetchone()
                if row is not None:
                    matches.append(candidate)
            finally:
                conn.close()
        except sqlite3.Error:
            continue
    unique = list(dict.fromkeys(matches))
    if len(unique) > 1:
        problems.append(_problem("TASK_DB_AMBIGUOUS", f"task_id {task_id} 在多个 Runtime 数据库中存在", severity="error"))
        return None, problems
    if not unique:
        problems.append(_problem("TASK_NOT_FOUND", f"找不到 task_id：{task_id}"))
        return None, problems
    return unique[0], problems


def _event_view(row: Dict[str, Any]) -> Dict[str, Any]:
    detail = _parse_detail(row.get("detail_json"))
    event_type = str(row.get("event_type") or "")
    semantics = event_contract.normalize_event_semantics(event_type, detail)
    summary = str(row.get("summary") or "")
    return {
        "id": int(row.get("id") or 0),
        "source_event_id": int(row.get("id") or 0),
        "event_type": event_type,
        "from_state": str(row.get("from_state") or ""),
        "to_state": str(row.get("to_state") or ""),
        "from_stage": str(row.get("from_stage") or ""),
        "to_stage": str(row.get("to_stage") or ""),
        "actor": str(row.get("actor_role") or ""),
        "work_item_id": row.get("work_item_id"),
        "actor_agent": row.get("actor_agent"),
        "step_id": detail.get("step_id"),
        "participation_id": detail.get("session_id"),
        "plan_version": detail.get("plan_version"),
        "evidence_path": row.get("evidence_path"),
        "detail": detail,
        "summary": summary,
        "created_at": str(row.get("created_at") or ""),
        "operation": semantics["operation"],
        "decision": semantics["decision"],
        "result_status": semantics["result_status"],
        "milestone_id": semantics["milestone_id"],
        "source_kind": semantics["source_kind"],
        "presentation": event_presentation.resolve_event_presentation(
            event_type, semantics["decision"], semantics["result_status"]
        ),
    }


def build_task_snapshot(
    task_id: Optional[str],
    *,
    db_path: "str | Path | None" = None,
    registry_path: Optional[str] = None,
    base_root: "str | Path | None" = None,
    connection: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    task_id0 = str(task_id or "").strip()
    if not task_id0:
        problems = [_problem("TASK_ID_REQUIRED", "当前没有明确 task_id；不会自动选择最近任务")]
        return {
            "title": "当前任务进度",
            "generated_at": dbmod.now_iso(),
            "health": "unavailable",
            "task": {"task_id": "", "title": "", "risk_level": "", "flow_level": "", "state": "", "phase": "", "owner": "", "updated_at": ""},
            "workflow": {"completed_steps": [], "current_step": {}, "next_step": {}, "steps": [], "reference_steps": ["需求确认", "方案/规划", "实现", "验证", "交付", "Knowledge/Wiki 收敛", "完成"]},
            "latest_checkpoint": {},
            "blockers": [],
            "verification": {"status": "NOT_RECORDED", "summary": "", "created_at": ""},
            "evidence": [],
            "timeline": [],
            "summary": "当前没有明确任务。",
            "problems": problems,
        }

    resolved_db, problems = _resolve_task_db_readonly(task_id0, db_path=db_path, registry_path=registry_path)
    if not resolved_db:
        return {
            "title": "当前任务进度",
            "generated_at": dbmod.now_iso(),
            "health": "unavailable",
            "task": {"task_id": task_id0, "title": "", "risk_level": "", "flow_level": "", "state": "", "phase": "", "owner": "", "updated_at": ""},
            "workflow": {"completed_steps": [], "current_step": {}, "next_step": {}, "steps": [], "reference_steps": ["需求确认", "方案/规划", "实现", "验证", "交付", "Knowledge/Wiki 收敛", "完成"]},
            "latest_checkpoint": {}, "blockers": [], "verification": {"status": "NOT_RECORDED", "summary": "", "created_at": ""},
            "evidence": [], "timeline": [], "summary": "无法读取当前任务。", "problems": problems,
        }

    try:
        conn = connection if connection is not None else dbmod.connect_readonly(str(resolved_db))
        try:
            if not conn.in_transaction:
                conn.execute("BEGIN")
            row = conn.execute(
                "SELECT t.*,p.project_name,p.root_path AS project_root_path FROM task t LEFT JOIN project p ON p.project_id=t.project_id WHERE t.task_id=?",
                (task_id0,),
            ).fetchone()
            if row is None:
                problems.append(_problem("TASK_NOT_FOUND", f"找不到 task_id：{task_id0}"))
                raise LookupError(task_id0)
            task_row = dict(row)
            event_rows = [dict(e) for e in conn.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id", (task_id0,)).fetchall()]
            from cli.report_cmd import task_progress_facts
            progress_facts = task_progress_facts(conn, task_row, events=event_rows,
                                                 retired=event_policies.is_task_retired(conn, task_id0))
            try:
                workflow = orchestration.resolve_progress(task_id0, db_path=str(resolved_db), base_root=base_root, connection=conn)
            except Exception as exc:
                workflow = {
                    "completed_steps": [], "current_step": {}, "next_step": {}, "steps": [],
                    "reference_steps": ["需求确认", "方案/规划", "实现", "验证", "交付", "Knowledge/Wiki 收敛", "完成"],
                    "route": {}, "error": str(exc),
                }
                problems.append(_problem("WORKFLOW_UNRESOLVED", f"工作流无法可靠解析：{exc}"))
            if workflow.get("error") and not any(p["code"] == "WORKFLOW_UNRESOLVED" for p in problems):
                problems.append(_problem("WORKFLOW_UNRESOLVED", str(workflow["error"])))
            for issue in progress_facts["execution"]["issues"]:
                problems.append(_problem("EXECUTION_FACTS_INVALID", issue))
        finally:
            if connection is None:
                conn.close()
    except LookupError:
        return {
            "title": "当前任务进度",
            "generated_at": dbmod.now_iso(),
            "health": "unavailable",
            "task": {"task_id": task_id0, "title": "", "risk_level": "", "flow_level": "", "state": "", "phase": "", "owner": "", "updated_at": ""},
            "workflow": {"completed_steps": [], "current_step": {}, "next_step": {}, "steps": [], "reference_steps": ["需求确认", "方案/规划", "实现", "验证", "交付", "Knowledge/Wiki 收敛", "完成"]},
            "latest_checkpoint": {},
            "blockers": [],
            "verification": {"status": "NOT_RECORDED", "summary": "", "created_at": ""},
            "evidence": [],
            "timeline": [],
            "summary": "无法读取当前任务。",
            "problems": problems,
        }
    except sqlite3.Error as exc:
        problems.append(_problem("TASK_DB_READ_ERROR", f"Runtime 数据库只读查询失败：{exc}", severity="error"))
        return {
            "title": "当前任务进度", "generated_at": dbmod.now_iso(), "health": "unavailable",
            "task": {"task_id": task_id0, "title": "", "risk_level": "", "flow_level": "", "state": "", "phase": "", "owner": "", "updated_at": ""},
            "workflow": {"completed_steps": [], "current_step": {}, "next_step": {}, "steps": [], "reference_steps": []},
            "latest_checkpoint": {}, "blockers": [], "verification": {"status": "NOT_RECORDED", "summary": "", "created_at": ""},
            "evidence": [], "timeline": [], "summary": "Runtime 数据库不可读。", "problems": problems,
        }

    latest_checkpoint: Dict[str, Any] = {}
    verification: Dict[str, Any] = {"status": "NOT_RECORDED", "summary": "", "created_at": ""}
    current_blocker: Dict[str, Any] = {}
    for event in event_rows:
        detail = _parse_detail(event.get("detail_json"))
        if event.get("event_type") == "FACT" and detail.get("operation") == "CHECKPOINT":
            latest_checkpoint = {
                "summary": str(event.get("summary") or ""),
                "phase": str(detail.get("phase") or event.get("to_stage") or ""),
                "actor": str(event.get("actor_role") or ""),
                "created_at": str(event.get("created_at") or ""),
            }
        if event.get("event_type") == "VERIFICATION_COMPLETED" and str(event.get("actor_role") or "") == "tp-test-engineer":
            semantics = event_contract.normalize_event_semantics("VERIFICATION_COMPLETED", detail)
            from ..event_policies import verification_scope
            try:
                scope = verification_scope(detail)
                status = (semantics["decision"] or "NOT_RECORDED") + ("_TECHNICAL" if scope == "technical" else "")
            except ValueError:
                scope, status = "unknown", "UNKNOWN"
            verification = {
                "status": status,
                "verification_scope": scope,
                "checks": detail.get("checks") if isinstance(detail.get("checks"), list) else [],
                "result_status": semantics["result_status"],
                "source_kind": semantics["source_kind"],
                "summary": str(event.get("summary") or ""),
                "created_at": str(event.get("created_at") or ""),
            }
        if event.get("event_type") == "BLOCKER":
            current_blocker = {
                "reason": str(event.get("summary") or ""),
                "actor": str(event.get("actor_role") or ""),
                "created_at": str(event.get("created_at") or ""),
            }

    evidence = build_evidence_view(
        event_rows,
        task_id=task_id0,
        project_root=str(task_row.get("project_root_path") or ""),
    )
    blockers = [current_blocker] if str(task_row.get("current_state") or "") == "BLOCKED" and current_blocker else []

    timeline = [_event_view(event) for event in reversed(event_rows[-50:])]
    summary = ""
    summary_source = "not_recorded"
    task = {
        "task_id": task_id0,
        "title": str(task_row.get("title") or ""),
        "project_id": str(task_row.get("project_id") or ""),
        "project_name": str(task_row.get("project_name") or ""),
        "project_root": str(task_row.get("project_root_path") or ""),
        "risk_level": str(task_row.get("risk_level") or ""),
        "flow_level": str(task_row.get("flow_level") or ""),
        "state": str(task_row.get("current_state") or ""),
        "phase": str(task_row.get("current_stage") or ""),
        "owner": str(task_row.get("owner_role") or ""),
        "updated_at": str(task_row.get("updated_at") or ""),
        "completed_at": str(task_row.get("completed_at") or ""),
        "base_version": str(task_row.get("base_version") or ""),
        "runtime_db": str(resolved_db),
    }
    if task["base_version"] and task["base_version"] != active_version(base_root):
        problems.append(_problem("TASK_VERSION_MISMATCH", f"任务 Contract {task['base_version']} 与当前 Base {active_version(base_root)} 不一致"))
    return {
        "title": "当前任务进度",
        "generated_at": dbmod.now_iso(),
        "health": _health(problems),
        "task": task,
        "workflow": workflow,
        # summarize_work_items reads WHERE task_id=? but omits that key in its legacy projection.
        # Carry the confirmed query scope, not an ID/name-derived parent, into the graph response.
        "work_items": {**progress_facts["work_items"], "items": [
            {**item, "task_id": task_id0} for item in progress_facts["work_items"]["items"]
        ]},
        "work_sessions": progress_facts["work_sessions"],
        "data_support": {"work_unit": "work_item + tp-spec.work-unit/v1 when recorded; legacy metadata unknown", "agent_thread_binding": "not_provided",
                         "work_item_parent": "work_item.task_id", "dependencies": "work_item.depends_on_json"},
        "latest_checkpoint": latest_checkpoint,
        "blockers": blockers,
        "verification": verification,
        "evidence": evidence,
        "timeline": timeline,
        "summary": summary,
        "summary_source": summary_source,
        "problems": problems,
    }
