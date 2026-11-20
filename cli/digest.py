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
import re
from pathlib import Path
from typing import Any, Iterable, Union

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

        # Preserve DB/visual/business obligations in mixed Owner-result blocks.
        def owner_block(match):
            import yaml
            body = match.group(0).split("\n", 1)[1].rsplit("```", 1)[0]
            try:
                parsed = yaml.safe_load(body)
            except yaml.YAMLError:
                return match.group(0)
            result_keys = {"deferred_acceptance", "owner_waivers"}
            if isinstance(parsed, dict) and result_keys.intersection(parsed):
                if set(parsed).issubset(result_keys):
                    return "```yaml\n<owner-acceptance-result>\n```"
                normalized = dict(parsed)
                for key in result_keys.intersection(parsed):
                    normalized[key] = "<owner-acceptance-result>"
                return "```yaml\n" + yaml.safe_dump(normalized, allow_unicode=True, sort_keys=False) + "```"
            return match.group(0)
        text = re.sub(r"(?ms)```yaml\s*\n.*?```", owner_block, text)
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


# Architecture subject digest modes. Historical events have no mode field and keep
# the original algorithm bit-for-bit. New records explicitly bind ``criteria_only_v1``.
DIGEST_MODES = ("legacy", "criteria_only_v1")


def normalize_digest_mode(value: Any) -> str:
    """Missing/empty mode is legacy history; an unknown explicit mode is an error."""
    if value in (None, ""):
        return "legacy"
    if not isinstance(value, str) or value not in DIGEST_MODES:
        raise ValueError(f"unsupported architecture digest mode: {value!r}")
    return value


def _acceptance_outcome_rows(text: str, *, all_rows: bool) -> str:
    """Canonicalize AC outcome cells outside fenced examples.

    A line that starts like an AC row inside a fenced code block is an example,
    not an actual table row, so its substantive edits must stay in the subject.
    ``all_rows`` canonicalizes every AC row's execution evidence/verdict cells
    (criteria_only_v1); otherwise only human-witness rows are canonicalized, which
    is the legacy rule.
    """
    lines: list[str] = []
    fence: tuple[str, int] | None = None
    for line in text.split("\n"):
        marker = re.match(r"^[ \t]*(`{3,}|~{3,})", line)
        if fence is None and marker:
            fence = (marker.group(1)[0], len(marker.group(1)))
            lines.append(line)
            continue
        if fence and re.fullmatch(r"[ \t]*" + re.escape(fence[0]) +
                                  "{" + str(fence[1]) + r",}[ \t]*", line):
            fence = None
            lines.append(line)
            continue
        if fence is None and re.match(r"^\s*\|\s*AC-[^|\s]+\s*\|", line):
            cells = line.split("|")
            if len(cells) > 9:
                if all_rows:
                    cells[6] = " <execution-evidence> "
                    cells[8] = " <execution-verdict> "
                elif cells[7].strip().lower() == "human":
                    cells[6] = " <human-result-evidence> "
                    cells[8] = " <human-result-verdict> "
                line = "|".join(cells)
        lines.append(line)
    return "\n".join(lines)


def _criteria_only_acceptance(text: str) -> str:
    """Bind architecture criteria, not Runtime-owned execution/owner outcomes.

    Reuses the legacy Owner-result normalization, then additionally canonicalizes
    the execution evidence/verdict cells of every AC row. IDs, conditions, sources,
    risk, method, witness type, row additions/removals and visual/database
    requirements stay in the subject. Only the Runtime-generated automatic title
    that introduces a pure Owner result block is dropped, and only the EOF
    boundary the Owner writer rewrites is normalized; ordinary body text and
    fenced examples are never rewritten wholesale.
    """
    text = normalize_text_for_digest(text)
    # Same Owner-result rules as legacy; the AC-row canonicalization runs at the
    # end so rows inside fenced examples stay examples and keep their content.
    text = re.sub(r"(?m)^(\s*human_witness\s*:\s*).*$", r"\1<runtime-result>", text)
    text = re.sub(r"(?m)^(\s*witness_evidence\s*:\s*).*$", r"\1<runtime-result>", text)
    # The Owner writer may insert this optional result field. Canonicalize
    # its absent slot as well, without dropping any acceptance requirement.
    if not re.search(r"(?m)^[ \t]*witness_evidence[ \t]*:", text):
        text = re.sub(r"(?m)^([ \t]*human_witness[ \t]*:[^\n]*)(\n|$)",
                      r"\1\n  witness_evidence: <runtime-result>\2", text, count=1)

    # Preserve DB/visual/business obligations in mixed Owner-result blocks.
    def owner_block(match):
        import yaml
        body = match.group(0).split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            parsed = yaml.safe_load(body)
        except yaml.YAMLError:
            return match.group(0)
        result_keys = {"deferred_acceptance", "owner_waivers"}
        if isinstance(parsed, dict) and result_keys.intersection(parsed):
            if set(parsed).issubset(result_keys):
                return "```yaml\n<owner-acceptance-result>\n```"
            normalized = dict(parsed)
            for key in result_keys.intersection(parsed):
                normalized[key] = "<owner-acceptance-result>"
            return "```yaml\n" + yaml.safe_dump(normalized, allow_unicode=True, sort_keys=False) + "```"
        return match.group(0)
    text = re.sub(r"(?ms)```yaml\s*\n.*?```", owner_block, text)

    pure = r"```yaml\n<owner-acceptance-result>\n```"
    # The automatic title and a pure Owner result block are Runtime-owned outcome
    # containers: adding or removing one cannot make architecture criteria stale.
    text = re.sub(r"(?m)^[ \t]*## Owner acceptance decisions[ \t]*\n+" + pure + r"[ \t]*\n*", "", text)
    text = re.sub(pure + r"[ \t]*\n*", "", text)
    text = _acceptance_outcome_rows(text, all_rows=True)
    # The Owner writer rstrips the file and appends its section, so the EOF
    # newline count is a write-boundary artifact, not a criterion. Only this
    # boundary is normalized; internal blank lines stay significant.
    text = text.rstrip(" \t\n")
    return text + "\n" if text else ""


