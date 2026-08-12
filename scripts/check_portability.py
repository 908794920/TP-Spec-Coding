# -*- coding: utf-8 -*-
"""Fail when Base runtime/docs accidentally capture machine-local fingerprints.

Compatibility values that must describe legacy data may live in the canonical
Content Systems configuration.  Product code, prompts, templates and ordinary
documentation must remain machine-neutral.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".pytest_cache", "__pycache__"}
ALLOWED_FINGERPRINT_FILES: set[Path] = set()
FORBIDDEN_FINGERPRINTS: tuple[str, ...] = ()
RUNTIME_SURFACES = ("agents", "automation", "cli", "knowledge", "project-entry", "scripts", "templates", "wiki")
WINDOWS_ABS = re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/](?:Users|work|project|updateProject|ProgramData)[\\/]")
POSIX_HOME = re.compile(r"/(?:home|Users)/[^/\s]+/")


def _files():
    for path in BASE.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(BASE)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        yield rel, path


def scan() -> list[str]:
    issues: list[str] = []
    for rel, path in _files():
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (UnicodeDecodeError, OSError):
            continue
        low = text.casefold()
        if rel not in ALLOWED_FINGERPRINT_FILES:
            for token in FORBIDDEN_FINGERPRINTS:
                if token in low:
                    issues.append(f"LOCAL_FINGERPRINT {rel}: {token}")
        if rel.parts and rel.parts[0] in RUNTIME_SURFACES and "tests" not in rel.parts:
            for lineno, line in enumerate(text.splitlines(), 1):
                if WINDOWS_ABS.search(line) or POSIX_HOME.search(line):
                    issues.append(f"MACHINE_ABSOLUTE_PATH {rel}:{lineno}")
    return issues


def main() -> int:
    issues = scan()
    if issues:
        print("PORTABILITY_FAIL")
        for issue in issues:
            print(issue)
        return 1
    print("PORTABILITY_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
