# -*- coding: utf-8 -*-
"""Machine-local TP-Spec-Coding installation lifecycle helpers."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from cli import db as dbmod
from cli.environment import (
    INSTALLATION_SCHEMA,
    EnvironmentConfigError,
    current_base_root,
    default_installation_path,
    load_installation_config,
    validate_base_root,
    write_installation_config,
)


def _dir_state(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {"path": None, "configured": False, "exists": False, "is_dir": False}
    return {"path": str(path), "configured": True, "exists": path.exists(), "is_dir": path.is_dir()}


def installation_doctor(
    installation_config: "str | Path | None" = None,
    *,
    executing_base_root: "str | Path | None" = None,
) -> Dict[str, Any]:
    path = Path(installation_config).resolve(strict=False) if installation_config else default_installation_path()
    result: Dict[str, Any] = {
        "schema": "ai-work.installation-health/v1",
        "path": str(path),
        "status": "FAIL",
        "health": "REPAIR_REQUIRED",
        "issues": [],
        "warnings": [],
        "actions": [],
    }
    if not path.is_file():
        result["issues"].append("installation config missing")
        result["actions"].append("RUN_BASE_CONFIGURE")
        return result
    try:
        cfg = load_installation_config(path)
    except Exception as exc:
        result["issues"].append(f"installation config invalid: {type(exc).__name__}: {exc}")
        result["actions"].append("REWRITE_WITH_BASE_CONFIGURE")
        return result

    base = validate_base_root(cfg.base_root) if cfg.base_root else {"root": None, "valid": False, "version": "", "missing": ["base.root"]}
    wiki = _dir_state(cfg.wiki_root)
    knowledge = _dir_state(cfg.knowledge_root)
    result.update({
        "configured_schema": cfg.data.get("schema"),
        "base": base,
        "wiki": wiki,
        "knowledge": knowledge,
        "runtime_registry": {
            "current": str(dbmod.registry_default_path()),
            "current_exists": dbmod.registry_default_path().is_file(),
            "legacy_base_local": str(dbmod.legacy_registry_default_path()),
            "legacy_exists": dbmod.legacy_registry_default_path().is_file(),
        },
    })
    if not base.get("valid"):
        result["issues"].append("configured Base root is invalid")
    if not wiki["configured"] or not wiki["is_dir"]:
        result["issues"].append("configured Wiki System Root is missing or not a directory")
    if not knowledge["configured"] or not knowledge["is_dir"]:
        result["issues"].append("configured Knowledge System Root is missing or not a directory")

    executing = Path(executing_base_root).resolve(strict=False) if executing_base_root else current_base_root()
    if cfg.base_root and os.path.normcase(str(cfg.base_root)) != os.path.normcase(str(executing)):
        result["warnings"].append(f"executing Base differs from installation base.root: {executing}")
        result["actions"].append("REVIEW_BASE_ROOT_DRIFT")
    if dbmod.legacy_registry_default_path().is_file():
        result["warnings"].append("legacy Base-local runtime registry exists; migrate it to machine-local ~/.ai-work state")
        result["actions"].append("RUN_BASE_INSTALLATION_MIGRATE")

    if result["issues"]:
        result["status"] = "FAIL"
        result["health"] = "REPAIR_REQUIRED"
    elif result["warnings"]:
        result["status"] = "PASS"
        result["health"] = "SYNC_REQUIRED"
    else:
        result["status"] = "PASS"
        result["health"] = "HEALTHY"
    return result


def configure_installation(
    *,
    base_root: "str | Path | None" = None,
    wiki_root: "str | Path | None" = None,
    knowledge_root: "str | Path | None" = None,
    installation_config: "str | Path | None" = None,
) -> Dict[str, Any]:
    """Create/update installation config while preserving omitted existing roots.

    Invalid existing config is never partially guessed: all required machine roots
    must be supplied explicitly before it can be replaced.
    """
    path = Path(installation_config).resolve(strict=False) if installation_config else default_installation_path()
    before = path.read_bytes() if path.is_file() else None
    existing = None
    invalid_existing = None
    if path.is_file():
        try:
            existing = load_installation_config(path)
        except Exception as exc:
            invalid_existing = exc

    if invalid_existing and not (base_root and wiki_root and knowledge_root):
        return {
            "schema": INSTALLATION_SCHEMA,
            "status": "BLOCKED",
            "path": str(path),
            "error": f"existing installation is invalid; provide all roots to repair: {type(invalid_existing).__name__}: {invalid_existing}",
        }

    base = Path(base_root).resolve(strict=False) if base_root else (existing.base_root if existing and existing.base_root else current_base_root())
    wiki = Path(wiki_root).resolve(strict=False) if wiki_root else (existing.wiki_root if existing else None)
    knowledge = Path(knowledge_root).resolve(strict=False) if knowledge_root else (existing.knowledge_root if existing else None)
    missing = [name for name, value in (("wiki_root", wiki), ("knowledge_root", knowledge)) if value is None]
    if missing:
        return {"schema": INSTALLATION_SCHEMA, "status": "BLOCKED", "path": str(path), "error": "missing required roots: " + ", ".join(missing)}
    base_health = validate_base_root(base)
    if not base_health["valid"]:
        return {"schema": INSTALLATION_SCHEMA, "status": "BLOCKED", "path": str(path), "error": "invalid Base root", "base": base_health}
    if not wiki.is_dir():
        return {"schema": INSTALLATION_SCHEMA, "status": "BLOCKED", "path": str(path), "error": f"Wiki System Root does not exist: {wiki}"}
    if not knowledge.is_dir():
        return {"schema": INSTALLATION_SCHEMA, "status": "BLOCKED", "path": str(path), "error": f"Knowledge System Root does not exist: {knowledge}"}

    write_installation_config(base_root=base, wiki_root=wiki, knowledge_root=knowledge, path=path)
    after = path.read_bytes()
    if before is None:
        action = "CREATED"
    elif before == after:
        action = "UNCHANGED"
    else:
        action = "UPDATED"
    health = installation_doctor(path, executing_base_root=current_base_root())
    return {
        "schema": INSTALLATION_SCHEMA,
        "status": "PASS" if health["status"] == "PASS" else "FAIL",
        "action": action,
        "path": str(path),
        "base_root": str(base),
        "wiki_root": str(wiki),
        "knowledge_root": str(knowledge),
        "health": health,
    }


def installation_migration(
    installation_config: "str | Path | None" = None,
    *,
    apply: bool = False,
    legacy_registry_path: Optional[str] = None,
    target_registry_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Migrate recognized machine-local installation state without guessing paths."""
    path = Path(installation_config).resolve(strict=False) if installation_config else default_installation_path()
    if not path.is_file():
        return {"schema": "ai-work.installation-migration/v1", "status": "BLOCKED", "path": str(path), "blockers": ["installation config missing"]}
    try:
        cfg = load_installation_config(path)
    except (EnvironmentConfigError, OSError, ValueError) as exc:
        return {"schema": "ai-work.installation-migration/v1", "status": "BLOCKED", "path": str(path), "blockers": [f"installation config invalid: {exc}"]}
    if cfg.data.get("schema") != INSTALLATION_SCHEMA:
        return {"schema": "ai-work.installation-migration/v1", "status": "BLOCKED", "path": str(path), "blockers": [f"unsupported installation schema: {cfg.data.get('schema')}"]}

    registry = dbmod.migrate_legacy_registry_to_user(
        apply=apply,
        legacy_path=legacy_registry_path,
        target_path=target_registry_path,
    )
    if registry["status"] == "BLOCKED":
        status = "BLOCKED"
    elif registry["status"] == "MIGRATION_AVAILABLE":
        status = "MIGRATION_AVAILABLE"
    elif registry["status"] == "MIGRATED":
        status = "PASS"
    else:
        status = "CURRENT"
    return {
        "schema": "ai-work.installation-migration/v1",
        "status": status,
        "apply": bool(apply),
        "path": str(path),
        "installation_schema": cfg.data.get("schema"),
        "runtime_registry": registry,
    }
