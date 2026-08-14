# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path

BASE = Path(__file__).parents[2]

# Legacy names are legal only at the explicit one-shot migration boundary or in
# historical release notes. Everything else is active v5.2.1 surface.
LEGACY_ALLOWED = {
    Path("CHANGELOG.md"),
    Path("cli/namespace_migration.py"),
    Path("docs/MIGRATION_V520_NAMESPACE.md"),
    Path("scripts/tests/test_v520_namespace_migration.py"),
    Path("scripts/tests/test_v520_namespace_purity.py"),
}
TEXT_SUFFIXES = {".py", ".ps1", ".cmd", ".md", ".yaml", ".yml", ".json", ".jsonl", ".txt", ".sql", ""}
LEGACY_PATTERNS = (
    re.compile(r"AI_WORK_"),
    re.compile(r"\.ai-work"),
    re.compile(r"(?<![A-Za-z0-9_-])ai-work(?=[\s./'\"`:]|$)"),
    re.compile(r"ai-work\."),
)


def _tracked_text_files():
    for path in BASE.rglob("*"):
        if not path.is_file() or ".git" in path.parts or ".pytest_cache" in path.parts:
            continue
        rel = path.relative_to(BASE)
        if rel in LEGACY_ALLOWED or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        yield rel, text


def test_no_legacy_namespace_on_active_v520_surface():
    hits = []
    for rel, text in _tracked_text_files():
        for line_no, line in enumerate(text.splitlines(), 1):
            if any(p.search(line) for p in LEGACY_PATTERNS):
                hits.append(f"{rel}:{line_no}: {line.strip()}")
    assert not hits, "legacy namespace remains on active surface:\n" + "\n".join(hits[:80])


def test_canonical_launcher_names_exist_and_legacy_launchers_do_not():
    for name in ("tp-spec", "tp-spec.ps1", "tp-spec.cmd"):
        assert (BASE / "scripts" / name).is_file(), name
    for name in ("Invoke-AiWorkCli.ps1", "ai-work.ps1"):
        assert not (BASE / "scripts" / name).exists(), name
