# -*- coding: utf-8 -*-
"""Shared filesystem path identity helpers.

Path strings are machine-local locators, not durable project identity.  This
module canonicalizes locators before equality/deduplication so Windows long-name
and 8.3 short-name aliases, symlinks and case variants resolve to one physical
identity whenever the filesystem can prove that relationship.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Union

PathLike = Union[str, os.PathLike[str], Path]


def canonical_path(value: PathLike) -> Path:
    """Return the best filesystem-canonical absolute path without requiring existence.

    ``Path.resolve(strict=False)`` is intentionally the primary operation: on
    Windows it expands existing 8.3 aliases to long names, and on all platforms
    it resolves existing symlink/junction components.  If the platform cannot
    resolve a broken/unavailable component, fall back to an absolute normalized
    path instead of failing a diagnostic/read path.
    """
    raw = os.path.expandvars(os.path.expanduser(os.fspath(value)))
    path = Path(raw)
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return Path(os.path.abspath(os.path.normpath(raw)))


def path_identity_key(value: PathLike) -> str:
    """Return a comparison key for one machine-local path locator."""
    text = os.path.normpath(str(canonical_path(value)))
    text = os.path.normcase(text)
    if len(text) > 1:
        text = text.rstrip("\\/")
    return text


def same_path(a: PathLike, b: PathLike) -> bool:
    """True when two locators resolve to the same canonical path identity."""
    return path_identity_key(a) == path_identity_key(b)
