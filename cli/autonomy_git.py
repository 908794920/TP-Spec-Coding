# -*- coding: utf-8 -*-
"""Deterministic Git helpers for isolated Autonomous Maintenance workspaces."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional


class AutonomyGitError(RuntimeError):
    pass


def git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if check and proc.returncode != 0:
        raise AutonomyGitError(f"GIT_ERROR: git {' '.join(args)} @ {repo}: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def clone_independent(source: Path, target: Path, *, branch: str, staging_branch: Optional[str]) -> None:
    if target.exists():
        raise AutonomyGitError(f"AUTONOMY_REPO_TARGET_EXISTS: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "clone", "--no-hardlinks", "--branch", branch, str(source), str(target)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise AutonomyGitError(f"GIT_CLONE_FAILED: {source} -> {target}: {proc.stderr.strip() or proc.stdout.strip()}")
    if staging_branch:
        git(target, "checkout", "-B", staging_branch)


def is_git_repo(path: Path) -> bool:
    return path.is_dir() and (path / ".git").exists()


def head(repo: Path, ref: str = "HEAD") -> str:
    return git(repo, "rev-parse", ref)


def branch(repo: Path) -> str:
    return git(repo, "branch", "--show-current")


def dirty(repo: Path) -> bool:
    return bool(git(repo, "status", "--porcelain"))


def status_porcelain(repo: Path) -> List[str]:
    raw = git(repo, "status", "--porcelain")
    return [line for line in raw.splitlines() if line]


def fetch_local_ref(repo: Path, source_repo: Path, source_branch: str, target_ref: str) -> str:
    # No persistent remote is created.  This is observation only; it never merges,
    # rebases or resets the long-lived staging branch.
    git(repo, "fetch", "--no-tags", str(source_repo), f"refs/heads/{source_branch}:{target_ref}")
    return head(repo, target_ref)


def merge_base(repo: Path, left: str, right: str) -> str:
    return git(repo, "merge-base", left, right)


def commit_count(repo: Path, base: str, tip: str) -> int:
    value = git(repo, "rev-list", "--count", f"{base}..{tip}")
    return int(value or 0)


def changed_files(repo: Path, base: str, tip: str) -> List[str]:
    raw = git(repo, "diff", "--name-only", f"{base}..{tip}")
    return [x for x in raw.splitlines() if x.strip()]


def diff_stat(repo: Path, base: str, tip: str) -> str:
    return git(repo, "diff", "--stat", f"{base}..{tip}")


def commit_subjects(repo: Path, base: str, tip: str) -> List[str]:
    raw = git(repo, "log", "--format=%H%x09%s", f"{base}..{tip}")
    return [x for x in raw.splitlines() if x]


def repo_state_fingerprint(repo: Path) -> str:
    """Hash current git-visible worktree/index state for effects:[] guards."""
    raw = git(repo, "status", "--porcelain=v1", "-uall")
    head_value = head(repo)
    return hashlib.sha256((head_value + "\n" + raw + "\n").encode("utf-8")).hexdigest()


def assert_no_repo_mutation(repo: Path, before_fingerprint: str) -> None:
    after = repo_state_fingerprint(repo)
    if after != before_fingerprint:
        raise AutonomyGitError(f"UNDECLARED_REPO_MUTATION: effects:[] stage changed mutable repo {repo}")
