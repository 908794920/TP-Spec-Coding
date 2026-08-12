#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""manifest.sha256 生成/校验工具（A-01.1，Python 实现，UTF-8 字节安全）。

替代 PowerShell 版本（PowerShell 5.1 无法可靠处理中文文件名的 git 输出）。
- 生成：Git 工作树可见文件（已跟踪且实际存在 + 未跟踪但未忽略）→ 逐文件 SHA-256 → manifest.sha256
- 校验：--verify 重算并比较，缺失/不匹配即返回 1

用法：
    python scripts/update_manifest.py            # 生成
    python scripts/update_manifest.py --verify           # 开发工作树校验
    python scripts/update_manifest.py --verify-release   # Git 发布面校验（仅已跟踪文件）
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # TP-Spec-Coding repo root
MANIFEST = BASE / "manifest.sha256"


def git_ls_files() -> list[str]:
    """Return Git-visible working-tree files, not merely index entries.

    Real-task testing deliberately happens before commit.  A working-tree manifest
    therefore has to include new non-ignored source files and must not require
    tracked files that are currently deleted.
    """
    proc = subprocess.run(
        ["git", "-C", str(BASE), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        capture_output=True,
        check=True,
    )
    out: list[str] = []
    for rel in proc.stdout.decode("utf-8").split("\0"):
        if not rel or rel == "manifest.sha256":
            continue
        if (BASE / rel).is_file():
            out.append(rel)
    return sorted(set(out))


def git_tracked_files() -> list[str]:
    """Return existing Git-indexed files, excluding the manifest itself."""
    proc = subprocess.run(
        ["git", "-C", str(BASE), "ls-files", "--cached", "-z"],
        capture_output=True,
        check=True,
    )
    out: list[str] = []
    for rel in proc.stdout.decode("utf-8").split("\0"):
        if not rel or rel == "manifest.sha256":
            continue
        if (BASE / rel).is_file():
            out.append(rel)
    return sorted(set(out))


def git_untracked_files() -> list[str]:
    """Return visible non-ignored files that are not in the Git index."""
    proc = subprocess.run(
        ["git", "-C", str(BASE), "ls-files", "--others", "--exclude-standard", "-z"],
        capture_output=True,
        check=True,
    )
    return sorted(
        rel
        for rel in proc.stdout.decode("utf-8").split("\0")
        if rel and rel != "manifest.sha256" and (BASE / rel).is_file()
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def generate() -> int:
    tracked = git_ls_files()
    if not tracked:
        print("ERROR: Git-visible working tree returned no files; refusing empty manifest", file=sys.stderr)
        return 1
    lines = [
        "# SHA-256 Manifest for TP-Spec-Coding working tree",
        f"# Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')}",
        "# Generator: update_manifest.py (SHA-256, UTF-8 byte-safe)",
        "# Repository: TP-Spec-Coding/",
        "# Note: records Git-visible working-tree files (tracked-existing + untracked non-ignored), except this manifest",
        "#",
    ]
    for rel in sorted(tracked):
        p = BASE / rel
        if not p.is_file():
            print(f"ERROR: tracked file missing: {rel}", file=sys.stderr)
            return 1
        lines.append(f"{sha256_file(p)}  {rel}")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"manifest.sha256 regenerated: {len(tracked)} files")
    return 0


_DIRECTORY_MODE_IGNORES = {".git", ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache"}
_DIRECTORY_MODE_SUFFIX_IGNORES = {".pyc", ".pyo", ".coverage", ".tmp", ".db-wal", ".db-shm"}


def _dir_file_set() -> set[str]:
    """无 Git 模式：枚举稳定发布文件，忽略可再生运行缓存。"""
    out: set[str] = set()
    for p in BASE.rglob("*"):
        if not p.is_file():
            continue
        rel_path = p.relative_to(BASE)
        rel = rel_path.as_posix()
        if rel == "manifest.sha256":
            continue
        if any(part in _DIRECTORY_MODE_IGNORES for part in rel_path.parts):
            continue
        if p.suffix.lower() in _DIRECTORY_MODE_SUFFIX_IGNORES:
            continue
        if p.name.startswith("_t4_") or p.name.startswith("_probe"):
            continue
        out.add(rel)
    return out


def verify() -> int:
    if not MANIFEST.is_file():
        print("ERROR: manifest.sha256 missing", file=sys.stderr)
        return 1
    entries: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            print(f"ERROR: unparseable manifest line: {line}", file=sys.stderr)
            return 1
        entries[parts[1].strip()] = parts[0].upper()
    if not entries:
        print("ERROR: manifest has no entries", file=sys.stderr)
        return 1
    bad: list[str] = []
    for rel, expected in entries.items():
        p = BASE / rel
        if not p.is_file():
            bad.append(f"missing:{rel}")
            continue
        if sha256_file(p) != expected:
            bad.append(f"mismatch:{rel}")
    # 模式判定：有 .git 时校验实际 Git 可见工作树；无 .git（发布包）校验稳定目录文件集合。
    if (BASE / ".git").exists():
        actual_set = set(git_ls_files())
        mode = "git-working-tree"
    else:
        actual_set = _dir_file_set()
        mode = "directory"
    extra = sorted(actual_set - set(entries))
    gone = sorted(set(entries) - actual_set)
    bad += [f"untracked-in-manifest:{e}" for e in extra]
    bad += [f"not-tracked:{g}" for g in gone]
    if bad:
        print(f"ERROR: manifest recompute failed ({mode} mode): " + "; ".join(bad), file=sys.stderr)
        return 1
    print(f"{len(entries)} files recomputed OK ({mode} mode)")
    return 0


def _manifest_entries() -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise ValueError(f"unparseable manifest line: {line}")
        entries[parts[1].strip()] = parts[0].upper()
    return entries


def verify_release() -> int:
    """Verify the release surface against the Git index, not the loose worktree.

    Development verification intentionally includes visible untracked files so a
    patch can be tested before staging.  A release must be stricter: every file
    recorded in the manifest must already be Git-tracked, and no visible
    non-ignored file may remain untracked.  This prevents a local file (for
    example .github/workflows/ci.yml) from passing validation but being omitted
    from the final commit.
    """
    if not (BASE / ".git").exists():
        print("ERROR: --verify-release requires a Git checkout", file=sys.stderr)
        return 1
    if verify() != 0:
        return 1
    try:
        entries = set(_manifest_entries())
    except (OSError, ValueError) as exc:
        print(f"ERROR: release manifest parse failed: {exc}", file=sys.stderr)
        return 1

    tracked = set(git_tracked_files())
    untracked = set(git_untracked_files())
    bad: list[str] = []
    bad += [f"manifest-not-git-tracked:{rel}" for rel in sorted(entries - tracked)]
    bad += [f"tracked-missing-manifest:{rel}" for rel in sorted(tracked - entries)]
    bad += [f"untracked-release-file:{rel}" for rel in sorted(untracked)]
    if bad:
        print("ERROR: release manifest gate failed: " + "; ".join(bad), file=sys.stderr)
        return 1
    print(f"{len(entries)} files release-tracked OK (git-index mode)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="manifest.sha256 generator/verifier")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true", help="verify development working tree")
    mode.add_argument("--verify-release", action="store_true", help="verify Git-tracked release surface")
    args = parser.parse_args()
    if args.verify_release:
        return verify_release()
    return verify() if args.verify else generate()


if __name__ == "__main__":
    sys.exit(main())
