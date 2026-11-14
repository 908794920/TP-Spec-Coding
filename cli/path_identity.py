# -*- coding: utf-8 -*-
"""Shared filesystem path identity helpers.

Path strings are machine-local locators, not durable project identity.  This
module canonicalizes locators before equality/deduplication so Windows long-name
and 8.3 short-name aliases, symlinks and case variants resolve to one physical
identity whenever the filesystem can prove that relationship.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Union

PathLike = Union[str, os.PathLike[str], Path]


def expand_path_text(value: str, *, windows: bool | None = None) -> str:
    """Expand configured path references once; literal: disables all expansion.

    Replacement values are opaque, including any dollar/percent characters.
    Diagnostics expose reference names only, never the path or environment values.
    """
    if value.startswith("literal:"):
        result = value[len("literal:"):]
    else:
        windows = os.name == "nt" if windows is None else windows
        # Delimited names preserve native names such as ProgramFiles(x86).
        pattern = r"\$\{([^{}\r\n]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)"
        if windows:
            pattern += r"|%([^%\r\n]+)%"
        missing = set()

        def replace(match: re.Match[str]) -> str:
            name = next(group for group in match.groups() if group is not None)
            if name not in os.environ:
                missing.add(name)
                return match.group(0)
            return os.environ[name]

        result = re.sub(pattern, replace, value)
        if missing:
            raise ValueError("UNDEFINED_PATH_VARIABLE: " + ", ".join(sorted(missing)))
        # Expand the user's tilde, not a tilde introduced by an environment value.
        if value.startswith("~"):
            result = os.path.expanduser(result)
    if not result.strip():
        raise ValueError("EMPTY_EXPANDED_PATH")
    return result


def path_config_text(value: PathLike) -> str:
    """Serialize a resolved path without reinterpreting its literal characters."""
    text = os.fspath(value)
    return "literal:" + text if any(c in text for c in "$%") or text.startswith(("~", "literal:")) else text


def canonical_path(value: PathLike) -> Path:
    """Return the best filesystem-canonical absolute path without requiring existence.

    ``Path.resolve(strict=False)`` is intentionally the primary operation: on
    Windows it expands existing 8.3 aliases to long names, and on all platforms
    it resolves existing symlink/junction components.  If the platform cannot
    resolve a broken/unavailable component, fall back to an absolute normalized
    path instead of failing a diagnostic/read path.
    """
    # PathLike values have already been resolved by their caller. Only external
    # strings are configuration syntax; never expand a filesystem path twice.
    raw = expand_path_text(value) if isinstance(value, str) else os.fspath(value)
    path = Path(raw)
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return Path(os.path.abspath(os.path.normpath(raw)))


def path_identity_key(value: PathLike) -> str:
    """Compare literal filesystem locators; resolve configuration syntax first."""
    text = os.path.normpath(str(canonical_path(Path(value))))
    text = os.path.normcase(text)
    if len(text) > 1:
        text = text.rstrip("\\/")
    return text


def same_path(a: PathLike, b: PathLike) -> bool:
    """True when two locators resolve to the same canonical path identity."""
    return path_identity_key(a) == path_identity_key(b)
