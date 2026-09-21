#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版本戳分类报告器：区分「契约性版本声明」与「纯展示性版本戳」。

背景（2026-09-21 立的政策配套；见 docs/README.md「历史与过程文档政策」）：
活动基座版本 token 只要出现在 release-tracked 文件里，就必须跟随每次 open release
line 一起替换，否则 ``scripts/check_version_consistency.py`` 的版本纯度门禁会因
"低于当前版本的 token"直接 FAIL。本脚本按出现位置把每个 token 分类，回答两个问题：

1. 每个 token 出现在哪个文件的哪一行、为什么会在那里；
2. 去掉纯展示标签后，哪些文件就不再需要逐版替换（开版替换面能收窄多少）。

判定规则（**保守优先**：拿不准就进 review，绝不静默当成"可去"）
------------------------------------------------------------------
``keep``（语义必要，必须跟随版本）
  * Markdown frontmatter / YAML / JSON 里命中语义键：``version``、``base_version``、
    ``schema_version``、``supported_versions``、``status_contract``、``contract``(s)、
    ``*_ranges``、``artifact_contract`` 等；
  * 治理区间取值（方括号/圆括号包裹的版本区间）；
  * token 紧邻路径分隔符（目录名/文件名的一部分）；
  * Python 裸版本字面量（引号内只有版本号本身）；
  * Markdown 代码块内的示例/配置。

``stamp``（纯展示标签，可去）
  * 注释与 docstring 里的版本标记（Python / PowerShell / YAML / Markdown）；
  * Markdown 标题与正文里的版本标记；
  * frontmatter 里**非语义键**的值（如 ``description:``）；
  * 用户可见文字里嵌的版本号（``help=`` / ``description=`` / ``error=`` / ``message=`` /
    ``print(`` 等所在行）—— 可去，但会改变用户看到的文字。

``review``（需人工判断）
  * Markdown 表格行（可能是版本对照表）；
  * 引号内还有其它文字的取值（描述性文字 / 表单占位符）；
  * 其余无法可靠归类的字符串。

文件集与历史白名单直接复用 ``scripts/check_version_consistency.py``，因此
**报告口径与门禁口径一致**；被纯度白名单豁免的文件默认不参与统计（用
``--include-allowed`` 可以显式列出）。

用法：
    python scripts/classify_version_stamps.py              # 汇总 + 三个清单
    python scripts/classify_version_stamps.py --verbose    # 逐行展开每个出现位置
    python scripts/classify_version_stamps.py --json       # 机器可读
    python scripts/classify_version_stamps.py --include-allowed

退出码固定为 0：本脚本是报告工具，不是门禁。
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tokenize
from pathlib import Path

import check_version_consistency as cvc  # 复用同一文件集与历史白名单（刻意耦合）

BASE = Path(__file__).resolve().parents[1]

# 语义键：命中即认为该 token 是契约/模板版本声明，必须跟随开版替换。
_SEMANTIC_KEY_RE = re.compile(
    r"\b(?:version|base_version|schema_version|supported_versions|status_contract|"
    r"contract|contracts|governance_range|governance_ranges|template_version|"
    r"artifact_contract|spec_version|api_version)\b",
    re.IGNORECASE,
)
# Markdown 正文里的"规则/契约字段引用"：这类正文规定新任务必须写入什么
# （如 ``base_version: <版本>``），属随活动契约走的语义内容，不是展示标签。
# 刻意只认带下划线/复合的字段名，避免把普通散文里的 "version" 误判成 keep。
_PROSE_SEMANTIC_RE = re.compile(
    r"\b(?:base_version|artifact_contract|schema_version|supported_versions|"
    r"status_contract|contract_version)\b",
    re.IGNORECASE,
)
# 用户可见文字上下文：这些标记所在行里的版本号是展示性文字。
_PROSE_MARKERS = ("help=", "description=", "error=", "message=", "print(", "title=",
                  "notes=", "placeholder", "usage:")
# 长字符串阈值：超过它且含版本号的字符串更像描述性文字。
_LONG_STRING = 60
# 引号内除 token 外还有这么多字符时，认为它是描述性文字而不是取值。
_QUOTE_NOISE = 8
# Markdown 围栏与 frontmatter 标记
_FENCE_PREFIXES = ("```", "~~~")
_FRONTMATTER = "---"


def _ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="strict")
            except (OSError, ValueError):
                pass


