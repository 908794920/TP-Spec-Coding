# -*- coding: utf-8 -*-
"""V5.2.4 C1 anchor_check 确定性锚点校验（B-17 C1-P1~P9）。

设计依据：历史设计记录 C1-review-preflight-design §4
证据锚点：升级计划 §3.1 L102-109；评审表 9.4 第 1 行（L333）。

纯确定性四项校验（无 LLM、无网络、无随机）：
① 引用文本/hunk 片段存在性（逐字节）；
② 行号范围（1 ≤ n ≤ 文件总行数，0/负数/越界均失败）；
③ 证据哈希一致性（接受 64hex 或 sha256: 前缀，同 B-16 `_normalize_sha256` 形式）；
④ hunk 滑动窗口确定性偏移（固定窗口/固定步长/确定性首匹配回溯）。

失败不删除 finding，标 anchor_status: unverified 交 tp-code-reviewer；
V5.2.4 不包含 OCR 式 LLM 评论过滤，所有预检命中保留。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .review_locator import locate_existing_code

# --- 版本与错误码枚举 ---
_ANCHOR_CHECK_VERSION = "1.0.0"

ANCHOR_TEXT_NOT_FOUND = "ANCHOR_TEXT_NOT_FOUND"
ANCHOR_LINE_RANGE_INVALID = "ANCHOR_LINE_RANGE_INVALID"
ANCHOR_HASH_MISMATCH = "ANCHOR_HASH_MISMATCH"
ANCHOR_OFFSET_UNDETERMINED = "ANCHOR_OFFSET_UNDETERMINED"

_ANCHOR_STATUS_VERIFIED = "verified"
_ANCHOR_STATUS_UNVERIFIED = "unverified"

# 滑动窗口固定参数（确定性默认，纳入 anchor_check 版本语义；不得随机/环境依赖）
_OFFSET_WINDOW_SIZE = 3
_OFFSET_STEP = 1

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _normalize_sha256(value: str | None) -> str | None:
    """接受 64 位十六进制或 sha256: 前缀形式，统一为 sha256:<hex>；非法返回 None。"""
    if not value:
        return None
    candidate = value.strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", candidate):
        candidate = f"sha256:{candidate}"
    if not _SHA256_RE.fullmatch(candidate):
        return None
    return candidate


def check_text_exists(file_content: str, text: str | None) -> bool:
    """① 引用文本/hunk 片段逐字节存在性。"""
    if text is None or not text.strip():
        return False
    return text in file_content


def check_line_range(file_content: str, line: int | None) -> bool:
    """② 行号范围：1 ≤ line ≤ 文件总行数；None/0/负数/越界均失败。"""
    if line is None:
        return False
    total = len(file_content.splitlines())
    return 1 <= line <= total


def check_hash_matches(file_content: str, evidence_hash: str | None) -> bool:
    """③ 证据哈希一致性：normalize 后与当前内容 SHA256 比对。"""
    expected = _normalize_sha256(evidence_hash)
    if expected is None:
        return False
    actual = hashlib.sha256(file_content.encode("utf-8")).hexdigest()
    return expected == f"sha256:{actual}"


def compute_offset_correction(file_content: str, hunk_context: list[str] | None) -> tuple[bool, int | None]:
    """④ hunk 滑动窗口确定性偏移。

    将 hunk 上下文行（去 +/- 前缀与行首空白）在目标文件行序列中滑动匹配，
    窗口大小与步长为固定常量（首匹配即回溯，无随机/时间/环境依赖）。
    返回 (找到?, 修正行号)；找不到返回 (False, None)。
    """
    if not hunk_context:
        return False, None
    lines = file_content.splitlines()
    # 目标行与上下文行统一 strip 后比较（行号仍对应原始行序）
    stripped_lines = [ln.strip() for ln in lines]
    ctx = [ln.lstrip("+-").strip() for ln in hunk_context if ln.strip()]
    ctx = [ln for ln in ctx if ln]
    if not ctx:
        return False, None
    window = min(len(ctx), _OFFSET_WINDOW_SIZE)
    if window == 0:
        return False, None
    ctx_head = ctx[:window]
    for i in range(0, len(stripped_lines) - window + 1, _OFFSET_STEP):
        if stripped_lines[i:i + window] == ctx_head:
            # 命中行号（1-based）即 hunk 实际位置
            return True, i + 1
    return False, None


def run_anchor_check(finding: dict[str, Any], file_content: str) -> dict[str, Any]:
    """对单个 finding 执行四项确定性校验。

    finding 结构：{id, file, text, line, evidence_hash, hunk_context}
    返回：{finding_id, file, anchor_status, checks{...}, errors[], offset_correction,
          anchor_check_version}

    任一检查失败 → anchor_status=unverified；失败不删除 finding（本函数只读，不触碰任何存储）。
    """
    errors: list[str] = []
    ok_text = check_text_exists(file_content, finding.get("text"))
    if not ok_text:
        errors.append(ANCHOR_TEXT_NOT_FOUND)
    ok_line = check_line_range(file_content, finding.get("line"))
    if not ok_line:
        errors.append(ANCHOR_LINE_RANGE_INVALID)
    ok_hash = check_hash_matches(file_content, finding.get("evidence_hash"))
    if not ok_hash:
        errors.append(ANCHOR_HASH_MISMATCH)
    ok_offset, offset = compute_offset_correction(file_content, finding.get("hunk_context"))
    if not ok_offset:
        errors.append(ANCHOR_OFFSET_UNDETERMINED)

    return {
        "finding_id": finding.get("id"),
        "file": finding.get("file"),
        "anchor_status": _ANCHOR_STATUS_VERIFIED if not errors else _ANCHOR_STATUS_UNVERIFIED,
        "checks": {
            "text_exists": ok_text,
            "line_range": ok_line,
            "hash_match": ok_hash,
            "offset_computed": ok_offset,
        },
        "errors": sorted(errors),
        "offset_correction": offset,
        "anchor_check_version": _ANCHOR_CHECK_VERSION,
    }


def locate_finding(finding: dict[str, Any], diffs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Best-effort deterministic relocation metadata for an unverified finding.

    This never changes the finding's trust result.  It only supplies a unique
    location candidate for the formal Code Reviewer; ambiguous matches return
    ``None`` rather than guessing.
    """
    code = str(finding.get("existing_code") or finding.get("text") or "").strip()
    if not code:
        return None
    loc = locate_existing_code(code, diffs, preferred_path=str(finding.get("file") or ""))
    if loc is None:
        return None
    return {"file": loc.path, "start_line": loc.start_line, "end_line": loc.end_line, "source": loc.source}
