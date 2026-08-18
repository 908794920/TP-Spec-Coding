# -*- coding: utf-8 -*-
"""Deterministic code-comment locator for review findings.

Adapted from Alibaba OpenCodeReview's Apache-2.0 diff resolver design
(`internal/diff/resolver.go`): prefer exact normalized hunk matching, fall back
to full new-file content, and relocate across files only on a unique match.
No LLM is used and ambiguity is never guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ReviewLocation:
    path: str
    start_line: int
    end_line: int
    source: str


def _norm(line: str) -> str:
    text = str(line).strip()
    if text.startswith(("+", "-")):
        text = text[1:].strip()
    return text


def _target_lines(code: str) -> list[str]:
    return [n for n in (_norm(x) for x in str(code or "").splitlines()) if n]


def _match(lines: list[tuple[int, str]], target: list[str]) -> tuple[int, int] | None:
    if not target or len(lines) < len(target):
        return None
    for i in range(len(lines) - len(target) + 1):
        if [x[1] for x in lines[i:i + len(target)]] == target:
            return lines[i][0], lines[i + len(target) - 1][0]
    return None


def _hunk_sides(diff_text: str) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    new_side: list[tuple[int, str]] = []
    old_side: list[tuple[int, str]] = []
    old_line = new_line = None
    header = re.compile(r"^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@")
    for raw in str(diff_text or "").splitlines():
        m = header.match(raw)
        if m:
            old_line, new_line = int(m.group(1)), int(m.group(2))
            continue
        if old_line is None or new_line is None or raw.startswith(("+++", "---")):
            continue
        if raw.startswith("+"):
            value = _norm(raw)
            if value:
                new_side.append((new_line, value))
            new_line += 1
        elif raw.startswith("-"):
            value = _norm(raw)
            if value:
                old_side.append((old_line, value))
            old_line += 1
        else:
            content = raw[1:] if raw.startswith(" ") else raw
            value = _norm(content)
            if value:
                new_side.append((new_line, value))
                old_side.append((old_line, value))
            old_line += 1; new_line += 1
    return new_side, old_side


def _locate_in_diff(code: str, row: dict[str, Any], *, source_label: str | None = None) -> ReviewLocation | None:
    target = _target_lines(code)
    if not target:
        return None
    path = str(row.get("new_path") or row.get("old_path") or "")
    new_side, old_side = _hunk_sides(str(row.get("diff") or ""))
    hit = _match(new_side, target) or _match(old_side, target)
    if hit:
        return ReviewLocation(path, hit[0], hit[1], source_label or "hunk")
    content = str(row.get("new_file_content") or "")
    indexed = [(i + 1, n) for i, raw in enumerate(content.splitlines()) if (n := _norm(raw))]
    hit = _match(indexed, target)
    if hit:
        return ReviewLocation(path, hit[0], hit[1], source_label or "file")
    return None


def locate_existing_code(existing_code: str, diffs: Iterable[dict[str, Any]], *, preferred_path: str = "") -> ReviewLocation | None:
    rows = list(diffs or [])
    preferred = str(preferred_path or "")
    if preferred:
        for row in rows:
            if preferred in {str(row.get("new_path") or ""), str(row.get("old_path") or "")}:
                hit = _locate_in_diff(existing_code, row)
                if hit:
                    return hit
                break
    hits: list[ReviewLocation] = []
    for row in rows:
        if preferred and preferred in {str(row.get("new_path") or ""), str(row.get("old_path") or "")}:
            continue
        hit = _locate_in_diff(existing_code, row, source_label="cross-file")
        if hit:
            hits.append(hit)
            if len(hits) > 1:
                return None
    return hits[0] if len(hits) == 1 else None