def _token_re(version: str) -> "re.Pattern[str]":
    """匹配活动版本 token（允许 v/V 前缀），边界与纯度门禁保持同一形态。"""
    return re.compile(r"(?<![0-9A-Za-z.])[vV]?" + re.escape(version) + r"(?![0-9A-Za-z.])")


def _bare_re(version: str) -> "re.Pattern[str]":
    return re.compile(r"^[vV]?" + re.escape(version) + r"$")


def _line_hits(text: str, rx: "re.Pattern[str]") -> "dict[int, int]":
    """返回 {行号: 该行 token 出现次数}。"""
    hits: "dict[int, int]" = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        found = len(rx.findall(line))
        if found:
            hits[lineno] = found
    return hits


def _path_adjacent(line: str, match: "re.Match[str]") -> bool:
    """token 是否紧邻路径分隔符（说明它是目录/文件名的一部分）。"""
    before = line[match.start() - 1] if match.start() > 0 else ""
    after = line[match.end()] if match.end() < len(line) else ""
    return before in ("/", "\\") or after in ("/", "\\")


def _any_path_adjacent(line: str, rx: "re.Pattern[str]") -> bool:
    return any(_path_adjacent(line, m) for m in rx.finditer(line))


def _range_like(line: str, rx: "re.Pattern[str]") -> bool:
    """治理区间取值：token 邻近 ``[`` ``]`` ``(`` ``)`` ``,`` ``<`` ``>`` 之一。"""
    for match in rx.finditer(line):
        window = line[max(0, match.start() - 6): match.end() + 8]
        if any(ch in window for ch in "[](),<>"):
            return True
    return False


def _quote_noise(line: str, match: "re.Match[str]") -> int:
    """若 token 落在引号内，返回引号内除 token 外的字符数；不在引号内返回 -1。"""
    for quote in ("\"", "'"):
        start = line.rfind(quote, 0, match.start())
        if start < 0:
            continue
        end = line.find(quote, match.end())
        if end < 0:
            continue
        if line.count(quote, start, match.end()) % 2 == 1:
            return len(line[start + 1: end]) - (match.end() - match.start())
    return -1


def _descriptive_value(line: str) -> bool:
    """字段值是否为描述性文字（含句读或过长），而不是简短的结构化取值。"""
    if ":" not in line:
        return False
    value = line.split(":", 1)[1].strip()
    if not value:
        return False
    return any(ch in value for ch in ";。，") or len(value) >= _LONG_STRING


def _classify_markdown(text: str, rx: "re.Pattern[str]") -> "dict[int, tuple[str, str]]":
    out: "dict[int, tuple[str, str]]" = {}
    in_fence = False
    in_frontmatter = False
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        is_fence_line = stripped.startswith(_FENCE_PREFIXES)
        is_frontmatter_line = stripped == _FRONTMATTER
        match = rx.search(line)
        if match:
            if in_fence:
                out[lineno] = ("keep", "Markdown 代码块内的示例/配置")
            elif in_frontmatter:
                if (_SEMANTIC_KEY_RE.search(line) or _any_path_adjacent(line, rx)
                        or _range_like(line, rx)):
                    out[lineno] = ("keep", "frontmatter 语义键/路径/区间取值")
                else:
                    out[lineno] = ("stamp", "frontmatter 非语义键值里的版本标记")
            elif stripped.startswith("#"):
                out[lineno] = ("stamp", "Markdown 标题里的版本标记")
            elif "|" in line:
                out[lineno] = ("review", "Markdown 表格行：可能是版本对照表")
            elif _any_path_adjacent(line, rx):
                out[lineno] = ("review", "紧邻路径分隔符：目录名/文件名里的版本号")
            elif _PROSE_SEMANTIC_RE.search(line):
                out[lineno] = ("keep", "Markdown 正文里的规则/契约字段引用（随契约跟随）")
            else:
                out[lineno] = ("stamp", "Markdown 正文里的版本标记")
        if is_frontmatter_line:
            in_frontmatter = not in_frontmatter
        elif is_fence_line:
            in_fence = not in_fence
    return out


