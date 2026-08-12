# -*- coding: utf-8 -*-
"""Read-only risk-floor detection from formal Task artifacts.

This module never lowers a declared risk and never writes Runtime state.  It is
used as a deterministic safety floor so security/access-control signals cannot
be hidden by an optimistic AI classification.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import config_loader

_LEVELS = ("L0", "L1", "L2", "L3")
_FORMAL_SUFFIXES = {".md", ".yaml", ".yml"}
_MAX_SCAN_CHARS = 512_000


def _rank(level: Optional[str]) -> int:
    try:
        return _LEVELS.index(str(level or "").upper())
    except ValueError:
        return -1


def _max_level(left: Optional[str], right: Optional[str]) -> Optional[str]:
    rank = max(_rank(left), _rank(right))
    return _LEVELS[rank] if rank >= 0 else None


def _rules(base_root: Optional["str | Path"] = None) -> Dict[str, Any]:
    data = config_loader.load_config(
        "governance/risk-rule.yaml",
        schema_name="risk-rule",
        base_root=base_root,
        strict_unknown_fields=True,
        use_cache=False,
    )
    automated = data.get("automated_validation") or {}
    return automated if isinstance(automated, dict) else {}


def _match_is_negated(candidate: str, match: re.Match[str], negative_pattern: str) -> bool:
    """Return True when a governed negation locally qualifies this signal hit.

    Negation is evaluated per signal match rather than per sentence.  This keeps
    a clause such as ``无 DDL，但修改安全策略`` from suppressing the real
    security signal while still ignoring ``本任务无 DDL`` and compact forms
    such as ``无授权模型/DDL 变更``.
    """
    if not negative_pattern:
        return False
    window_start = max(0, match.start() - 24)
    window_end = min(len(candidate), max(match.end(), match.start() + 1))
    window = candidate[window_start:window_end]
    for negated in reversed(list(re.finditer(negative_pattern, window))):
        neg_start = window_start + negated.start()
        neg_end = window_start + negated.end()
        overlaps = neg_start < match.end() and neg_end > match.start()
        gap = candidate[neg_end:match.start()] if neg_end <= match.start() else ""
        nearby = neg_end <= match.start() and len(gap) <= 12
        if not (overlaps or nearby):
            continue
        if gap and re.search(r"(?:但|但是|不过|然而|反而)", gap):
            continue
        return True
    return False


def scan_texts(texts: Iterable[str], *, base_root: Optional["str | Path"] = None) -> Dict[str, Any]:
    rules = _rules(base_root)
    negative = str(rules.get("negative_pattern") or "")
    groups = (
        ("L3", rules.get("minimum_L3_signals") or []),
        ("L2", rules.get("minimum_L2_signals") or []),
    )
    floor: Optional[str] = None
    hits: List[str] = []
    seen: set[str] = set()
    for text in texts:
        # ``、`` is a semantic list/clause separator in Task prose.  Splitting
        # it prevents a verb in one negated item (e.g. 接口契约变更) from
        # leaking through ``.*`` into another item (e.g. 无定时任务).
        for segment in re.split(r"[，,。；;、\n]", str(text or "")):
            candidate = segment.strip()
            if not candidate:
                continue
            for level, signals in groups:
                for signal in signals:
                    if not isinstance(signal, dict):
                        continue
                    sid = str(signal.get("id") or "").strip()
                    pattern = str(signal.get("pattern") or "")
                    if not sid or not pattern:
                        continue
                    matched = False
                    for signal_match in re.finditer(pattern, candidate):
                        if not _match_is_negated(candidate, signal_match, negative):
                            matched = True
                            break
                    if matched:
                        floor = _max_level(floor, level)
                        if sid not in seen:
                            hits.append(sid)
                            seen.add(sid)
    return {"floor": floor, "signals": hits}


def scan_task_artifacts(task_dir: "str | Path", *, base_root: Optional["str | Path"] = None) -> Dict[str, Any]:
    root = Path(task_dir)
    if not root.is_dir():
        return {"floor": None, "signals": []}
    texts: List[str] = []
    total = 0
    for path in sorted(root.iterdir()):
        if not path.is_file() or path.suffix.lower() not in _FORMAL_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        remaining = _MAX_SCAN_CHARS - total
        if remaining <= 0:
            break
        text = text[:remaining]
        texts.append(text)
        total += len(text)
    return scan_texts(texts, base_root=base_root)
