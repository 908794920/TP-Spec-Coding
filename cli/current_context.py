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


def _region(text: str) -> tuple[str, int] | None:
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
    region_lines = lines[markers[0][0] + 1:markers[1][0]]
    leading_empty = 0
    for line in region_lines:
        if line.strip():
            break
        leading_empty += 1
    content = "\n".join(region_lines).strip()
    # Empty scaffold headings/comments carry no decision and must not compete
    # with an adopted Requirement or require a new questionnaire.
    substantive = re.sub(r"<!--.*?-->", "", content, flags=re.S)
    substantive = re.sub(r"(?m)^\s*#{1,6}\s+.*$", "", substantive).strip()
    return (content, markers[0][0] + 2 + leading_empty) if substantive else None


def read_current(task_dir: Path | None, *, task_id: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "ABSENT", "source": None, "content": "", "source_digest": "",
        "authorization_granted": False, "sources": [], "issues": [],
    }
    if task_dir is None:
        return result
    root = Path(task_dir)
    candidates: list[tuple[str, str, str, int]] = []
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
            region = _region(text)
            if not region:
                continue
            content, source_line = region
            metadata = frontmatter.parse(text) or {}
            if task_id and metadata.get("task_id") not in (None, "", task_id):
                raise ValueError("canonical source belongs to another Task")
            if len(content) > MAX_CONTEXT_CHARS:
                result["issues"].append({"path": name, "reason": "current region exceeds context limit; do not truncate", "status": "TOO_LARGE"})
                continue
            candidates.append((name, content, digest, source_line))
        except (OSError, UnicodeError, ValueError) as exc:
            # Return an explicit diagnostic, not an old/partial alternative.
            result["issues"].append({"path": name, "reason": str(exc), "status": "INVALID"})
    if result["issues"]:
        result["status"] = ("INVALID" if any(i["status"] == "INVALID" for i in result["issues"]) else "TOO_LARGE")
    elif len(candidates) > 1:
        result["status"] = "CONFLICT"
        result["issues"] = [{"path": item[0], "reason": "multiple nonempty current regions"} for item in candidates]
    elif candidates:
        name, content, digest, source_line = candidates[0]
        result.update(status="AVAILABLE", source=name, content=content, source_digest=digest, source_line=source_line)
    if result["status"] in UNUSABLE:
        result["recovery"] = RECOVERY
    return result


def workflow_consistency_diagnostics(task_dir: Path, context: dict, *, state: str,
                                     state_source: str) -> list[dict]:
    """只提示明确的当前任务状态冲突；不从历史、部署边界或普通未完成措辞裁决。"""
    if state == "UNKNOWN" or context["status"] in UNUSABLE:
        return []
    sources = []
    if context["status"] == "AVAILABLE":
        sources.append((context["source"], context["content"], context.get("source_line", 1), True))
    else:
        for name in ("task.md", "implementation.md"):
            path = task_dir / name
            try:
                if path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_SOURCE_BYTES:
                    sources.append((name, path.read_text(encoding="utf-8-sig"), 1, False))
            except (OSError, UnicodeError):
                continue  # 来源读取异常由已有工件诊断负责，不能猜文字内容。
    issues = []
    for name, text, first_line, in_current in sources:
        fence_char, fence_len = "", 0
        in_comment = False
        for offset, line in enumerate(text.splitlines()):
            fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
            if fence_char:
                if fence and fence.group(1)[0] == fence_char and len(fence.group(1)) >= fence_len and not fence.group(2).strip():
                    fence_char, fence_len = "", 0
                continue
            if in_comment or "<!--" in line:
                in_comment = "-->" not in line
                continue
            if fence:
                fence_char, fence_len = fence.group(1)[0], len(fence.group(1))
                continue
            if line.startswith(("    ", "\t")):
                continue
            statement = re.sub(r"^\s*[-*]\s+", "", line).strip()
            prefix = r"(?:当前(?:任务|流程|workflow)?状态|当前任务状态)"
            if in_current:
                prefix = r"(?:" + prefix + r"|任务状态|workflow状态)"
            match = re.fullmatch(prefix + r"\s*[:：]\s*`?(NEW|ACTIVE|BLOCKED|COMPLETED|CANCELLED|PENDING)`?[。.!！]?", statement, re.I)
            declared = match.group(1).upper() if match else None
            if in_current and re.fullmatch(r"当前任务(?:尚未|未)完成[。.!！]?", statement):
                declared = "UNFINISHED"
            if not declared or declared == state:
                continue
            if declared in {"UNFINISHED", "PENDING"} and state not in {"COMPLETED", "CANCELLED"}:
                continue
            issues.append({"code": "CURRENT_WORKFLOW_CONTRADICTION", "path": name,
                           "line": first_line + offset, "statement": statement,
                           "declared_state": declared, "formal_state": state, "state_source": state_source,
                           "message": "当前状态文字与正式记录不一致；仅提示定位，保留历史与实际验收边界。"})
    return issues


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