def _classify_structured(text: str, rx: "re.Pattern[str]", comment: bool
                         ) -> "dict[int, tuple[str, str]]":
    """YAML / JSON 通用分类（``comment=False`` 时按 JSON 处理，无注释）。"""
    out: "dict[int, tuple[str, str]]" = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        match = rx.search(line)
        if not match:
            continue
        if comment and line.lstrip().startswith("#"):
            out[lineno] = ("stamp", "YAML 注释里的版本标记")
            continue
        if _SEMANTIC_KEY_RE.search(line) or _any_path_adjacent(line, rx) or _range_like(line, rx):
            out[lineno] = ("keep", "YAML/JSON 语义键、路径或区间取值")
        elif any(marker in line for marker in _PROSE_MARKERS) or _quote_noise(line, match) >= _QUOTE_NOISE:
            out[lineno] = ("review", "引号内还有其它文字：描述性取值/占位符，需人工判断")
        elif _descriptive_value(line):
            out[lineno] = ("review", "字段值里的描述性文字（非门控字段），需人工判断")
        else:
            out[lineno] = ("keep", "YAML/JSON 字段值：契约/模板版本声明")
    return out


def _ps1_comments(text: str) -> "set[int]":
    """返回 PowerShell 注释行号集合（含 <# ... #> 块注释）。"""
    lines: "set[int]" = set()
    in_block = False
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if in_block:
            lines.add(lineno)
            if "#>" in stripped:
                in_block = False
            continue
        if stripped.startswith("<#"):
            lines.add(lineno)
            if "#>" not in stripped[2:]:
                in_block = True
            continue
        if stripped.startswith("#"):
            lines.add(lineno)
    return lines


def _docstring_lines(text: str) -> "set[int]":
    """模块/类/函数 docstring 覆盖的行号（ast 精确判定）。"""
    covered: "set[int]" = set()
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return covered
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", [])
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            end = getattr(value, "end_lineno", None) or value.lineno
            covered.update(range(value.lineno, end + 1))
    return covered


def _string_body(raw: str) -> str:
    body = raw.lstrip("rRbBuUfF")
    if len(body) >= 2 and body[0] in "\"'" and body[-1] == body[0]:
        body = body[1:-1]
    return body


def _classify_python(text: str, rx: "re.Pattern[str]", version: str) -> "dict[int, tuple[str, str]]":
    out: "dict[int, tuple[str, str]]" = {}
    bare = _bare_re(version)
    doc_lines = _docstring_lines(text)
    string_types = {tokenize.STRING}
    for name in ("FSTRING_MIDDLE", "FSTRING_END"):
        kind = getattr(tokenize, name, None)
        if kind is not None:
            string_types.add(kind)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        tokens = []
    for tok in tokens:
        if not rx.search(tok.string):
            continue
        if tok.type == tokenize.COMMENT:
            category, reason = "stamp", "Python 注释里的版本标记"
        elif tok.type in string_types:
            body = _string_body(tok.string)
            if tok.start[0] in doc_lines:
                category, reason = "stamp", "Python docstring 里的版本标记"
            elif bare.fullmatch(body.strip()):
                category, reason = "keep", "Python 裸版本字面量（门控/声明取值）"
            elif _any_path_adjacent(body, rx):
                category, reason = "keep", "Python 字符串里的路径引用（随改名同步）"
            elif any(marker in tok.line for marker in _PROSE_MARKERS):
                category, reason = "stamp", "用户可见 help/错误文字里的版本号（可去）"
            elif len(body) >= _LONG_STRING:
                category, reason = "review", "Python 长字符串字面量：描述性文字"
            else:
                category, reason = "review", "Python 短字符串但非裸版本：需人工判断"
        else:
            continue
        # 只标注**确实含 token 的那几行**（多行 docstring 不能整段计入）
        for offset, token_line in enumerate(tok.string.splitlines()):
            if rx.search(token_line):
                out[tok.start[0] + offset] = (category, reason)
    # 未被 token 覆盖的行（无法 tokenize 的文件、裸正则字面量等）保守按语义保留
    for lineno in _line_hits(text, rx):
        out.setdefault(lineno, ("keep", "未识别的上下文，按语义保留（保守）"))
    return out


