# -*- coding: utf-8 -*-
"""Read-only Evidence View projection for TP-Spec HTML cards.

This module intentionally does not reuse the governance PASS validator as a
presentation decision engine.  It only explains what historical events say,
normalizes paths conservatively, and never mutates Runtime facts.
"""
from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_DRIVE_ABSOLUTE = re.compile(r"^[A-Za-z]:[/\\]")
_SCOPE_LABELS = {
    "task": "任务工件",
    "project": "项目文件",
    "unknown": "未验证",
    "unsafe": "不安全路径",
}


def _detail(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        data = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _split_legacy(value: Any) -> List[str]:
    rows: List[str] = []
    values: Iterable[Any]
    if isinstance(value, list):
        values = value
    elif value is None:
        values = []
    else:
        values = [value]
    for item in values:
        rows.extend(part.strip() for part in str(item).split(";") if part.strip())
    return rows


def _slash(raw: str) -> str:
    return str(raw or "").replace("\\", "/")


def _is_absolute(raw: str) -> bool:
    value = str(raw or "").strip()
    normalized = _slash(value)
    return bool(normalized.startswith("/") or normalized.startswith("//") or _DRIVE_ABSOLUTE.match(value))


def _normalize_relative(raw: str) -> str:
    value = _slash(raw).strip()
    if not value:
        return ""
    normalized = posixpath.normpath(value)
    return "" if normalized == "." else normalized


def _is_lexically_unsafe(raw: str) -> bool:
    if _is_absolute(raw):
        return True
    normalized = _normalize_relative(raw)
    return normalized == ".." or normalized.startswith("../")


def _task_target(task_dir: Optional[Path], normalized: str) -> Tuple[Optional[Path], bool]:
    if task_dir is None or not normalized:
        return None, False
    base = task_dir.resolve(strict=False)
    target = (base / normalized).resolve(strict=False)
    try:
        target.relative_to(base)
    except ValueError:
        return target, False
    return target, True


def _display_name(raw: str, normalized: str) -> str:
    value = normalized or _slash(raw)
    return value.rsplit("/", 1)[-1] or value or "未命名依据"


def _source(event: Dict[str, Any], field: str) -> Dict[str, Any]:
    return {
        "field": field,
        "event_id": event.get("id"),
        "event_type": str(event.get("event_type") or ""),
        "created_at": str(event.get("created_at") or ""),
        "summary": str(event.get("summary") or ""),
    }


def _candidate(
    *,
    raw_path: str,
    declared_anchor: str,
    verification: str,
    task_id: str,
    task_dir: Optional[Path],
    source: Dict[str, Any],
    sha256: str = "",
) -> Dict[str, Any]:
    raw = str(raw_path or "").strip()
    normalized = _normalize_relative(raw)
    anchor = declared_anchor
    current_exists: Optional[bool] = None

    if _is_lexically_unsafe(raw):
        anchor = "unsafe"
        verification = "unsafe"
    elif declared_anchor == "task" and task_dir is not None:
        target, inside = _task_target(task_dir, normalized)
        if not inside:
            anchor = "unsafe"
            verification = "unsafe"
        else:
            current_exists = bool(target and target.is_file())

    if anchor == "task":
        display_path = f".tp-spec/tasks/{task_id}/{normalized}" if normalized else f".tp-spec/tasks/{task_id}"
    else:
        display_path = raw

    return {
        "display_name": _display_name(raw, normalized),
        "raw_path": raw,
        "normalized_path": normalized or raw,
        "anchor": anchor,
        "scope_label": _SCOPE_LABELS.get(anchor, "未验证"),
        "display_path": display_path,
        "copy_path": display_path,
        "verification": verification,
        "current_exists": current_exists,
        "sha256": str(sha256 or ""),
        "sources": [source],
        "occurrence_count": 1,
    }


def build_evidence_view(
    events: Iterable[Dict[str, Any]],
    *,
    task_id: str,
    project_root: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Build a conservative, aggregated Evidence View from task events.

    ``detail.evidence_items`` is the only currently supported source that
    carries an explicit task-relative anchor.  Legacy strings remain visible
    but are kept ``unknown`` unless they are unsafe.  No historical row is
    rewritten or dropped merely because its target file no longer exists.
    """
    root = Path(project_root).resolve(strict=False) if str(project_root or "").strip() else None
    task_dir = root / ".tp-spec" / "tasks" / str(task_id) if root is not None else None
    aggregated: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def add(item: Dict[str, Any]) -> None:
        key = (str(item.get("anchor") or "unknown"), str(item.get("normalized_path") or item.get("raw_path") or ""))
        existing = aggregated.get(key)
        if existing is None:
            aggregated[key] = item
            return
        existing["occurrence_count"] = int(existing.get("occurrence_count") or 0) + int(item.get("occurrence_count") or 0)
        existing.setdefault("sources", []).extend(item.get("sources") or [])
        if not existing.get("sha256") and item.get("sha256"):
            existing["sha256"] = item["sha256"]
        if existing.get("current_exists") is not True and item.get("current_exists") is True:
            existing["current_exists"] = True

    for original in events:
        event = dict(original)
        detail = _detail(event.get("detail_json"))
        structured_norms: set[str] = set()
        items = detail.get("evidence_items")
        if isinstance(items, list):
            for raw_item in items:
                if not isinstance(raw_item, dict):
                    continue
                raw = str(raw_item.get("path") or "").strip()
                if not raw:
                    continue
                normalized = _normalize_relative(raw)
                structured_norms.add(normalized)
                declared_type = str(raw_item.get("type") or "local_file").strip().lower()
                declared_anchor = "task" if declared_type == "local_file" else "unsafe"
                verification = "structured" if declared_type == "local_file" else "unsafe"
                add(_candidate(
                    raw_path=raw,
                    declared_anchor=declared_anchor,
                    verification=verification,
                    task_id=str(task_id),
                    task_dir=task_dir,
                    source=_source(event, "detail.evidence_items"),
                    sha256=str(raw_item.get("sha256") or ""),
                ))

        for field, values in (
            ("detail.evidence", detail.get("evidence")),
            ("task_event.evidence_path", event.get("evidence_path")),
        ):
            for raw in _split_legacy(values):
                # Within the same event, the structured item is authoritative for
                # this exact normalized path; do not duplicate its legacy mirror.
                if _normalize_relative(raw) in structured_norms:
                    continue
                add(_candidate(
                    raw_path=raw,
                    declared_anchor="unknown",
                    verification="legacy_unverified",
                    task_id=str(task_id),
                    task_dir=task_dir,
                    source=_source(event, field),
                ))

    return list(aggregated.values())
