# -*- coding: utf-8 -*-
"""Shared Content Systems configuration and path resolution.

V5.2.5 keeps Wiki and Knowledge as first-class content systems while separating
logical project mounts from physical storage.  This module is the single resolver
used by both subsystems; ``cli.wiki.config`` remains a compatibility re-export.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
import os

from cli.config_loader import load_config
from cli.environment import load_installation_config, load_project_binding, resolve_base_root
from cli.path_identity import canonical_path, same_path

BASE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = BASE_ROOT / "governance" / "content-systems.yaml"


class ContentSystemsConfigError(ValueError):
    pass


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _path_value(value: Any, *, anchor: Path) -> Path:
    text = str(value or "").strip()
    if not text:
        raise ContentSystemsConfigError("empty path must be resolved by its caller")
    text = os.path.expandvars(os.path.expanduser(text))
    path = Path(text)
    if not path.is_absolute():
        path = anchor / path
    return canonical_path(path)


def _child_path(value: Any, *, anchor: Path, default: str) -> Path:
    text = str(value if value is not None else default).strip() or default
    return _path_value(text, anchor=anchor)




@dataclass(frozen=True)
class ContentPaths:
    workspace_root: Path
    tp_spec_root: Path
    wiki_logical_root: Path
    wiki_system_root: Path
    wiki_registry: Path
    knowledge_logical_root: Path
    knowledge_physical_root: Path
    knowledge_registry: Path
    knowledge_projection_db: Path
    knowledge_meta_root: Path
    base_root: Path
    installation_config: Path
    project_binding: Path
    wiki_layout: str
    knowledge_layout: str

    def as_dict(self) -> Dict[str, str]:
        return {
            "workspace_root": str(self.workspace_root),
            "tp_spec_root": str(self.tp_spec_root),
            "wiki_logical_root": str(self.wiki_logical_root),
            "wiki_system_root": str(self.wiki_system_root),
            "wiki_registry": str(self.wiki_registry),
            "knowledge_logical_root": str(self.knowledge_logical_root),
            "knowledge_physical_root": str(self.knowledge_physical_root),
            "knowledge_registry": str(self.knowledge_registry),
            "knowledge_projection_db": str(self.knowledge_projection_db),
            "knowledge_meta_root": str(self.knowledge_meta_root),
            "base_root": str(self.base_root),
            "installation_config": str(self.installation_config),
            "project_binding": str(self.project_binding),
            "wiki_layout": self.wiki_layout,
            "knowledge_layout": self.knowledge_layout,
        }


@dataclass(frozen=True)
class ResolvedConfig:
    data: Dict[str, Any]
    paths: ContentPaths
    # Wiki compatibility fields used by the existing Wiki runtime.
    source: Dict[str, Any]
    snapshot: Dict[str, Any]
    quality: Dict[str, Any]
    coverage: Dict[str, Any]
    # Knowledge subsystem configuration surfaces.
    knowledge: Dict[str, Any]
    knowledge_canonical: Dict[str, Any]
    knowledge_projection: Dict[str, Any]
    knowledge_retrieval: Dict[str, Any]
    knowledge_ingest: Dict[str, Any]
    knowledge_quality: Dict[str, Any]
    knowledge_evidence: Dict[str, Any]
    knowledge_evaluation: Dict[str, Any]


def _ratio(section: str, field: str, value: Any) -> None:
    if value is None:
        return
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ContentSystemsConfigError(f"{section}.{field} must be numeric within 0..1") from exc
    if not 0 <= number <= 1:
        raise ContentSystemsConfigError(f"{section}.{field} must be within 0..1")


def _positive_int(section: str, field: str, value: Any, *, allow_zero: bool = False) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        raise ContentSystemsConfigError(f"{section}.{field} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ContentSystemsConfigError(f"{section}.{field} must be an integer") from exc
    minimum = 0 if allow_zero else 1
    if number < minimum or (isinstance(value, float) and not value.is_integer()):
        label = "non-negative" if allow_zero else "positive"
        raise ContentSystemsConfigError(f"{section}.{field} must be a {label} integer")


def _validate_config(data: Dict[str, Any]) -> None:
    if data.get("schema") != "tp-spec.content-systems/v1":
        raise ContentSystemsConfigError("schema must be tp-spec.content-systems/v1")
    paths = data.get("paths")
    systems = data.get("systems")
    if not isinstance(paths, dict) or not isinstance(systems, dict):
        raise ContentSystemsConfigError("paths and systems must be mappings")
    for name in ("wiki", "knowledge"):
        if not isinstance(systems.get(name), dict):
            raise ContentSystemsConfigError(f"systems.{name} must be a mapping")

    wiki = systems["wiki"]
    if wiki.get("layout", "auto") not in {"auto", "workspace-root", "legacy-central"}:
        raise ContentSystemsConfigError("systems.wiki.layout must be auto|workspace-root|legacy-central")
    snap = wiki.get("snapshot", {})
    qual = wiki.get("quality", {})
    coverage = wiki.get("coverage", {})
    if not isinstance(snap, dict) or not isinstance(qual, dict) or not isinstance(coverage, dict):
        raise ContentSystemsConfigError("systems.wiki.snapshot, systems.wiki.quality and systems.wiki.coverage must be mappings")
    for field in ("mass_change_ratio", "bulk_cosmetic_ratio"):
        _ratio("systems.wiki.snapshot", field, snap.get(field))
    _positive_int("systems.wiki.snapshot", "mass_change_min_files", snap.get("mass_change_min_files"))
    for field in ("citation_line_coverage_target", "source_dependency_coverage_warn", "effective_wiki_coverage_warn", "initial_build_effective_coverage_min"):
        _ratio("systems.wiki.quality", field, qual.get(field))
    for field in ("semantic_audit_sample_docs", "filler_repetition_warn"):
        _positive_int("systems.wiki.quality", field, qual.get(field))
    for field in ("include_globs", "no_doc_globs", "excluded_extensions", "markdown_contract_roots"):
        value = coverage.get(field)
        if value is not None and not isinstance(value, list):
            raise ContentSystemsConfigError(f"systems.wiki.coverage.{field} must be a list")

    knowledge = systems["knowledge"]
    if knowledge.get("layout", "auto") not in {"auto", "vault-root"}:
        raise ContentSystemsConfigError("systems.knowledge.layout must be auto|vault-root")
    for field in ("canonical", "projection", "retrieval", "ingest", "quality", "evidence", "evaluation", "maintenance"):
        value = knowledge.get(field, {})
        if not isinstance(value, dict):
            raise ContentSystemsConfigError(f"systems.knowledge.{field} must be a mapping")
    projection = knowledge.get("projection", {})
    if projection.get("engine", "sqlite-fts5") != "sqlite-fts5":
        raise ContentSystemsConfigError("systems.knowledge.projection.engine currently supports only sqlite-fts5")
    if projection.get("graph_mode", "optional") not in {"optional", "disabled"}:
        raise ContentSystemsConfigError("systems.knowledge.projection.graph_mode must be optional|disabled")
    if projection.get("vector_mode", "retired-compatible") not in {"retired-compatible", "disabled"}:
        raise ContentSystemsConfigError("systems.knowledge.projection.vector_mode must be retired-compatible|disabled")
    legacy_databases = projection.get("legacy_databases")
    if legacy_databases is not None and not isinstance(legacy_databases, list):
        raise ContentSystemsConfigError("systems.knowledge.projection.legacy_databases must be a list")
    retrieval = knowledge.get("retrieval", {})
    if retrieval.get("strategy", "canonical-first-fts5") != "canonical-first-fts5":
        raise ContentSystemsConfigError("systems.knowledge.retrieval.strategy currently supports only canonical-first-fts5")
    if retrieval.get("default_scope", "project") not in {"project", "global"}:
        raise ContentSystemsConfigError("systems.knowledge.retrieval.default_scope must be project|global")
    for field in ("include_shared", "global_fallback", "source_fallback", "telemetry"):
        if field in retrieval and not isinstance(retrieval.get(field), bool):
            raise ContentSystemsConfigError(f"systems.knowledge.retrieval.{field} must be boolean")
    _positive_int("systems.knowledge.retrieval", "limit_default", retrieval.get("limit_default"))
    _positive_int("systems.knowledge.retrieval", "telemetry_retention_days", retrieval.get("telemetry_retention_days"))
    ingest = knowledge.get("ingest", {})
    _positive_int("systems.knowledge.ingest", "max_text_bytes", ingest.get("max_text_bytes"))
    for field in ("allowed_extensions", "hard_exclude_globs"):
        value = ingest.get(field)
        if value is not None and not isinstance(value, list):
            raise ContentSystemsConfigError(f"systems.knowledge.ingest.{field} must be a list")
    kqual = knowledge.get("quality", {})
    for field in ("semantic_audit_sample_docs", "filler_repetition_warn"):
        _positive_int("systems.knowledge.quality", field, kqual.get(field))
    for field in ("source_accountability_warn", "canonical_traceability_target", "index_freshness_target"):
        _ratio("systems.knowledge.quality", field, kqual.get(field))
    evidence = knowledge.get("evidence", {})
    for field in ("task_roots",):
        value = evidence.get(field)
        if value is not None and not isinstance(value, list):
            raise ContentSystemsConfigError(f"systems.knowledge.evidence.{field} must be a list")
    evaluation = knowledge.get("evaluation", {})
    _positive_int("systems.knowledge.evaluation", "limit", evaluation.get("limit"))
    maintenance = knowledge.get("maintenance", {})
    local_roots = maintenance.get("local_out_of_scope_roots")
    if local_roots is not None and not isinstance(local_roots, list):
        raise ContentSystemsConfigError("systems.knowledge.maintenance.local_out_of_scope_roots must be a list")


def load_content_systems(
    workspace_root: "str | Path" = ".",
    *,
    config_path: "str | Path | None" = None,
    base_config_path: "str | Path | None" = None,
    installation_config_path: "str | Path | None" = None,
) -> ResolvedConfig:
    workspace = canonical_path(workspace_root)
    base_path = Path(base_config_path) if base_config_path else DEFAULT_CONFIG
    base = load_config(base_path, use_cache=False)

    # User installation roots are global defaults. Project Content Systems remains
    # the highest-precedence override so exceptional workspaces stay possible.
    installation = load_installation_config(installation_config_path)
    install_override: Dict[str, Any] = {}
    if installation.exists:
        install_override = {
            "systems": {
                "wiki": {"root": str(installation.wiki_root) if installation.wiki_root else ""},
                "knowledge": {"root": str(installation.knowledge_root) if installation.knowledge_root else ""},
            }
        }
        base = _merge(base, install_override)

    override_path: Optional[Path]
    if config_path:
        override_path = Path(config_path)
        if not override_path.is_absolute():
            override_path = workspace / override_path
    else:
        override_path = workspace / ".tp-spec" / "config" / "content-systems.yaml"
    override: Dict[str, Any] = {}
    if override_path.is_file():
        override = load_config(override_path, use_cache=False)
        if "schema" not in override:
            override = {"schema": base.get("schema"), **override}
    data = _merge(base, override)
    _validate_config(data)

    path_cfg = data["paths"]
    systems = data["systems"]
    ai_work_text = str(path_cfg.get("tp_spec_root") or "").strip()
    ai_work = _path_value(ai_work_text, anchor=workspace) if ai_work_text else (workspace / ".tp-spec").resolve(strict=False)

    wiki_cfg = systems["wiki"]
    wiki_logical = (ai_work / "wiki").resolve(strict=False)
    wiki_root_text = str(wiki_cfg.get("root") or "").strip()
    wiki_system = _path_value(wiki_root_text, anchor=workspace) if wiki_root_text else wiki_logical
    requested_layout = str(wiki_cfg.get("layout") or "auto")
    legacy_registry = wiki_system / "00-system" / "repo-registry.yaml"
    if requested_layout == "auto":
        wiki_layout = "legacy-central" if legacy_registry.is_file() else "workspace-root"
    else:
        wiki_layout = requested_layout
    registry_text = str(wiki_cfg.get("registry") or "").strip()
    if registry_text:
        wiki_registry = _path_value(registry_text, anchor=workspace)
    elif legacy_registry.is_file() or wiki_layout == "legacy-central":
        wiki_registry = legacy_registry.resolve(strict=False)
    else:
        wiki_registry = (ai_work / "config" / "wiki-repos.yaml").resolve(strict=False)

    knowledge_cfg = systems["knowledge"]
    knowledge_logical = (ai_work / "knowledge").resolve(strict=False)
    knowledge_text = str(knowledge_cfg.get("root") or "").strip()
    knowledge_physical = _path_value(knowledge_text, anchor=workspace) if knowledge_text else knowledge_logical
    requested_knowledge_layout = str(knowledge_cfg.get("layout") or "auto")
    knowledge_layout = "vault-root" if requested_knowledge_layout == "auto" else requested_knowledge_layout
    kregistry_text = str(knowledge_cfg.get("registry") or "").strip()
    if kregistry_text:
        knowledge_registry = _path_value(kregistry_text, anchor=workspace)
    else:
        knowledge_registry = (knowledge_physical / "00-system" / "project-registry.yaml").resolve(strict=False)
    projection = dict(knowledge_cfg.get("projection") or {})
    knowledge_projection_db = _child_path(projection.get("database"), anchor=knowledge_physical, default=".ai-kb/knowledge.db")
    if not knowledge_projection_db.exists():
        for raw in projection.get("legacy_databases") or []:
            candidate = _child_path(raw, anchor=knowledge_physical, default=".ai-kb/knowledge.db")
            if candidate.is_file():
                knowledge_projection_db = candidate
                break
    knowledge_meta_root = _child_path(projection.get("meta_root"), anchor=knowledge_physical, default=".ai-kb/meta")

    binding = load_project_binding(workspace)
    paths = ContentPaths(
        workspace_root=workspace,
        tp_spec_root=ai_work,
        wiki_logical_root=wiki_logical,
        wiki_system_root=wiki_system,
        wiki_registry=wiki_registry,
        knowledge_logical_root=knowledge_logical,
        knowledge_physical_root=knowledge_physical,
        knowledge_registry=knowledge_registry,
        knowledge_projection_db=knowledge_projection_db,
        knowledge_meta_root=knowledge_meta_root,
        base_root=resolve_base_root(workspace, installation_path=installation_config_path),
        installation_config=installation.path,
        project_binding=binding.path,
        wiki_layout=wiki_layout,
        knowledge_layout=knowledge_layout,
    )
    return ResolvedConfig(
        data=data,
        paths=paths,
        source=dict(wiki_cfg.get("source") or {}),
        snapshot=dict(wiki_cfg.get("snapshot") or {}),
        quality=dict(wiki_cfg.get("quality") or {}),
        coverage=dict(wiki_cfg.get("coverage") or {}),
        knowledge=dict(knowledge_cfg),
        knowledge_canonical=dict(knowledge_cfg.get("canonical") or {}),
        knowledge_projection=projection,
        knowledge_retrieval=dict(knowledge_cfg.get("retrieval") or {}),
        knowledge_ingest=dict(knowledge_cfg.get("ingest") or {}),
        knowledge_quality=dict(knowledge_cfg.get("quality") or {}),
        knowledge_evidence=dict(knowledge_cfg.get("evidence") or {}),
        knowledge_evaluation=dict(knowledge_cfg.get("evaluation") or {}),
    )


def junction_relation(logical: Path, physical: Path) -> Dict[str, Any]:
    """Return informational mount status; never creates or rewrites a Junction."""
    logical = logical.resolve(strict=False)
    physical = physical.resolve(strict=False)
    exists = logical.exists() or logical.is_symlink()
    resolved = None
    try:
        if exists:
            resolved = logical.resolve(strict=False)
    except OSError:
        resolved = None
    return {
        "logical": str(logical),
        "physical": str(physical),
        "logical_exists": bool(exists),
        "logical_is_symlink": logical.is_symlink(),
        "resolved": str(resolved) if resolved else None,
        "matches": bool(resolved and same_path(resolved, physical)),
        "required": False,
    }
