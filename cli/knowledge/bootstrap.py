"""Explicit, add-only registration of an already bound Knowledge project."""
from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from pathlib import Path

import jsonschema
import yaml

from cli.config_loader import load_config
from cli.environment import load_project_binding
from .common import base_schema_path


def register_bound_project(cfg) -> dict:
    binding = load_project_binding(cfg.paths.workspace_root)
    project_id = binding.knowledge_id or binding.project_id
    if not binding.exists or not binding.project_id:
        raise ValueError("KNOWLEDGE_PROJECT_BINDING_REQUIRED: run project init for this workspace first")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", project_id):
        raise ValueError("KNOWLEDGE_INVALID_PROJECT_ID: review the existing project binding")

    path = cfg.paths.knowledge_registry
    before = path.read_bytes() if path.is_file() else None
    data = load_config(path, use_cache=False) if before is not None else {"registry_version": "1", "projects": []}
    schema = json.loads(base_schema_path("project-registry.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(data)
    ids = [row["id"] for field in ("projects", "shared_scopes") for row in data.get(field, [])]
    if len(ids) != len(set(ids)):
        raise ValueError("KNOWLEDGE_DUPLICATE_PROJECT: preserve and review the existing registry")
    if any(row["id"] == project_id for row in data.get("shared_scopes", [])):
        raise ValueError("KNOWLEDGE_PROJECT_SCOPE_CONFLICT: bound project id is already a shared scope")
    result = {"project_id": project_id, "registry": str(path), "binding": str(binding.path)}
    if any(row["id"] == project_id for row in data["projects"]):
        return {**result, "action": "UNCHANGED"}

    data["projects"].append({"id": project_id, "display_name": project_id, "status": "active"})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        mode = stat.S_IMODE(path.stat().st_mode) if before is not None else 0o644
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".knowledge-registry-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(yaml.safe_dump(data, allow_unicode=True, sort_keys=False).encode("utf-8"))
        os.chmod(temporary, mode)
        if (path.read_bytes() if path.is_file() else None) != before:
            raise ValueError("KNOWLEDGE_REGISTRY_CHANGED: read the current registry and retry")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {**result, "action": "CREATED" if before is None else "REGISTERED"}
