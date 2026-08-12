# -*- coding: utf-8 -*-
"""Source-topology analysis independent of the existing Wiki dependency graph.

The purpose is visibility, not architecture inference: new/deleted/moved source must
remain visible even when no old Wiki document already references it.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any, Dict, List, Tuple


def _module_key(path: str) -> str:
    parts = PurePosixPath(path).parts
    if not parts:
        return "."
    # Keep enough shape for common src/module layouts without assuming Maven only.
    if parts[0] == "src" and len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0]


def analyze_topology(changeset: Dict[str, Any]) -> Dict[str, Any]:
    changes = list(changeset.get("changes") or [])
    added = [c for c in changes if c.get("kind") == "STRUCTURAL" and c.get("reason") == "added"]
    deleted = [c for c in changes if c.get("kind") == "DELETED"]

    by_norm_added: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_norm_deleted: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for c in added:
        h = ((c.get("after") or {}).get("normalized_hash"))
        if h:
            by_norm_added[str(h)].append(c)
    for c in deleted:
        h = ((c.get("before") or {}).get("normalized_hash"))
        if h:
            by_norm_deleted[str(h)].append(c)

    moved: List[Dict[str, str]] = []
    consumed_added: set[str] = set()
    consumed_deleted: set[str] = set()
    for h in sorted(set(by_norm_added) & set(by_norm_deleted)):
        a = by_norm_added[h]
        d = by_norm_deleted[h]
        # Pair deterministically; ambiguous duplicate-content moves remain visible as adds/deletes.
        if len(a) == 1 and len(d) == 1:
            old = str(d[0].get("file"))
            new = str(a[0].get("file"))
            moved.append({"from": old, "to": new, "normalized_hash": h})
            consumed_added.add(new)
            consumed_deleted.add(old)

    pure_added = [str(c.get("file")) for c in added if str(c.get("file")) not in consumed_added]
    pure_deleted = [str(c.get("file")) for c in deleted if str(c.get("file")) not in consumed_deleted]

    added_modules = Counter(_module_key(p) for p in pure_added)
    deleted_modules = Counter(_module_key(p) for p in pure_deleted)
    findings: List[Dict[str, Any]] = []
    findings += [{"kind": "MOVED_SOURCE", **m, "requires_review": True} for m in moved]
    findings += [{"kind": "ADDED_SOURCE", "file": p, "module": _module_key(p), "requires_review": True} for p in pure_added]
    findings += [{"kind": "DELETED_SOURCE", "file": p, "module": _module_key(p), "requires_review": True} for p in pure_deleted]

    return {
        "moved": moved,
        "added": pure_added,
        "deleted": pure_deleted,
        "added_modules": dict(sorted(added_modules.items())),
        "deleted_modules": dict(sorted(deleted_modules.items())),
        "findings": findings,
        "requires_review": bool(findings),
    }
