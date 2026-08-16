# -*- coding: utf-8 -*-
"""V5.2.3 UTF-8 安全输入守卫（A-05 修复：真实中文 mojibake 识别）。

纯 stdlib、离线。所有进入权威事件/handoff 的自由文本（summary/changes/
risks/evidence/action/constraint/decision/authorization）
在写入前必须通过本模块校验：

- UTF-8 round-trip：``text.encode("utf-8").decode("utf-8") == text``；
- mojibake 特征检测：U+FFFD 替换符、UTF-8 被按 Latin-1/Windows-1252 误读的
  双字节序列（如 ``\u00c3`` 族、``â€`` 族）、连续 3+ 问号占位；
- 可逆重解码检测（V5.2.3 修复）：尝试将文本按 latin1/cp1252 重新编码后再按
  UTF-8 解码，若产生明显 CJK 而原文本含高比例扩展 Latin 字符，判定为
  中文 UTF-8→Latin-1 误读（实际样本如 ``å¼€å§‹`` → ``开始``）；
  正常西欧文本（法语等）不会被拒绝。

命中高风险特征时抛 EncodingValidationError（CLI 输出 ENCODING_VALIDATION_FAILED），
调用方必须保证数据库与投影零变化。

设计依据：V5.2.3 AI-A 定向修复任务书 §7 与审查报告 §3.6。
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# U+FFFD（replacement character）：解码失败的明确痕迹。
_MOJIBAKE_REPLACEMENT = re.compile(r"\ufffd")

# UTF-8 两字节序列被按 Latin-1 误读：Ã（0xC3 误读）+ 高位字节（0x80-0xBF）。
_MOJIBAKE_LATIN1 = re.compile(r"\u00c3[\x80-\xbf]")

# UTF-8 三字节序列被按 Windows-1252 误读：â€（E2 80 误读）后跟高位字符
# （第三字节 0x80-0xBF 按 cp1252 映射为 œ/™/„/“/”/–/— 等高位 Unicode）。
_MOJIBAKE_CP1252 = re.compile(r"â€[^\x00-\x7f]")

# 连续问号占位（任务书示例特征；3+ 连续才视为可疑）。
_MOJIBAKE_QMARK = re.compile(r"\?{3,}")

# CJK 统一表意文字（含扩展 A）与全角符号：重解码后出现即视为中文恢复证据。
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]")

# 扩展 Latin-1 字符（U+0080-U+00FF）：mojibake 原文的主体字符集。
_LATIN1_EXT_RE = re.compile(r"[\u0080-\u00ff]")

# 可逆重解码需要的最少 CJK 命中数（正常西欧文本解码失败或 CJK=0，误报风险低）。
_MIN_CJK_HITS = 1
# 原文中扩展 Latin 字符的最小占比（防“少量偶然字符”误报）。
_MIN_LATIN1_RATIO = 0.4


class EncodingValidationError(ValueError):
    """UTF-8 输入校验失败；CLI 映射为 ENCODING_VALIDATION_FAILED。"""

    def __init__(self, message: str, reason: str = "", sample: str = "", recovered_preview: str = ""):
        super().__init__(message)
        self.reason = reason
        self.sample = sample
        self.recovered_preview = recovered_preview


def roundtrip_ok(text: str) -> bool:
    """UTF-8 round-trip 校验。非 str 输入/非法代理项/无法编码时返回 False。"""
    if not isinstance(text, str):
        return False
    try:
        return text.encode("utf-8").decode("utf-8") == text
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False


def _reversible_mojibake(text: str) -> Optional[Tuple[str, str]]:
    """可逆重解码检测：中文 UTF-8 → Latin-1/CP1252 误读。

    返回 (recovered_preview, reason) 或 None。
    策略（任务书 §7.2）：
    1. 原文须含高比例扩展 Latin 字符（U+0080-U+00FF）；
    2. 将原文按 latin1/cp1252 编码为字节；
    3. 再按 UTF-8 解码；
    4. 若成功且出现 >= 2 个 CJK 字符，判定疑似 mojibake。
    正常西欧文本（如法语 éàç）单字节扩展字符无法组成合法 UTF-8 序列，天然不命中。
    """
    if not text:
        return None
    latin_hits = len(_LATIN1_EXT_RE.findall(text))
    if latin_hits == 0:
        return None
    if latin_hits / len(text) < _MIN_LATIN1_RATIO:
        return None
    encodings = ("cp1252", "latin1")
    for enc in encodings:
        try:
            raw = text.encode(enc)
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        # 解码失败时逐字节截尾重试（mojibake 尾部字节可能丢失/为未定义码位，
        # 如“状态”= E7 8A B6 E6 80 81 的末字节 0x81 在部分环境下不可见）。
        for cut in (0, 1, 2, 3):
            payload = raw if cut == 0 else raw[:-cut]
            if not payload:
                continue
            try:
                recovered = payload.decode("utf-8")
            except UnicodeDecodeError:
                continue
            cjk_hits = _CJK_RE.findall(recovered)
            if len(cjk_hits) >= _MIN_CJK_HITS:
                preview = recovered[:20]
                return preview, f"suspected_utf8_as_{enc}_mojibake"
    return None


def detect_mojibake(text: str) -> List[str]:
    """检测明显乱码特征，返回命中特征名列表（无命中返回空列表）。"""
    hits: List[str] = []
    if _MOJIBAKE_REPLACEMENT.search(text):
        hits.append("U+FFFD replacement char")
    if _MOJIBAKE_LATIN1.search(text):
        hits.append("latin-1 mojibake (Ã + high byte)")
    if _MOJIBAKE_CP1252.search(text):
        hits.append("windows-1252 mojibake (â€ family)")
    if _MOJIBAKE_QMARK.search(text):
        hits.append("repeated '?' placeholder")
    recovered = _reversible_mojibake(text)
    if recovered is not None:
        preview, reason = recovered
        hits.append(f"{reason} (recovered: {preview})")
    return hits


def validate_input(text: str, field: str = "input") -> None:
    """校验单个字段；失败抛 EncodingValidationError（含字段名与特征）。"""
    if not roundtrip_ok(text):
        raise EncodingValidationError(
            f"{field}: UTF-8 round-trip failed (text cannot be safely re-encoded)"
        )
    hits = detect_mojibake(text)
    if hits:
        detail = "; ".join(hits)
        recovered = _reversible_mojibake(text)
        reason = recovered[1] if recovered else ""
        preview = recovered[0] if recovered else ""
        raise EncodingValidationError(
            f"{field}: high-risk mojibake pattern detected: {detail}",
            reason=reason,
            sample=text[:40],
            recovered_preview=preview,
        )


def validate_list(items, field: str) -> None:
    """校验字符串列表的每个元素。"""
    for item in items or []:
        validate_input(str(item), field)


def validate_texts(plain: str, lists: dict) -> None:
    """组合校验：单个字段 + 若干列表字段。plain 为 summary 等必填文本。"""
    validate_input(plain, "summary")
    for field, items in (lists or {}).items():
        validate_list(items, field)
