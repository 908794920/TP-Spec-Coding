#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查工作台亮暗主题变量与 Ant Design 的单源引用；不运行产品测试。"""
from __future__ import annotations
import argparse
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

def variables(block: str) -> dict[str, str]:
    return dict(re.findall(r'(--[a-z0-9-]+)\s*:\s*([^;]+);', block))

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    css = (BASE / 'ui/workbench/src/styles/tokens.css').read_text(encoding='utf-8-sig')
    theme = (BASE / 'ui/workbench/src/theme.ts').read_text(encoding='utf-8-sig')
    light_match = re.search(r':root\s*\{([^}]+)\}', css)
    dark_match = re.search(r":root\[data-theme=['\"]dark['\"]\]\s*\{([^}]+)\}", css)
    errors = []
    if not light_match or not dark_match:
        print('FAILED: missing light/dark token blocks')
        return 1
    light, dark = variables(light_match.group(1)), variables(dark_match.group(1))
    references = set(re.findall(r"color\(['\"](--[a-z0-9-]+)['\"]\)", theme))
    if not references: errors.append('theme.ts does not consume CSS variables')
    if re.search(r'#[0-9a-fA-F]{3,8}\b', theme): errors.append('theme.ts contains a duplicated color literal')
    for name in sorted(references):
        if name not in light: errors.append(f'{name}: missing base value')
        elif light[name].strip().startswith('#') and name not in dark: errors.append(f'{name}: missing dark value')
        elif args.verbose: print(f'OK {name}: {light[name].strip()} / {dark.get(name, light[name]).strip()}')
    for error in errors: print('FAILED:', error)
    if errors: return 1
    print(f'PASS: {len(references)} CSS token references; both palettes available, no duplicate theme colors')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
