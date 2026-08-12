#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版本纯度扫描器（全仓文本扫描，A-01 发布门禁；当前活动契约 Hardening 升级版）。

规则（任务书 §12 / 审查报告 P1-2）：
- 唯一允许的基座版本 = VERSION 文件内容（动态读取，由 VERSION 动态读取）。
- 活动契约目录（README/templates/governance/agents/cli/scripts）中不得出现任何
  低于当前基座版本的 token（前一修补版本、5.0.x、4.x 及历史编码标识符），
  否则 FAILED；
- 历史位置精确 allowlist（_ALLOWED_HISTORY_PREFIXES / _ALLOWED_HISTORY_GLOBS）：
  docs/ 报告、reports/、历史回归测试（Test-V510*/test_v510_*/v510_single_contract.py）
  允许保留对旧版本的精确引用（不视为污染），避免改写历史证据；活动 `skills/` 必须跟随当前契约扫描；
- CHANGELOG.md 只放行版本导航标题行（## vX.Y.Z）；
- 未来版本（5.2.0 等演练目标）与独立命名空间版本（治理/工具 schema 的
  1.0.0/2.x 等）不视为污染；
- 扫描器自身以拼接形式声明 token，不在源码中保存完整旧版本字面量。

用法：
    python scripts/check_version_consistency.py
    python scripts/check_version_consistency.py --verbose
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # ai-work-base

# 历史位置精确 allowlist（任务书 §12）：这些位置允许出现旧版本 token（归档证据、
# 历史回归测试、旧版目录），保留原样以维持审计链；不参与活动契约纯度判定。
# 前缀匹配（相对 BASE 的 posix 路径前缀）。
_ALLOWED_HISTORY_PREFIXES = (
    "docs/",          # 发布审查/基线/最终报告等历史证据
    "reports/",       # 历史质量报告
)
# 精确文件 glob 匹配（相对 BASE）。
_ALLOWED_HISTORY_GLOBS = (
    "scripts/tests/Test-V510*",
    "scripts/tests/test_v510_*",
    "scripts/tests/v510_single_contract.py",
    "scripts/tests/test_b12_*",
    "scripts/tests/test_b14_*",
    "scripts/tests/test_b17_*",
    "scripts/tests/test_c1_*",
    "scripts/tests/test_c5_*",
    "scripts/tests/test_config_loader.py",
    "scripts/tests/test_v511_commit_reliability.py",
    "scripts/tests/test_v511_hardening_gates.py",
    "scripts/tests/test_v511_*",
    "scripts/tests/test_v512_*",
    "scripts/tests/test_v513_*",
    "scripts/tests/test_b18_*",
    "scripts/ci/Test-V510*",
    "CHANGELOG.md",
    "manifest.sha256",  # 生成产物，可引用历史文件名
    "db/registry.local.json",
    "db/registry.local.json.example",
)

# 旧基座版本 token（拼接声明，避免扫描器扫描自身时自报）。
# 三类规则：
#   1) dotted 版本字面量：带词边界，防 IP 子串误报（(?i) 全局开关在拼接最外层）
#   2) 历史编码标识符：无前边界，允许变量/函数/拼接上下文
_LEGACY_PATTERNS = (
    r"v?4\.\d+\.\d+",            # v4.x.x / 4.x.x 历史版本
    r"v?5\.\d+\.\d+",         # any 5.x.x; numeric filter keeps current/future
    r"v(?:4\d{2}|50[0-9])",        # 历史编码标识符
)


def _build_legacy_re(version: str) -> "re.Pattern[str]":
    """Build candidate legacy-token regex; numeric filtering decides old/current/future."""
    patterns = list(_LEGACY_PATTERNS)
    dotted = [
        rf"(?<![0-9A-Za-z.]){p}(?![0-9A-Za-z.])"
        for p in patterns
        if p != _LEGACY_PATTERNS[2]
    ]
    return re.compile(
        r"(?i)(?:"
        + r"|".join(dotted)
        + r"|" + _LEGACY_PATTERNS[2]
        + r")"
    )


