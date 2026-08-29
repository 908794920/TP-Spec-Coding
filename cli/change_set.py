# -*- coding: utf-8 -*-
"""Deterministic, read-only Git content snapshots for TP-Spec workflow facts."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "tp-spec.change-set/v1"
_EXCLUDED_ROOTS = {".tp-spec", ".execution"}


class ChangeSetError(RuntimeError):
    pass


def _run_git(root: Path, *args: str, text: bool = True) -> str | bytes:
    try:
        cp = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=text,
            check=False,
        )
    except OSError as exc:
        raise ChangeSetError(f"git unavailable for {root}: {exc}") from exc
    if cp.returncode != 0:
        stderr = cp.stderr.strip() if text else cp.stderr.decode("utf-8", errors="replace").strip()
        raise ChangeSetError(f"git {' '.join(args)} failed in {root}: {stderr or 'exit ' + str(cp.returncode)}")
    return cp.stdout


def _git_root(candidate: str | Path) -> Path:
    path = Path(candidate).expanduser().resolve()
    if not path.exists():
        raise ChangeSetError(f"repo root does not exist: {path}")
    raw = str(_run_git(path, "rev-parse", "--show-toplevel")).strip()
    if not raw:
        raise ChangeSetError(f"unable to resolve git root: {path}")
    return Path(raw).resolve()


def _is_product_path(rel: str) -> bool:
    normalized = rel.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized:
        return False
    first = normalized.split("/", 1)[0]
    return first not in _EXCLUDED_ROOTS and first != ".git"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _path_record(root: Path, rel: str, *, tracked: bool) -> dict[str, Any]:
    path = root / rel
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"path": rel, "tracked": tracked, "kind": "deleted"}

    executable = bool(info.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    if stat.S_ISLNK(info.st_mode):
        target = os.readlink(path)
        return {
            "path": rel,
            "tracked": tracked,
            "kind": "symlink",
            "target": target,
            "executable": executable,
        }
    if stat.S_ISREG(info.st_mode):
        return {
            "path": rel,
            "tracked": tracked,
            "kind": "file",
            "size": info.st_size,
            "sha256": _sha256_file(path),
            "executable": executable,
        }
    return {
        "path": rel,
        "tracked": tracked,
        "kind": "other",
        "mode": stat.S_IFMT(info.st_mode),
    }


def _nul_paths(raw: bytes) -> list[str]:
    return sorted(
        value.decode("utf-8", errors="surrogateescape")
        for value in raw.split(b"\0")
        if value
    )


def _canonical_sha(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _capture_repo(root: Path) -> tuple[dict[str, Any], str]:
    head = str(_run_git(root, "rev-parse", "HEAD")).strip()
    head_tree = str(_run_git(root, "rev-parse", "HEAD^{tree}")).strip()
    if not head or not head_tree:
        raise ChangeSetError(f"repository has no valid HEAD baseline: {root}")

    tracked_raw = _run_git(root, "ls-files", "-z", text=False)
    untracked_raw = _run_git(root, "ls-files", "--others", "--exclude-standard", "-z", text=False)
    assert isinstance(tracked_raw, bytes) and isinstance(untracked_raw, bytes)
    tracked = [path for path in _nul_paths(tracked_raw) if _is_product_path(path)]
    untracked = [path for path in _nul_paths(untracked_raw) if _is_product_path(path)]

    records = [_path_record(root, path, tracked=True) for path in tracked]
    records.extend(_path_record(root, path, tracked=False) for path in untracked)
    records.sort(key=lambda row: (str(row["path"]), 0 if row["tracked"] else 1))
    product_digest = _canonical_sha(records)

    patch = _run_git(
        root,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--binary",
        "HEAD",
        "--",
        ".",
        ":(exclude).tp-spec",
        ":(exclude).tp-spec/**",
        ":(exclude).execution",
        ":(exclude).execution/**",
        text=False,
    )
    assert isinstance(patch, bytes)

    repo = {
        "root_locator": str(root),
        "head": head,
        "head_tree": head_tree,
        "tracked_patch_sha256": "sha256:" + hashlib.sha256(patch).hexdigest(),
        "product_digest": product_digest,
        "entries": records,
        "untracked": [row for row in records if not row.get("tracked")],
    }
    return repo, product_digest


def capture_change_set(repo_roots: Iterable[str | Path]) -> dict[str, Any]:
    roots = sorted({_git_root(value) for value in repo_roots}, key=lambda value: str(value))
    if not roots:
        raise ChangeSetError("at least one explicit repo root is required")

    repositories: list[dict[str, Any]] = []
    product_digests: list[str] = []
    for root in roots:
        repo, product_digest = _capture_repo(root)
        repositories.append(repo)
        product_digests.append(product_digest)

    content_digest = _canonical_sha(sorted(product_digests))
    snapshot_payload = {
        "content_digest": content_digest,
        "repositories": repositories,
    }
    return {
        "schema": SCHEMA,
        "content_digest": content_digest,
        "snapshot_digest": _canonical_sha(snapshot_payload),
        "repositories": repositories,
    }


def current_content_digest(repo_roots: Iterable[str | Path]) -> str:
    return str(capture_change_set(repo_roots)["content_digest"])


def same_product_content(expected_id: str, current: dict[str, Any]) -> bool:
    return bool(expected_id) and str(current.get("content_digest") or "") == str(expected_id)
