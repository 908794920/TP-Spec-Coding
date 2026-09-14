# -*- coding: utf-8 -*-
"""A bounded, read-only slice of the existing canonical business document.

The slice is declared prose, not an authorization, a verification result or a
second ledger. No history inference, source-link following or persistent cache.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from . import frontmatter

START = "<!-- tp-spec:current:start -->"
END = "<!-- tp-spec:current:end -->"
SOURCE_NAMES = ("task.md", "requirement.md")
MAX_SOURCE_BYTES = 512_000
MAX_CONTEXT_CHARS = 8_192
UNUSABLE = frozenset({"CONFLICT", "INVALID", "TOO_LARGE"})
RECOVERY = (
    "定向核对列出的 canonical 工件及来源，只保留一处有效区；保留被替代历史。"
    "先由执行者调查，只有真实范围/授权取舍才请求用户；不按修改时间选择、不截断限制。"
)


def _region(text: str) -> str | None:
    """Find one marker pair outside fenced examples; reject ambiguous markup."""
    lines = text.splitlines()
    markers: list[tuple[int, str]] = []
    fence_char, fence_len = "", 0
    for index, line in enumerate(lines):
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence_char:
            if (fence and fence.group(1)[0] == fence_char
                    and len(fence.group(1)) >= fence_len and not fence.group(2).strip()):
                fence_char, fence_len = "", 0
            continue
        if fence:
            fence_char, fence_len = fence.group(1)[0], len(fence.group(1))
            continue
        value = line.strip()
        # Indented examples are not an active marker either.
        if line.startswith(("    ", "\t")):
            continue
        if value.startswith("<!-- tp-spec:current:"):
            if value not in {START, END}:
                raise ValueError("invalid current-region marker")
            markers.append((index, value))
    if not markers:
        return None
    if len(markers) != 2 or [m[1] for m in markers] != [START, END]:
        raise ValueError("expected exactly one ordered current-region marker pair")
    content = "\n".join(lines[markers[0][0] + 1:markers[1][0]]).strip()
    # Empty scaffold headings/comments carry no decision and must not compete
    # with an adopted Requirement or require a new questionnaire.
    substantive = re.sub(r"<!--.*?-->", "", content, flags=re.S)
    substantive = re.sub(r"(?m)^\s*#{1,6}\s+.*$", "", substantive).strip()
    return content if substantive else ""


def read_current(task_dir: Path | None, *, task_id: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "ABSENT", "source": None, "content": "", "source_digest": "",
        "authorization_granted": False, "sources": [], "issues": [],
    }
    if task_dir is None:
        return result
    root = Path(task_dir)
    candidates: list[tuple[str, str, str]] = []
    for name in SOURCE_NAMES:
        path = root / name
        try:
            if root.is_symlink() or path.is_symlink():
                raise ValueError("linked canonical source is not followed")
            if not path.exists():
                continue
            with path.open("rb") as handle:
                raw = handle.read(MAX_SOURCE_BYTES + 1)
            if len(raw) > MAX_SOURCE_BYTES:
                result["issues"].append({"path": name, "reason": "source exceeds bounded read", "status": "TOO_LARGE"})
                continue
            text = raw.decode("utf-8-sig")
            # Match the generated-view digest's BOM removal / EOL preservation.
            digest = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
            result["sources"].append({"path": name, "digest": digest})
            content = _region(text)
            if not content:
                continue
            metadata = frontmatter.parse(text) or {}
            if task_id and metadata.get("task_id") not in (None, "", task_id):
                raise ValueError("canonical source belongs to another Task")
            if len(content) > MAX_CONTEXT_CHARS:
                result["issues"].append({"path": name, "reason": "current region exceeds context limit; do not truncate", "status": "TOO_LARGE"})
                continue
            candidates.append((name, content, digest))
        except (OSError, UnicodeError, ValueError) as exc:
            # Return an explicit diagnostic, not an old/partial alternative.
            result["issues"].append({"path": name, "reason": str(exc), "status": "INVALID"})
    if result["issues"]:
        result["status"] = ("INVALID" if any(i["status"] == "INVALID" for i in result["issues"]) else "TOO_LARGE")
    elif len(candidates) > 1:
        result["status"] = "CONFLICT"
        result["issues"] = [{"path": name, "reason": "multiple nonempty current regions"} for name, _, _ in candidates]
    elif candidates:
        name, content, digest = candidates[0]
        result.update(status="AVAILABLE", source=name, content=content, source_digest=digest)
    if result["status"] in UNUSABLE:
        result["recovery"] = RECOVERY
    return result


def render_current(context: dict[str, Any]) -> str:
    """Render the same slice, never another model-written summary."""
    status = context["status"]
    if status == "ABSENT":
        return ""
    if status in UNUSABLE:
        paths = ", ".join(item["path"] for item in context["issues"])
        return f"\n## 当前有效范围与决策\n\n待核对（{status}）：{paths}。{RECOVERY}\n"
    return (
        f"\n## 当前有效范围与决策（来源：{context['source']}）\n\n"
        "> 以下为 canonical 业务声明；来源尚需按需核实，不授予操作权限或验收 PASS。\n\n"
        + context["content"]
        + "\n\n历史/替代依据按需读取来源工件的历史区或已有 requirement-decisions.md；不从旧记录恢复已替代决定。\n"
    )
