# -*- coding: utf-8 -*-
"""Lazy actor discovery from the governed Catalog, not signing authority."""
from __future__ import annotations

import argparse
from pathlib import Path

from . import config_loader


def load_role_catalog(base_root: str | Path | None = None) -> dict:
    return config_loader.load_config(
        "governance/role-catalog.yaml", schema_name="role-catalog",
        base_root=base_root, strict_unknown_fields=True, use_cache=True,
    )


def actor_ids(*, formal_only: bool = False, base_root: str | Path | None = None) -> tuple[str, ...]:
    catalog = load_role_catalog(base_root)
    roles = [row.get("workflow_role") for row in catalog["roles"]
             if not formal_only or row.get("type") == "workflow-role"]
    roles.append((catalog.get("human_actor") or {}).get("id"))
    if any(not isinstance(role, str) or not role.strip() for role in roles):
        raise ValueError("ROLE_CATALOG_INVALID: actor IDs must be non-empty strings")
    return tuple(sorted(set(roles)))


def actor_argument(*, formal_only: bool = False):
    """Argparse type: read the Catalog only for a selected actor argument."""
    def validate(value: str) -> str:
        roles = actor_ids(formal_only=formal_only)
        if value not in roles:
            raise argparse.ArgumentTypeError(f"unknown actor {value!r}; choose from {', '.join(roles)}")
        return value
    return validate