def classify_file(path: Path, rx: "re.Pattern[str]", version: str) -> "dict[int, tuple[str, str]]":
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return {}
    suffix = path.suffix.lower()
    if suffix == ".md":
        result = _classify_markdown(text, rx)
    elif suffix in {".yaml", ".yml"}:
        result = _classify_structured(text, rx, comment=True)
    elif suffix == ".json":
        result = _classify_structured(text, rx, comment=False)
    elif suffix == ".py":
        result = _classify_python(text, rx, version)
    elif suffix == ".ps1":
        comments = _ps1_comments(text)
        result = {
            lineno: ("stamp", "PowerShell 注释里的版本标记") if lineno in comments
            else ("keep", "PowerShell 表达式/字符串里的版本声明")
            for lineno in _line_hits(text, rx)
        }
    else:
        result = {lineno: ("keep", "无结构化注释语义：按语义声明保留")
                  for lineno in _line_hits(text, rx)}
    if version in path.relative_to(BASE).as_posix():
        for lineno, (category, reason) in list(result.items()):
            if category == "stamp":
                result[lineno] = ("review", f"{reason}（文件路径本身含版本号，随开版改名）")
    return result


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #


def _files(include_allowed: bool) -> "list[Path]":
    paths: "list[Path]" = []
    for path in cvc._git_visible_files(BASE):
        rel = path.relative_to(BASE).as_posix()
        if any(part in cvc.EXCLUDE_DIRS for part in path.relative_to(BASE).parts):
            continue
        if not cvc._is_text(path):
            continue
        if not include_allowed and cvc._is_allowed_history(rel):
            continue
        if rel == "VERSION":
            continue  # 单一版本来源，本身就是契约事实
        paths.append(path)
    return paths


def collect(version: str, include_allowed: bool) -> "dict":
    rx = _token_re(version)
    rows: "list[dict]" = []
    scanned = 0
    for path in _files(include_allowed):
        scanned += 1
        per_line = classify_file(path, rx, version)
        if not per_line:
            continue
        rel = path.relative_to(BASE).as_posix()
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for lineno in sorted(per_line):
            category, reason = per_line[lineno]
            source = lines[lineno - 1] if lineno <= len(lines) else ""
            rows.append({
                "file": rel,
                "line": lineno,
                "count": len(rx.findall(source)),
                "category": category,
                "reason": reason,
                "text": source.strip()[:160],
                "path_bound": version in rel,
            })
    return {"schema": "tp-spec.version-stamp-report/v1", "version": version,
            "scanned_files": scanned, "rows": rows}


