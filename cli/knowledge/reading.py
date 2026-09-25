"""Registered Knowledge reading: one budget decision, then one truthful receipt."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import sqlite3
import time

from .common import parse_frontmatter
from .documents import document_path, find_document, metadata, public_document, resolve_scope
from . import telemetry

PREVIEW_LINES = 80
PREVIEW_CHARS = 4000
OUTLINE_ITEMS = 20
OUTLINE_CHARS = 1000


def outline(body: str, body_start: int = 1) -> tuple[list[dict], bool]:
    items, used, truncated = [], 0, False
    fence = None
    previous = None
    for number, line in enumerate(body.splitlines(), body_start):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            previous = None
            continue
        if marker and not (marker[1][0] == "`" and "`" in marker[2]):
            fence = marker[1]; previous = None
            continue
        match = re.match(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?)|[ \t]*)$", line)
        heading = None
        if match:
            title = re.sub(r"[ \t]+#+[ \t]*$", "", match[2] or "").strip()
            heading = {"level": len(match[1]), "title": title, "line": number}
        elif previous and re.fullmatch(r" {0,3}(=+|-+)[ \t]*", line):
            heading = {"level": 1 if line.strip()[0] == "=" else 2, "title": previous[1], "line": previous[0]}
        if heading:
            if len(items) >= OUTLINE_ITEMS or used >= OUTLINE_CHARS:
                truncated = True
            else:
                original = heading["title"]
                heading["title"] = original[:OUTLINE_CHARS-used]
                truncated |= heading["title"] != original
                used += len(heading["title"])
                items.append(heading)
            previous = None
        else:
            previous = (number, line.strip()) if line.strip() and not line.startswith(("    ", "\t", ">")) else None
    return items, truncated


def budget(text: str, *, start_line=None, end_line=None, full=False) -> dict:
    """Character (not token) budgets, preserving whole lines and source numbering."""
    if full and (start_line is not None or end_line is not None):
        raise telemetry.KnowledgeError("KNOWLEDGE_READ_MODES_CONFLICT")
    if any(value is not None and (not isinstance(value, int) or value < 1) for value in (start_line, end_line)):
        raise telemetry.KnowledgeError("KNOWLEDGE_INVALID_LINE_RANGE")
    _, body, _, body_start = parse_frontmatter(text)
    raw_lines = text.splitlines(keepends=True)
    total = len(raw_lines)
    headings, headings_truncated = outline(body, body_start)
    explicit = start_line is not None or end_line is not None
    start = start_line if start_line is not None else body_start
    if end_line is not None and end_line < start:
        raise telemetry.KnowledgeError("KNOWLEDGE_INVALID_LINE_RANGE")
    if explicit and start > total and total > 0:
        raise telemetry.KnowledgeError("KNOWLEDGE_LINE_RANGE_OUTSIDE_DOCUMENT")
    mode = "full" if full else "lines" if explicit else "preview"
    content, returned_lines, hint = "", 0, None
    if full:
        end = total
        content = "".join(raw_lines[body_start-1:]); start = body_start
        returned_lines = max(0, total-body_start+1)
    elif explicit:
        end = min(total, end_line if end_line is not None else start+PREVIEW_LINES-1)
        content = "".join(raw_lines[start-1:end])
        returned_lines = max(0, end-start+1)
    else:
        for line in raw_lines[start-1:]:
            if returned_lines >= PREVIEW_LINES or len(content) + len(line) > PREVIEW_CHARS:
                if returned_lines == 0:
                    hint = "FIRST_LINE_EXCEEDS_PREVIEW_BUDGET_USE_EXPLICIT_LINE_RANGE"
                break
            content += line; returned_lines += 1
        end = start+returned_lines-1
    truncated = end < total
    # Frontmatter-only ranges and directory output do not count as body reads.
    body_returned = bool("".join(raw_lines[max(start, body_start)-1:max(end, 0)]).strip()) and bool(content.strip())
    return {"content": content, "read_mode": mode, "outline": headings,
            "outline_truncated": headings_truncated, "truncated": truncated,
            "line_start": start if returned_lines else None, "line_end": end if returned_lines else None,
            "next_start_line": max(start, end+1) if truncated else None,
            "total_lines": total, "body_start_line": body_start, "body_returned": body_returned,
            "budget_hint": hint, "preview_budget": {"lines": PREVIEW_LINES, "characters": PREVIEW_CHARS,
                                                       "outline_items": OUTLINE_ITEMS, "outline_characters": OUTLINE_CHARS}}


def _text(cfg, row):
    path = document_path(cfg, row)
    # Revalidate immediately before reading, including POSIX symlinks/Windows junctions.
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "r", encoding="utf-8-sig", newline=None) as stream:
        current = document_path(cfg, row)
        stat = current.stat()
        opened = os.fstat(stream.fileno())
        if (stat.st_dev, stat.st_ino) != (opened.st_dev, opened.st_ino):
            raise telemetry.KnowledgeError("KNOWLEDGE_DOCUMENT_CHANGED_DURING_READ")
        content = stream.read()
        after = os.fstat(stream.fileno())
        if (after.st_size, after.st_mtime_ns) != (opened.st_size, opened.st_mtime_ns):
            raise telemetry.KnowledgeError("KNOWLEDGE_DOCUMENT_CHANGED_DURING_READ")
    fm, _, _, _ = parse_frontmatter(content)
    if fm and fm.get("project") and str(fm["project"]) != row["project"]:
        raise telemetry.KnowledgeError("KNOWLEDGE_DOCUMENT_SCOPE_CHANGED")
    if row["scope"] == "canonical" and fm and fm.get("id") and str(fm["id"]) != row["canonical_id"]:
        raise telemetry.KnowledgeError("KNOWLEDGE_DOCUMENT_ID_CHANGED")
    return content


def read_document(cfg, document_id: str, *, project=None, scope=None, start_line=None, end_line=None,
                  full=False, record_telemetry=True, request_id=None, task_id=None, actor_role=None,
                  purpose="development", caller="ai_cli") -> dict:
    request = telemetry.request_context(request_id=request_id, task_id=task_id, actor_role=actor_role,
                                        purpose=purpose, caller=caller)
    mode = "full" if full else "lines" if start_line is not None or end_line is not None else "preview"
    request.update(document_key=document_id, scope=scope or "project", project=project or "", projects=[],
                   read_mode=mode, start_line=start_line, end_line=end_line, full=bool(full))
    t0 = time.perf_counter()
    try:
        request.update(resolve_scope(cfg, project=project, scope=scope))
        digest = telemetry.fingerprint("read", request)
        telemetry.check_request(cfg, request, digest, enabled=record_telemetry)
        # Validate options even for metadata-only originals.
        budget("", start_line=start_line, end_line=end_line, full=full)
        row = find_document(cfg, document_id, projects=request["projects"])
        document = public_document(cfg, row)
        if metadata(row).get("metadata_only"):
            result = {**budget(""), "read_mode": "metadata", "body_returned": False,
                      "note": "原件非受支持的知识 Markdown；仅展示注册元数据与已登记转换件，不自动转换或读取外部原件。"}
        else:
            text = _text(cfg, row)
            version = hashlib.sha256(text.encode("utf-8")).hexdigest()
            document.update(indexed_version=document["version"], version=version,
                            version_status="same" if version == row["sha256"] else "changed")
            result = budget(text, start_line=start_line, end_line=end_line, full=full)
        receipt_result = {**document, "line_start": result["line_start"], "line_end": result["line_end"]}
        collected = telemetry.record(cfg, "read", request, digest, results=[receipt_result],
            elapsed_ms=(time.perf_counter()-t0)*1000, document_key=document_id,
            read_mode=result["read_mode"], line_start=result["line_start"], line_end=result["line_end"],
            body_returned=result["body_returned"], enabled=record_telemetry)
        return {"schema": "tp-spec.knowledge-read/v1", "status": "PASS", "document": document,
                "requested_project": request["project"], "requested_projects": request["projects"],
                **result, **collected}
    except (ValueError, sqlite3.Error, OSError, RuntimeError) as exc:
        code = exc.code if isinstance(exc, telemetry.KnowledgeError) else (
            "KNOWLEDGE_DOCUMENT_MISSING" if isinstance(exc, FileNotFoundError) else "KNOWLEDGE_DOCUMENT_UNREADABLE")
        error = telemetry.KnowledgeError(code)
        if code not in {"KNOWLEDGE_REQUEST_CONFLICT", "KNOWLEDGE_RETRY_RESULT_CHANGED"}:
            error.collection = telemetry.record(cfg, "read", request, telemetry.fingerprint("read", request),
                status="failed", error_code=code, elapsed_ms=(time.perf_counter()-t0)*1000,
                document_key=document_id, read_mode=mode, enabled=record_telemetry)
        raise error from None
