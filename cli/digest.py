# -*- coding: utf-8 -*-
"""V5.2.5 架构评审 Subject Digest 单一来源（第三轮 P0-2）。

《V5.2.5 Final Hardening 外部源码复审报告》P0-2：第一轮 design digest 只含
task/decisions/test-guide/acceptance，篡改 requirement-knowledge.md 或
requirement-clarifications.md 不会使旧架构 PASS 失效。

本函数为唯一权威实现（review record、transition gate、测试共同使用）：
- 输入工件：task.md / requirement-knowledge.md / requirement-clarifications.md /
  requirement-decisions.md / requirement-test-guide.md / acceptance.md
- 排除：implementation.md（开发阶段工件，架构评审发生在 DEVELOPING 之前）、
  architecture-review.md（评审产物，PASS 写入后 front matter 更新不应使刚记录
  的 PASS 失效）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Union

# Subject digest 输入工件（按固定顺序拼接，保持确定性）
SUBJECT_DIGEST_PARTS = (
    "task.md",
    "requirement-knowledge.md",
    "requirement-clarifications.md",
    "requirement-decisions.md",
    "requirement-test-guide.md",
    "acceptance.md",
)


def _read(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()



def normalize_text_for_digest(text: str) -> str:
    """Normalize transport-only text differences for semantic artifact binding.

    UTF-8 BOM and CRLF/CR line endings must not invalidate a governance PASS.
    Content, whitespace inside lines and trailing newlines remain significant.
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def compute_text_artifact_digest(text: str) -> str:
    """SHA-256 of normalized UTF-8 text for review artifact identity."""
    return hashlib.sha256(normalize_text_for_digest(text).encode("utf-8")).hexdigest()


def compute_text_artifact_file_digest(path: Union[str, Path]) -> str:
    """Read a UTF-8 text artifact and compute the normalized artifact digest."""
    p = Path(path)
    try:
        raw = p.read_bytes()
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return ""
    return compute_text_artifact_digest(text)


def _normalize_subject_part(name: str, text: str) -> str:
    """Normalize transport/runtime-owned bookkeeping before subject binding.

    Review identity protects business/technical subject matter, not transport EOL/BOM or
    fields that the Runtime itself mutates during later transitions.  In particular,
    requirement-test-guide.md lifecycle/current_owner/section_owners must never make a
    valid PASS stale merely because the Runtime advanced state.
    """
    text = normalize_text_for_digest(text)
    if name == "acceptance.md":
        # Verification PASS binds acceptance *criteria*, not mutable execution outcomes.
        # Human test results/owner disposition may be recorded after technical PASS
        # without making that technical review stale. Criteria/method/witness changes
        # remain protected.
        import re
        lines = []
        for line in text.split("\n"):
            if re.match(r"^\s*\|\s*AC-[^|\s]+\s*\|", line):
                cells = line.split("|")
                if len(cells) > 9:
                    if cells[7].strip().lower() == "human":
                        cells[6] = " <human-result-evidence> "
                        cells[8] = " <human-result-verdict> "
                    line = "|".join(cells)
            lines.append(line)
        text = "\n".join(lines)
        text = re.sub(r"(?m)^(\s*human_witness\s*:\s*).*$", r"\1<runtime-result>", text)
        text = re.sub(r"(?m)^(\s*witness_evidence\s*:\s*).*$", r"\1<runtime-result>", text)
        # Owner defer/waive records are audited Runtime outcomes, not review subject.
        text = re.sub(r"(?ms)```yaml\s*\n(?:deferred_acceptance|owner_waivers):.*?```", "```yaml\n<owner-acceptance-result>\n```", text)
        return text
    if name != "requirement-test-guide.md":
        return text
    from . import frontmatter
    parts = frontmatter.split(text)
    if parts is None:
        return text
    front, rest, _ = parts
    filtered: list[str] = []
    skip_block = False
    runtime_keys = {"current_owner", "lifecycle", "section_owners"}
    for line in front.split("\n"):
        if line and not line[0].isspace():
            key = line.split(":", 1)[0].strip() if ":" in line else ""
            skip_block = key in runtime_keys
            if skip_block:
                continue
        elif skip_block:
            continue
        filtered.append(line)
    return "---\n" + "\n".join(filtered) + "\n---\n" + rest

def compute_architecture_subject_digest(task_dir: Union[str, Path]) -> str:
    """计算架构评审 subject digest（当前设计内容指纹）。

    仅包含``SUBJECT_DIGEST_PARTS``中实际存在的文件；任一设计工件缺失/内容变化
    都会改变 digest（fail-closed 语义由调用方决定）。
    """
    base = Path(task_dir)
    parts: list[str] = []
    for name in SUBJECT_DIGEST_PARTS:
        p = base / name
        if p.is_file():
            parts.append(name + "\n" + _normalize_subject_part(name, _read(p)))
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()


# ---- Fourth Hardening（P0-4）：Verification subject digest ----

# Verification subject digest 输入工件（固定顺序）：
# - acceptance.md：验收标准（含 AC 行/证据声明）
# - implementation.md：实现说明
# - requirement-test-guide.md：tester-facing 测试指南；Runtime 自管生命周期元数据不参与 subject digest
# 排除 codex-review.md（评审产物，使用独立 artifact_digest 绑定）。
VERIFICATION_SUBJECT_DIGEST_PARTS = (
    "acceptance.md",
    "implementation.md",
    "requirement-test-guide.md",
)


def compute_verification_subject_digest(task_dir: Union[str, Path]) -> str:
    """计算 verification review subject digest（当前受评审技术内容指纹）。

    覆盖 acceptance criteria / implementation.md / requirement-test-guide.md；
    排除可后置的 human test outcome、整目录 evidence 变化与 codex-review.md。
    正式 review evidence 由 REVIEW_COMPLETED.evidence_items 独立绑定。
    """
    base = Path(task_dir)
    parts: list[str] = []
    for name in VERIFICATION_SUBJECT_DIGEST_PARTS:
        p = base / name
        if p.is_file():
            parts.append(name + "\n" + _normalize_subject_part(name, _read(p)))
    # Review evidence identity is bound explicitly in REVIEW_COMPLETED.evidence_items;
    # hashing the entire evidence/ directory made later human-test evidence additions
    # invalidate an otherwise valid technical PASS.
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()
