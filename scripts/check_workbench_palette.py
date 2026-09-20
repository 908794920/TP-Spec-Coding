#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地工作台配色一致性扫描器。

工作台的设计变量分布在两处，语义上必须保持一致：
- `ui/workbench/src/styles/tokens.css` 的 `:root` CSS 变量（普通 CSS 选择器用）；
- `ui/workbench/src/theme.ts` 的 `palette`（Ant Design 主题 token 用）。

两处都是"唯一事实源"的一半：只要它们漂移，同一个界面元素就会按渲染路径拿到两种颜色。
脚本按显式映射逐项比对，任一不一致即 FAILED；映射之外的主题专属色（只存在于 theme.ts、
没有 CSS 变量对应物）不参与比对，避免把"有意的主题专属值"误判为漂移。

用法：
    python scripts/check_workbench_palette.py
    python scripts/check_workbench_palette.py --verbose
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

BASE = Path(__file__).resolve().parent.parent
TOKENS_CSS = BASE / "ui" / "workbench" / "src" / "styles" / "tokens.css"
THEME_TS = BASE / "ui" / "workbench" / "src" / "theme.ts"

# (CSS 变量名, theme.ts palette 键名)。变量名的 kebab-case 与键名的 camelCase 互为转写，
# 这里仍然显式列出：改名属于需要人确认的改动，不该由脚本猜。
_COLOR_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("--bg", "bg"),
    ("--surface", "surface"),
    ("--muted-surface", "mutedSurface"),
    ("--text", "text"),
    ("--muted", "muted"),
    ("--border", "border"),
    ("--accent", "accent"),
    ("--accent-soft", "accentSoft"),
    ("--warning", "warning"),
    ("--warning-bg", "warningBg"),
    ("--danger", "danger"),
    ("--good", "good"),
)
# 半径不是颜色，但与颜色同样是两处并存的设计变量，所以一并比对（数值相等即可，忽略单位）。
_RADIUS_PAIR = ("--radius", "borderRadius")


def _ensure_utf8_stdio() -> None:
    """Force deterministic Unicode output even under cp1252 Windows stdio."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="strict")
            except (OSError, ValueError):
                pass


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _css_variables(text: str) -> Dict[str, str]:
    """Collect `--name: value` declarations, including several per line."""
    return {name: value.strip() for name, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", text)}


def _palette_entries(text: str) -> Dict[str, str]:
    """Collect the `palette = { ... }` object literal's key/value pairs."""
    start = text.find("const palette")
    if start < 0:
        return {}
    end = text.find("};", start)
    block = text[start:end if end >= 0 else len(text)]
    entries: Dict[str, str] = {}
    for key, value in re.findall(r"(\w+)\s*:\s*'([^']*)'", block):
        entries[key] = value
    for key, value in re.findall(r"(\w+)\s*:\s*(\d+)\b", block):
        entries.setdefault(key, value)
    return entries


def _theme_radius(text: str) -> str:
    """`borderRadius` lives in the theme's token object rather than in `palette`, so it is read on its
    own instead of forcing the source to move it into the palette just to satisfy this check."""
    found = re.search(r"borderRadius\s*:\s*(\d+(?:\.\d+)?)", text)
    return found.group(1) if found else ""


def _normalize_hex(value: str) -> str:
    """Lower-case hex, expanding `#abc` to `#aabbcc` so shorthand is not read as a difference."""
    text = value.strip().lower()
    if re.fullmatch(r"#[0-9a-f]{3}", text):
        return "#" + "".join(char * 2 for char in text[1:])
    return text


def _numbers(value: str) -> str:
    found = re.search(r"-?\d+(?:\.\d+)?", value or "")
    return found.group(0) if found else ""


def main() -> int:
    _ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="校验工作台 tokens.css 与 theme.ts 的配色是否一致")
    parser.add_argument("--verbose", action="store_true", help="打印每一项比对结果")
    args = parser.parse_args()

    for path in (TOKENS_CSS, THEME_TS):
        if not path.is_file():
            print(f"ERROR: 找不到 {path.relative_to(BASE).as_posix()}", file=sys.stderr)
            return 2

    theme_text = _read(THEME_TS)
    variables = _css_variables(_read(TOKENS_CSS))
    palette = _palette_entries(theme_text)
    mismatches: List[str] = []

    for token, key in _COLOR_PAIRS:
        css_value, ts_value = variables.get(token), palette.get(key)
        if css_value is None:
            mismatches.append(f"tokens.css 缺少 {token}")
            continue
        if ts_value is None:
            mismatches.append(f"theme.ts palette 缺少 {key}")
            continue
        left, right = _normalize_hex(css_value), _normalize_hex(ts_value)
        same = left == right
        if not same:
            mismatches.append(f"{token} = {css_value} 与 palette.{key} = {ts_value} 不一致")
        if args.verbose:
            print(f"  {'OK  ' if same else 'FAIL'} {token:<16} {css_value:<10} {key:<14} {ts_value}")

    token, key = _RADIUS_PAIR
    left, right = _numbers(variables.get(token, "")), _theme_radius(theme_text)
    if not left or not right:
        mismatches.append(f"半径对比缺少取值（{token} / {key}）")
    elif left != right:
        mismatches.append(f"{token} = {left} 与 theme.ts {key} = {right} 不一致")
    elif args.verbose:
        print(f"  OK   {token:<16} {left:<10} {key:<14} {right}")

    print(f"比对了 {len(_COLOR_PAIRS)} 个颜色变量与 1 个半径变量：tokens.css 共 {len(variables)} 项，palette 共 {len(palette)} 项")
    # palette 里没有 CSS 对应物的键是主题专属值（例如 Tag.defaultBg），只提示不判失败。
    unmapped = sorted(set(palette) - {key for _, key in _COLOR_PAIRS} - {_RADIUS_PAIR[1]})
    if unmapped:
        print(f"提示：palette 中不参与比对的键（主题专属）：{', '.join(unmapped)}")

    if mismatches:
        print("FAILED: 工作台配色已漂移 ——")
        for item in mismatches:
            print(f"  - {item}")
        return 1
    print("PASSED: tokens.css 与 theme.ts 的配色一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