def _summary(report: "dict") -> "dict":
    rows = report["rows"]
    per_file: "dict[str, dict]" = {}
    counts = {name: {"lines": 0, "tokens": 0, "files": 0} for name in ("keep", "stamp", "review")}
    for row in rows:
        slot = per_file.setdefault(row["file"], {"keep": 0, "stamp": 0, "review": 0,
                                                 "path_bound": row["path_bound"]})
        slot[row["category"]] += 1
        counts[row["category"]]["lines"] += 1
        counts[row["category"]]["tokens"] += row["count"]
    for name in counts:
        counts[name]["files"] = len({row["file"] for row in rows if row["category"] == name})

    def bucket(predicate) -> "list[str]":
        return sorted(rel for rel, slot in per_file.items() if predicate(slot))

    return {
        "total_lines": len(rows),
        "total_tokens": sum(row["count"] for row in rows),
        "files_with_token": len(per_file),
        "counts": counts,
        "per_file": per_file,
        "shrinkable_files": bucket(lambda s: s["stamp"] > 0 and s["keep"] == 0 and s["review"] == 0),
        "keep_only_files": bucket(lambda s: s["keep"] > 0 and s["stamp"] == 0 and s["review"] == 0),
        "mixed_files": bucket(lambda s: s["keep"] > 0 and s["stamp"] > 0),
        "review_files": bucket(lambda s: s["review"] > 0),
    }


def main() -> int:
    _ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="版本戳分类报告器（报告工具，不是门禁）")
    parser.add_argument("--verbose", action="store_true", help="逐行展开每个出现位置")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--include-allowed", action="store_true",
                        help="同时统计版本纯度白名单豁免的文件")
    args = parser.parse_args()

    version = (BASE / "VERSION").read_text(encoding="utf-8").strip()
    report = collect(version, args.include_allowed)
    summary = _summary(report)

    if args.json:
        print(json.dumps({"report": report, "summary": summary}, ensure_ascii=False, indent=2))
        return 0

    print("Version Stamp Report — 版本戳分类（报告工具，不阻断）")
    print("=" * 64)
    print(f"活动版本: {version}（读自 VERSION）")
    print("文件集与历史白名单复用 scripts/check_version_consistency.py（报告口径 == 门禁口径）")
    if args.include_allowed:
        print("注: 已包含纯度白名单豁免的文件（--include-allowed）")
    print("=" * 64)
    print(f"\n扫描文件: {report['scanned_files']}    含 token 文件: {summary['files_with_token']}"
          f"    token 出现: {summary['total_tokens']} 次 / {summary['total_lines']} 行")
    label = {"keep": "keep   语义必要（必须跟随版本）",
             "stamp": "stamp  纯展示标签（可去）",
             "review": "review 需人工判断"}
    for name in ("keep", "stamp", "review"):
        slot = summary["counts"][name]
        print(f"  {label[name]:<34} {slot['tokens']:>4} 次 / {slot['lines']:>4} 行"
              f" / {slot['files']:>3} 文件")

    shrink = summary["shrinkable_files"]
    print(f"\n[A] 去掉 stamp 后可完全脱离逐版替换（内容只剩展示标签）: {len(shrink)} 文件")
    for rel in shrink:
        print(f"  - {rel}")

    keep_only = summary["keep_only_files"]
    print(f"\n[B] 只含 keep（必须跟随版本，替换无法避免）: {len(keep_only)} 文件")
    for rel in keep_only:
        print(f"  - {rel}")

    mixed = summary["mixed_files"]
    print(f"\n[D] keep + stamp 混合（语义键必须跟随，但另有可去标签）: {len(mixed)} 文件")
    for rel in mixed:
        slot = summary["per_file"][rel]
        print(f"  - {rel}  (keep {slot['keep']} / stamp {slot['stamp']})")

    review = summary["review_files"]
    print(f"\n[C] 需人工判断: {len(review)} 文件")
    for rel in review:
        slot = summary["per_file"][rel]
        tail = "，路径含版本号" if slot["path_bound"] else ""
        print(f"  - {rel}  (keep {slot['keep']} / stamp {slot['stamp']} / review {slot['review']}{tail})")

    if args.verbose:
        print("\n" + "=" * 64)
        print("逐行明细（按文件）")
        print("=" * 64)
        current = None
        for row in sorted(report["rows"], key=lambda r: (r["file"], r["line"])):
            if row["file"] != current:
                current = row["file"]
                print(f"\n--- {current} ---")
            print(f"  {row['line']:>5}  [{row['category']}] {row['reason']}")
            print(f"         {row['text']}")
    else:
        print("\n（用 --verbose 查看每个出现位置的行号与原文）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