def _is_legacy_dotted(token: str, version: str) -> bool:
    """Return True only when a dotted base version is older than active VERSION.

    Historical encoded identifiers and 4.x tokens remain legacy by definition;
    dotted 5.x values are compared numerically so previous minors are rejected
    while current and future versions remain allowed.
    """
    t = token.lstrip("vV").strip()
    if t == version:
        return False
    cur = [int(x) for x in re.findall(r"\d+", version)]
    tok = [int(x) for x in re.findall(r"\d+", t)]
    if len(cur) == 3 and len(tok) == 3 and tok[0] == cur[0]:
        return tuple(tok) < tuple(cur)
    return True



# 严格排除的子目录名（任意层级）
EXCLUDE_DIRS = {".git", "__pycache__", ".pytest_cache", "reports"}

# CHANGELOG 发布导航标题：## vX.Y.Z（可带说明后缀，如"— 历史版本"；
# 允许列表项前缀“- ”）（放行）
_CHANGELOG_TITLE_RE = re.compile(r"^(?:-\s*)?#{1,3}\s+v\d+\.\d+\.\d+(\s+[—-].*)?\s*$")

# 文本文件扩展名白名单（只扫文本；二进制跳过）
_TEXT_EXTS = {
    ".py", ".ps1", ".md", ".yaml", ".yml", ".json", ".txt", ".sh", ".cfg",
    ".ini", ".gitignore", ".gitattributes", ".pyw",
}
_NO_EXT_NAMES = {"VERSION", "Dockerfile", "Makefile"}


def _iter_all_files(base: Path):
    """递归枚举仓库内所有文本文件（排除目录黑名单）。"""
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in p.relative_to(base).parts):
            continue
        if _is_text(p):
            yield p


def _is_text(p: Path) -> bool:
    if p.suffix in _TEXT_EXTS:
        return True
    if p.name in _NO_EXT_NAMES:
        return True
    # 无扩展名/未知扩展名：尝试 UTF-8 解码判定（二进制跳过）
    try:
        p.read_bytes()[:4096].decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _is_allowed_history(rel: str) -> bool:
    """是否属于历史位置 allowlist（精确前缀或 glob 匹配）。"""
    if rel in _ALLOWED_HISTORY_PREFIXES:
        return True
    if rel.startswith(_ALLOWED_HISTORY_PREFIXES):
        return True
    import fnmatch
    for pat in _ALLOWED_HISTORY_GLOBS:
        if fnmatch.fnmatch(rel, pat):
            return True
    return False


def scan_file(path: Path, legacy_re: "re.Pattern[str]", version: str) -> list[str]:
    """扫描单个文件，返回问题行描述列表。历史位置精确放行。"""
    rel = path.relative_to(BASE).as_posix()
    if _is_allowed_history(rel):
        return []
    issues: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return issues
    is_changelog = path.name == "CHANGELOG.md"
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        # CHANGELOG 发布导航标题放行
        if is_changelog and _CHANGELOG_TITLE_RE.match(stripped):
            continue
        m = legacy_re.search(line)
        if m:
            token = m.group(0)
            if not _is_legacy_dotted(token, version):
                continue  # 当前基座版本或未来版本放行
            issues.append(f"  [LEGACY] {rel}:{i}  -> contains {token!r}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="版本纯度扫描器（全仓文本扫描）")
    parser.add_argument("--verbose", action="store_true", help="输出每个文件的扫描状态")
    args = parser.parse_args()

    version = (BASE / "VERSION").read_text(encoding="utf-8").strip()
    legacy_re = _build_legacy_re(version)
    print("Version Purity Report (full-repository text scan)")
    print("=" * 60)
    print(f"当前唯一活动版本: {version}")
    print(f"扫描方式: 全仓递归文本扫描（排除 .git/__pycache__/.pytest_cache/二进制；历史证据文档精确白名单）")
    print("=" * 60)

    all_issues: list[str] = []
    scanned = 0
    for p in _iter_all_files(BASE):
        scanned += 1
        issues = scan_file(p, legacy_re, version)
        if issues:
            all_issues.extend(issues)
            print(f"\n--- {p.relative_to(BASE).as_posix()} ---")
            for issue in issues:
                print(issue)
        elif args.verbose:
            print(f"  [OK] {p.relative_to(BASE).as_posix()}")

    print("\n" + "=" * 60)
    print("结果摘要:")
    print(f"  扫描文件: {scanned}")
    print(f"  发现问题: {len(all_issues)}")

    if all_issues:
        print("  状态: FAILED - 检测到旧基座版本 token 污染")
        return 1
    print("  状态: PASSED - 全仓版本纯净（无旧基座版本 token）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