def architecture_digest_parts(task_dir: Union[str, Path], design_inputs: Iterable[str] | None = None,
                              *, digest_mode: Any = None) -> list[dict]:
    """Sorted input paths with per-file content digests under the selected mode.

    ``content_digest`` stays None for a deleted bound input, so removal is part of
    the subject. The same list derives both the aggregate and the per-file table.
    """
    base = Path(task_dir)
    mode = normalize_digest_mode(digest_mode)
    names = (resolve_architecture_design_inputs(base) if design_inputs is None
             else _architecture_input_names(base, design_inputs))
    parts = []
    for name in names:
        path = base / name
        if path.is_file():
            text = _read(path)
            content = (_criteria_only_acceptance(text)
                       if mode == "criteria_only_v1" and name == "acceptance.md"
                       else _normalize_subject_part(name, text))
            content_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        else:
            content_digest = None
        parts.append({"path": name, "content_digest": content_digest})
    return parts


def aggregate_architecture_parts(parts: Iterable[dict]) -> str:
    return hashlib.sha256(json.dumps(list(parts), ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def compute_architecture_subject_digest(task_dir: Union[str, Path], *, design_inputs: Iterable[str] | None = None,
                                        digest_mode: Any = None) -> str:
    """同一摘要绑定排序去重的路径集合与内容身份；已绑定文件删除也改变主体。"""
    return aggregate_architecture_parts(
        architecture_digest_parts(task_dir, design_inputs, digest_mode=digest_mode))


def compute_architecture_subject_digest_for_detail(task_dir: Union[str, Path], detail: dict | None) -> str:
    """Replay an architecture record under its own recorded mode.

    Historical events (missing/empty ``design_digest_mode``) keep the original
    algorithm; a new record binds ``criteria_only_v1``. An unsupported non-empty
    mode raises instead of silently falling back.
    """
    detail = detail or {}
    return compute_architecture_subject_digest(
        task_dir, design_inputs=detail.get("design_inputs"),
        digest_mode=detail.get("design_digest_mode"))


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


VERIFICATION_SUBJECT_MODE = "criteria_only_v1"


def compute_verification_subject_digest(task_dir: Union[str, Path], *, scope: str = "full",
                                        acceptance_text: str | None = None,
                                        subject_mode: str = "legacy") -> str:
    """计算 verification review subject digest（当前受评审技术内容指纹）。

    覆盖 canonical task/requirement、acceptance criteria / implementation.md / requirement-test-guide.md；
    排除可后置的 human test outcome、整目录 evidence 变化与 codex-review.md。
    正式 review evidence 由 REVIEW_COMPLETED.evidence_items 独立绑定。
    """
    if scope not in {"full", "technical"}:
        raise ValueError("unknown verification scope")
    if subject_mode not in {"legacy", VERIFICATION_SUBJECT_MODE}:
        raise ValueError("unknown verification subject mode")
    base = Path(task_dir)
    parts: list[str] = []
    for name in VERIFICATION_SUBJECT_DIGEST_PARTS:
        p = base / name
        if p.is_file() or (name == "acceptance.md" and acceptance_text is not None):
            pending = acceptance_text if name == "acceptance.md" else None
            raw = pending if pending is not None else _read(p)
            text = (_criteria_only_acceptance(raw) if name == "acceptance.md" and
                    subject_mode == VERIFICATION_SUBJECT_MODE else _normalize_subject_part(name, raw))
            if subject_mode == "legacy" and scope == "technical" and name == "acceptance.md":
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
