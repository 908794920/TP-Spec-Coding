# -*- coding: utf-8 -*-
"""架构评审 Subject Digest 单一来源（第三轮 P0-2）。

《Final Hardening 外部源码复审报告》P0-2：第一轮 design digest 只含
task/decisions/test-guide/acceptance，篡改 requirement-knowledge.md 或
requirement-clarifications.md 不会使旧架构 PASS 失效。

本函数为唯一权威实现（review record、transition gate、waiting 共同使用）：
- 默认绑定实际存在的 canonical 需求工件及 architecture.md；其它受审设计由
  review record 的 --design-input 声明，不扫描全部 Markdown。
- 本次完整集合写入 Review detail.design_inputs；后续复核沿同一集合读取，
  修改与删除都改变主体。Review 输出和 Runtime 投影不参与输入。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Union

# Subject digest 输入工件（按固定顺序拼接，保持确定性）
SUBJECT_DIGEST_PARTS = (
    "task.md",
    "requirement.md",
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
        # The Owner writer may insert this optional result field. Canonicalize
        # its absent slot as well, without dropping any acceptance requirement.
        if not re.search(r"(?m)^[ \t]*witness_evidence[ \t]*:", text):
            text = re.sub(r"(?m)^([ \t]*human_witness[ \t]*:[^\n]*)(\n|$)",
                          r"\1\n  witness_evidence: <runtime-result>\2", text, count=1)

        # Preserve the established digest for dedicated Owner-result blocks.
        # A mixed block may contain DB/visual/business obligations: never erase
        # that whole block merely because its first key is Owner metadata.
        def owner_block(match):
            import yaml
            body = match.group(0).split("\n", 1)[1].rsplit("```", 1)[0]
            try:
                parsed = yaml.safe_load(body)
            except yaml.YAMLError:
                return match.group(0)
            if isinstance(parsed, dict) and set(parsed).issubset({"deferred_acceptance", "owner_waivers"}):
                return "```yaml\n<owner-acceptance-result>\n```"
            return match.group(0)
        text = re.sub(r"(?ms)```yaml\s*\n(?:deferred_acceptance|owner_waivers):.*?```", owner_block, text)
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

def _architecture_input_names(task_dir: Path, inputs: Iterable[str], *, review_artifact: str = "architecture-review.md") -> list[str]:
    if isinstance(inputs, (str, bytes)):
        raise ValueError("design inputs must be a collection of Task-relative paths")
    names = set()
    for value in inputs:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("design input must be a nonempty Task-relative path")
        name = value.strip().replace("\\", "/")
        path = Path(name)
        if (path.is_absolute() or ":" in name or ".." in path.parts
                or not (task_dir / path).resolve().is_relative_to(task_dir.resolve())):
            raise ValueError(f"design input is outside selected Task: {name}")
        name = path.as_posix()
        # 这些是评审输出或自管投影；纳入输入会让记录动作使自己的 PASS 失效。
        if (name in {Path(review_artifact.replace("\\", "/")).as_posix(), "architecture-review.md", "codex-review.md",
                     "status.yaml", "events.jsonl", "handoff.json"}
                or name.startswith("generated/") or name == "."):
            raise ValueError(f"design input is a review output or Runtime projection: {name}")
        names.add(name)
    return sorted(names)


def resolve_architecture_design_inputs(task_dir: Union[str, Path], inputs: Iterable[str] | None = None,
                                       *, review_artifact: str = "architecture-review.md") -> list[str]:
    """收集本次实际受审输入；独立设计按显式参数纳入，不扫描全部 Markdown。"""
    base = Path(task_dir)
    defaults = [name for name in (*SUBJECT_DIGEST_PARTS, "architecture.md") if (base / name).is_file()]
    names = _architecture_input_names(base, [*defaults, *(inputs or [])], review_artifact=review_artifact)
    for name in names:
        if not (base / name).is_file():
            raise ValueError(f"review design input is not a readable file: {name}")
    return names


def compute_architecture_subject_digest(task_dir: Union[str, Path], *, design_inputs: Iterable[str] | None = None) -> str:
    """同一摘要绑定排序去重的路径集合与内容身份；已绑定文件删除也改变主体。"""
    base = Path(task_dir)
    names = (resolve_architecture_design_inputs(base) if design_inputs is None
             else _architecture_input_names(base, design_inputs))
    parts = []
    for name in names:
        path = base / name
        content = (_normalize_subject_part(name, _read(path)) if path.is_file() else None)
        parts.append({"path": name, "content_digest": (
            hashlib.sha256(content.encode("utf-8")).hexdigest() if content is not None else None)})
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


# ---- Fourth Hardening（P0-4）：Verification subject digest ----

# Verification subject digest 输入工件（固定顺序）：
# - task.md / requirement.md：完整 canonical 范围/决定（不只绑定摘要）
# - acceptance.md：验收标准（含 AC 行/证据声明）
# - implementation.md：实现说明
# - requirement-test-guide.md：tester-facing 测试指南；Runtime 自管生命周期元数据不参与 subject digest
# 排除 codex-review.md（评审产物，使用独立 artifact_digest 绑定）。
VERIFICATION_SUBJECT_DIGEST_PARTS = (
    "task.md",
    "requirement.md",
    "acceptance.md",
    "implementation.md",
    "requirement-test-guide.md",
)


def compute_verification_subject_digest(task_dir: Union[str, Path], *, scope: str = "full",
                                        acceptance_text: str | None = None) -> str:
    """计算 verification review subject digest（当前受评审技术内容指纹）。

    覆盖 canonical task/requirement、acceptance criteria / implementation.md / requirement-test-guide.md；
    排除可后置的 human test outcome、整目录 evidence 变化与 codex-review.md。
    正式 review evidence 由 REVIEW_COMPLETED.evidence_items 独立绑定。
    """
    if scope not in {"full", "technical"}:
        raise ValueError("unknown verification scope")
    base = Path(task_dir)
    parts: list[str] = []
    for name in VERIFICATION_SUBJECT_DIGEST_PARTS:
        p = base / name
        if p.is_file() or (name == "acceptance.md" and acceptance_text is not None):
            pending = acceptance_text if name == "acceptance.md" else None
            text = _normalize_subject_part(name, pending if pending is not None else _read(p))
            if scope == "technical" and name == "acceptance.md":
                # Only execution evidence/verdict cells may be supplemented after
                # review. Criteria, method, witness policy and visual config remain
                # part of the subject; actual technical evidence is hashed separately.
                import re
                lines = []
                for line in text.split("\n"):
                    if re.match(r"^\s*\|\s*AC-[^|\s]+\s*\|", line):
                        cells = line.split("|")
                        if len(cells) > 9:
                            cells[6] = " <execution-evidence> "
                            cells[8] = " <execution-verdict> "
                            line = "|".join(cells)
                    lines.append(line)
                text = "\n".join(lines)
            parts.append(name + "\n" + text)
    # Review evidence identity is bound explicitly in REVIEW_COMPLETED.evidence_items;
    # hashing the entire evidence/ directory made later human-test evidence additions
    # invalidate an otherwise valid technical PASS.
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()
