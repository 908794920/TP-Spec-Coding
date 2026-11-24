# -*- coding: utf-8 -*-
"""Deterministic, read-only Git content snapshots for TP-Spec workflow facts."""
from __future__ import annotations

import hashlib
import copy
from concurrent.futures import ThreadPoolExecutor
from contextvars import Context
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any, Iterable
from . import command_context

SCHEMA = "tp-spec.change-set/v1"
OPS_SUBJECT_SCHEMA = "tp-spec.ops-subject/v1"
_EXCLUDED_ROOTS = {".tp-spec", ".execution"}


class ChangeSetError(RuntimeError):
    pass


def _run_git(root: Path, *args: str, text: bool = True) -> str | bytes:
    command_context.count("git_subprocesses")
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
    command_context.count("content_files_hashed")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        # 产品树以小文件为主，避免每次读取先分配 1 MiB；哈希范围不变。
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
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


def _capture_repo(root: Path, head: str, head_tree: str) -> tuple[dict[str, Any], str]:
    tracked_raw = _run_git(root, "ls-files", "-z", text=False)
    untracked_raw = _run_git(root, "ls-files", "--others", "--exclude-standard", "-z", text=False)
    assert isinstance(tracked_raw, bytes) and isinstance(untracked_raw, bytes)
    tracked = [path for path in _nul_paths(tracked_raw) if _is_product_path(path)]
    untracked = [path for path in _nul_paths(untracked_raw) if _is_product_path(path)]

    paths = [(path, True) for path in tracked] + [(path, False) for path in untracked]
    context = command_context.current()
    if context is not None and context.read_only_request and len(paths) >= 64:
        # 网页批量读取用有界线程隐藏本地文件 I/O 等待；每个文件仍读取真实字节。
        # 线程不继承请求上下文，计数由调用线程汇总，避免共享可变缓存。
        def read_batch(batch):
            return [_path_record(root, path, tracked=tracked_path) for path, tracked_path in batch]
        with ThreadPoolExecutor(max_workers=4) as pool:
            batches = pool.map(lambda batch: Context().run(read_batch, batch), [paths[i::4] for i in range(4)])
            records = [record for batch in batches for record in batch]
        command_context.count("content_files_hashed", sum(row["kind"] == "file" for row in records))
    else:
        records = [_path_record(root, path, tracked=tracked_path) for path, tracked_path in paths]
    records.sort(key=lambda row: (str(row["path"]), 0 if row["tracked"] else 1))
    product_digest = _canonical_sha(records)

    patch = _run_git(
        root,
        # A stat-only change must not make this read-only snapshot refresh the index.
        "-c",
        "diff.autoRefreshIndex=false",
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


@command_context.measured("changeset")
def capture_change_set(repo_roots: Iterable[str | Path]) -> dict[str, Any]:
    context = command_context.current()
    if context is None or not context.read_only_request:
        return _capture_change_set(repo_roots)
    # 只读页面在单次请求内复用同一组显式输入；下一请求重新读取。
    key = tuple(sorted({str(Path(value).expanduser().absolute()) for value in repo_roots}))
    if key not in context.change_set_cache:
        context.change_set_cache[key] = _capture_change_set(key)
    return copy.deepcopy(context.change_set_cache[key])


def _capture_change_set(repo_roots: Iterable[str | Path]) -> dict[str, Any]:
    identities: dict[Path, tuple[str, str]] = {}
    for value in repo_roots:
        path = Path(value).expanduser().resolve()
        if not path.exists():
            raise ChangeSetError(f"repo root does not exist: {path}")
        root, head, head_tree = str(_run_git(path, "rev-parse", "--show-toplevel", "HEAD", "HEAD^{tree}")).strip().rsplit("\n", 2)
        identities.setdefault(Path(root).resolve(), (head, head_tree))
    if not identities:
        raise ChangeSetError("at least one explicit repo root is required")

    repositories: list[dict[str, Any]] = []
    product_digests: list[str] = []
    for root, (head, head_tree) in sorted(identities.items(), key=lambda item: str(item[0])):
        repo, product_digest = _capture_repo(root, head, head_tree)
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


def is_ops_subject(detail: dict[str, Any]) -> bool:
    snapshot = detail.get("change_set")
    return isinstance(snapshot, dict) and snapshot.get("schema") == OPS_SUBJECT_SCHEMA


def capture_bound_product(detail: dict[str, Any], task_dir: str | Path | None, *,
                          repo_roots: Iterable[str | Path] | None = None) -> dict[str, Any]:
    """Re-read the recorded product identity using its existing evidence source."""
    if is_ops_subject(detail):
        if task_dir is None:
            raise ChangeSetError("ops subject requires a Task directory")
        from .ops_subject import capture
        return capture(task_dir, detail["change_set"].get("manifest_ref"))
    return capture_change_set((detail.get("repo_roots") or []) if repo_roots is None else repo_roots)


def same_product_content(expected_id: str, current: dict[str, Any]) -> bool:
    return bool(expected_id) and str(current.get("content_digest") or "") == str(expected_id)


def repository_keys(values: Iterable[str | Path]) -> set[str]:
    from .path_identity import path_identity_key
    return {path_identity_key(value) for value in values}


def same_bound_product_content(detail: dict[str, Any], current: dict[str, Any]) -> bool:
    """Keep history-only commits valid, but never swap content between repositories.

    Legacy single-repo facts can use their original content ID. A multi-repo fact
    without per-repository product digests must be re-recorded, never backfilled.
    """
    if not same_product_content(str(detail.get("change_set_id") or ""), current):
        return False
    bound = detail.get("change_set") or {}
    if not isinstance(bound, dict):
        return False
    if is_ops_subject(detail) or current.get("schema") == OPS_SUBJECT_SCHEMA:
        return (bound == current and is_ops_subject(detail)
                and not detail.get("repo_roots"))
    expected, actual = bound.get("repositories"), current.get("repositories")
    if not isinstance(expected, list) or not expected or not isinstance(actual, list):
        return False
    from .path_identity import path_identity_key
    def mapping(repositories):
        result = {}
        for repo in repositories:
            if not isinstance(repo, dict) or not isinstance(repo.get("root_locator"), str) or not repo["root_locator"]:
                return None
            key = path_identity_key(repo["root_locator"])
            if key in result:
                return None
            result[key] = repo.get("product_digest")
        return result
    left, right = mapping(expected), mapping(actual)
    if left is None or right is None or left.keys() != right.keys():
        return False
    roots = detail.get("repo_roots")
    if not isinstance(roots, list) or any(not isinstance(r, str) or not r.strip() for r in roots):
        return False
    if repository_keys(roots) != set(right):
        return False
    if len(left) == 1 and next(iter(left.values())) is None:
        return True
    return all(isinstance(v, str) and v.startswith("sha256:") and v == right[k] for k, v in left.items())
