# -*- coding: utf-8 -*-
"""V5.2.5 B-14 lossless-summary 仅无损的可回溯摘要（B-17 C7-P1~P10）。

设计依据：历史设计记录 B14-lossless-summary-design §2-§7
证据锚点：升级计划 §3.4（L155-169）、§3.1（L117-119）、§7（L244 第 9 条）；
          评审表 B-14 专节（L85-94）、L127、L173、L195、L238、L324、L340。

能力（T1-T5）：
- T1 五级内容分类器：P1 可靠 magic bytes/结构特征 > P2 显式可信内容声明
  > P3 严格解析成功 > P4 扩展名 > P5 路径 heuristic；
  冲突/无法识别/保护字段无法完整隔离 -> SUMMARY_NOT_SAFE（只存原文索引，fail-closed）；
- T2 sentinel 保护引擎：九类保护字段（代码块/命令/错误/路径/URL/数字/哈希/验收结论/授权）
  确定性提取、⟦LSM-<6位零填充⟧ 候选冲突检测、MAX_RESTORE_PASSES=8 嵌套、
  逐项恢复（提取逆序）与全文逐字节比对；
- T3 三类可逆折叠：json_fold（schema 提取/稳定键排序/重复值因子化）、
  log_index（重复计数+索引化，行级 keepends 无损）、code_index（全行索引+符号索引，不重写函数体）；
- T4 摘要产物序列化：双锚点（summary_format_version + summary_format_sha256）、
  索引六要素（source_path/content_type/byte_range/sha256/retrieve_handle/sentinel_list）、
  content_hash、sort_keys 稳定序列化、temp+rename 原子写 + readback + 幂等；
- T5 retrieve 校验器（句柄解析 -> 字节范围读取 -> _normalize_sha256/check_hash_matches 比对）
  + rebuild parity（fold 逆向 + sentinel 还原，与原文逐字节比对）。

全程无 LLM/模型/网络/DB/subprocess/时间戳/随机量；相同输入两次运行逐字节一致。
唯一内部依赖：cli/anchor_check.py（单向，复用 _normalize_sha256/check_hash_matches/_SHA256_RE）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from . import anchor_check

# --- 版本与错误码枚举 ---
SUMMARY_FORMAT_VERSION = "1.0.0"  # 复合版本：摘要产物 schema + 内容分类规则 + sentinel 保护规则 三域联动
MAX_RESTORE_PASSES = 8  # sentinel 嵌套恢复上限（评审表 L94 第 4 项 caveman 范式）

SUMMARY_NOT_SAFE = "SUMMARY_NOT_SAFE"
SUMMARY_INPUT_INVALID = "SUMMARY_INPUT_INVALID"
SUMMARY_RETRIEVE_FAILED = "SUMMARY_RETRIEVE_FAILED"
SUMMARY_READBACK_MISMATCH = "SUMMARY_READBACK_MISMATCH"
SUMMARY_VERIFY_FAILED = "SUMMARY_VERIFY_FAILED"

_CONTENT_TYPES = ("json", "log", "code", "text", "unknown")

# --- 三域规则定义（summary_format_sha256 双锚点内容源，防逃逸）---

# 域 1：内容分类规则表（T1，版本化；规则 ID 按字典序求值保证确定性）
_CLASSIFIER_RULES = [
    {"id": "code_magic", "priority": "P1", "pattern": r"(?m)^(?:def |class |import |from )", "type": "code"},
    {"id": "json_magic", "priority": "P1", "pattern": r"^[\{\[]", "type": "json"},
    {"id": "log_magic", "priority": "P1", "pattern": r"(?m)^(?:\d{4}-\d{2}-\d{2}[T ]|(?:ERROR|WARN|INFO|DEBUG|TRACE):)", "type": "log"},
]
_EXTENSION_MAP = {
    ".json": "json", ".log": "log",
    ".py": "code", ".js": "code", ".ts": "code", ".go": "code", ".java": "code",
    ".md": "text", ".txt": "text", ".csv": "text",
}
_PATH_HINTS = {"logs/": "log", "evidence/": "text", "docs/": "text", "scripts/": "code", "src/": "code"}
_DECLARED_TYPES = ("json", "log", "code", "text")

# 域 2：sentinel 保护规则（T2；规则 ID 字典序求值；fragment 逐字保留）
_SENTINEL_RULES = [
    # 围栏代码块整体提取（可带语言标注行；非贪婪，嵌套围栏逐轮收敛）
    {"id": "code_block", "pattern": r"(?ms)^(?P<fence>```+|~~~+)[^\n]*\n.*?^(?P=fence)[ \t]*$"},
    # 命令形态：提示符行 / 受控命令 ID 行
    {"id": "command", "pattern": r"(?m)^(?:[$>] |tp-spec |python |pip |npm |git |docker |curl |wget )[^\n]+"},
    # 错误形态
    {"id": "error", "pattern": r"(?im)^\s*(?:error|traceback|exception|failed)[^\n]*|\b(?:error|failed|failure):\s*[^\n]+"},
    # 哈希：sha256: 前缀或裸 64-hex（复用 _SHA256_RE 判定范式）
    {"id": "hash", "pattern": r"sha256:[0-9a-f]{64}|(?<![\w])[0-9a-f]{64}(?![\w])"},
    # 数字：版本号 / 时间戳 / 普通数字 token（排除 sentinel 串内序号）
    {"id": "number", "pattern": r"(?<!⟦LSM-)\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?\b|(?<!⟦LSM-)\b\d+(?:\.\d+)+\b|(?<!⟦LSM-)(?<![\d.])[0-9]+(?![\d.])"},
    # 路径形态（Windows 盘符 / 绝对 / 相对；盘符后 `(?![\\/])` 排除 URL 的 s:// 段，
    # `(?<![A-Za-z0-9_:/])` 排除 URL 的 // 段，使 URL 由 url 规则整体保护）
    {"id": "path", "pattern": r"[A-Za-z]:[\\/](?![\\/])[^\s\"'<>]+|(?<![A-Za-z0-9_:/])/(?:[\w.-]+/)*[\w.-]+|\.{1,2}/[\w./-]+"},
    # URL（受控 scheme）
    {"id": "url", "pattern": r"(?:https?|ftp)://[^\s\"'<>]+"},
    # 验收结论 / 状态决策枚举
    {"id": "accept_verdict", "pattern": r"\b(?:PASS|FAIL|REVIEW_COMPLETED|COMPLETED|BLOCKED|APPROVED|REJECTED)\b"},
    # 授权字段键值形态
    {"id": "auth_field", "pattern": r"(?m)\b(?:authorized_by|authorization_scope|actor)\s*[:=]\s*[^\n]+"},
]
_SENTINEL_PREFIX = "⟦LSM-"
_SENTINEL_SUFFIX = "⟧"
_SENTINEL_MAX_RETRY = 1 << 24  # 候选冲突确定性上限（2^24 次重试）

# 域 3：摘要产物 schema 描述（与产物结构一致，纳入双锚点）
_SCHEMA_TEXT = (
    "summary_format_version(summary_format_sha256 summary_type status content_hash source_base "
    "entries[source_path content_type byte_range sha256 retrieve_handle sentinel_list] fold)"
)

_RULES_TEXT = "|".join(
    json.dumps(_CLASSIFIER_RULES, ensure_ascii=False, sort_keys=True)
    + "|" + json.dumps(_SENTINEL_RULES, ensure_ascii=False, sort_keys=True)
    + "|" + _SCHEMA_TEXT
)
SUMMARY_FORMAT_SHA256 = "sha256:" + hashlib.sha256(_RULES_TEXT.encode("utf-8")).hexdigest()


# =====================================================================
# T1 内容分类器（五级优先级链，fail-closed）
# =====================================================================

def classify(content: str, source_path: str, declared_type: str | None = None) -> str | None:
    """五级分类：P1 魔数 > P2 声明 > P3 严格解析 > P4 扩展名 > P5 路径。

    返回 content_type（json/log/code/text）；无法识别或 P1 内部冲突返回 None（-> SUMMARY_NOT_SAFE）。
    """
    # P1：可靠 magic bytes / 结构特征（规则 ID 字典序求值；多命中且结论互斥 -> 冲突）
    hits: dict[str, str] = {}
    for rule in sorted(_CLASSIFIER_RULES, key=lambda r: r["id"]):
        if re.search(rule["pattern"], content):
            hits[rule["id"]] = rule["type"]
    distinct = sorted(set(hits.values()))
    if len(distinct) > 1:
        return None  # P1 内部冲突：无法裁决（fail-closed）
    if distinct:
        return distinct[0]
    # P2：显式且可信的内容声明（仅受控枚举；声明源为调用方受控 manifest）
    if declared_type in _DECLARED_TYPES:
        return declared_type
    # P3：严格解析成功（确定性解析器；当前唯一 json.loads）
    try:
        json.loads(content)
        return "json"
    except (ValueError, TypeError):
        pass
    # P4：受控扩展名表
    suffix = Path(source_path).suffix.lower()
    if suffix in _EXTENSION_MAP:
        return _EXTENSION_MAP[suffix]
    # P5：路径 heuristic（最低优先级）
    posix = source_path.replace("\\", "/")
    for hint, ctype in sorted(_PATH_HINTS.items()):
        if hint in posix:
            return ctype
    return None  # 无法识别


# =====================================================================
# T2 sentinel 保护引擎（九类保护字段，确定性，嵌套恢复）
# =====================================================================

def _sentinel_candidate(seq: int) -> str:
    return f"{_SENTINEL_PREFIX}{seq:06d}{_SENTINEL_SUFFIX}"


def _collect_spans(content: str, rules: list[dict[str, str]]) -> list[tuple[int, int, str, str]]:
    """单轮提取：按规则 ID 字典序全文扫描，收集非重叠命中段（重叠时规则序优先）。

    返回 [(start, end, fragment, rule_id)] 按 start 升序（均基于同一文本快照）。
    """
    spans: list[tuple[int, int, str, str]] = []
    for rule in sorted(rules, key=lambda r: r["id"]):
        for match in re.finditer(rule["pattern"], content):
            start, end = match.start(), match.end()
            # 跳过与已提取区间重叠的命中（先提取的规则优先，避免嵌套破坏）
            if any(start < s_end and end > s_start for s_start, s_end, _, _ in spans):
                continue
            spans.append((start, end, content[start:end], rule["id"]))
    spans.sort(key=lambda item: item[0])
    return spans


def _sentinel_rules_for(content_type: str | None) -> list[dict[str, str]]:
    """类型感知规则裁剪：json 折叠不改写数字（值表/骨架逐字保留），数字无需保护；
    其余类型数字保护生效（保护段随行保留，还原逐字节）。"""
    if content_type == "json":
        return [rule for rule in _SENTINEL_RULES if rule["id"] != "number"]
    return list(_SENTINEL_RULES)


def protect_fields(content: str, content_type: str | None = None,
                   max_passes: int = MAX_RESTORE_PASSES) -> tuple[str, list[dict[str, Any]], bool]:
    """sentinel 化：多轮提取（嵌套逐层），候选冲突检测，MAX_RESTORE_PASSES 上限。

    返回 (sentinelized_text, sentinel_list 按提取顺序, ok)；不收敛 -> (原文, [], False)。
    sentinel_list 元素：{sentinel_id, fragment, byte_range, rule_id, pass_no}；
    byte_range 为 fragment 在提取轮文本中的字节区间（还原以全文逐字节比对兜底）。
    """
    rules = _sentinel_rules_for(content_type)
    current = content
    sentinels: list[dict[str, Any]] = []
    used: set[str] = set()
    fragment_to_sentinel: dict[str, str] = {}  # 相同片段复用同一 sentinel（重复值因子化）
    seq = 0
    for pass_no in range(1, max_passes + 1):
        spans = _collect_spans(current, rules)
        if not spans:
            return current, sentinels, True
        # 先分配候选（冲突检测基于当前文本 + 已用集合；相同 fragment 复用），再构建新文本
        assignments: list[tuple[int, int, str, str, str, list[int]]] = []
        for start, end, fragment, rule_id in spans:
            candidate = fragment_to_sentinel.get(fragment)
            if candidate is None:
                seq += 1
                candidate = _sentinel_candidate(seq)
                retries = 0
                while (candidate in current or candidate in used) and retries < _SENTINEL_MAX_RETRY:
                    seq += 1
                    candidate = _sentinel_candidate(seq)
                    retries += 1
                if retries >= _SENTINEL_MAX_RETRY:
                    return content, [], False  # 候选冲突无法解决 -> 保护不完整
                used.add(candidate)
                fragment_to_sentinel[fragment] = candidate
            assignments.append((start, end, fragment, rule_id, candidate,
                                [len(current[:start].encode("utf-8")),
                                 len(current[:end].encode("utf-8"))]))
        # 构建新文本：未命中段原文保留 + 候选（按 start 升序拼接）
        parts: list[str] = []
        cursor = 0
        for start, end, _fragment, _rule_id, candidate, _br in assignments:
            parts.append(current[cursor:start])
            parts.append(candidate)
            cursor = end
        parts.append(current[cursor:])
        current = "".join(parts)
        for start, end, fragment, rule_id, candidate, byte_range in assignments:
            sentinels.append({
                "sentinel_id": candidate,
                "fragment": fragment,
                "byte_range": byte_range,
                "rule_id": rule_id,
                "pass_no": pass_no,
            })
    return content, [], False  # 超过 MAX_RESTORE_PASSES 仍未收敛 -> 保护不完整


def restore_fields(sentinelized: str, sentinel_list: list[dict[str, Any]]) -> str:
    """逐项恢复：按提取顺序逆序还原（嵌套时后提取的先还原）。"""
    result = sentinelized
    for item in reversed(sentinel_list):
        result = result.replace(item["sentinel_id"], item["fragment"])
    return result


# =====================================================================
# T3 三类可逆折叠（全部 parity 可还原）
# =====================================================================

def _json_leaf_spans(text: str) -> list[tuple[int, int, Any]]:
    """递归定位 JSON 叶子值（str/number/bool/null）的字符区间，供骨架替换。

    容器内部值统一经 walk 从值起点递归解析（容忍字符串值内的 sentinel 占位符）。
    """
    decoder = json.JSONDecoder()
    spans: list[tuple[int, int, Any]] = []

    def skip_ws(i: int) -> int:
        while i < len(text) and text[i] in " \t\r\n":
            i += 1
        return i

    def walk(i: int) -> int:
        i = skip_ws(i)
        if i >= len(text):
            return i
        c = text[i]
        if c == "{":
            i += 1
            while True:
                i = skip_ws(i)
                if i >= len(text):
                    return i
                if text[i] == "}":
                    return i + 1
                _, i = decoder.raw_decode(text, i)  # 键（字符串）；必须用返回值推进游标
                i = skip_ws(i)
                if i < len(text) and text[i] == ":":
                    i += 1
                val_start = skip_ws(i)
                i = walk(val_start)
                i = skip_ws(i)
                if i < len(text) and text[i] == ",":
                    i += 1
        elif c == "[":
            i += 1
            while True:
                i = skip_ws(i)
                if i >= len(text):
                    return i
                if text[i] == "]":
                    return i + 1
                val_start = skip_ws(i)
                i = walk(val_start)
                i = skip_ws(i)
                if i < len(text) and text[i] == ",":
                    i += 1
        else:
            val_start = i
            val, i = decoder.raw_decode(text, i)
            spans.append((val_start, i, val))
        return i

    walk(0)
    return spans


def fold_json(sentinelized: str) -> dict[str, Any]:
    """json_fold：schema 提取（键路径+类型+长度）+ 稳定键排序 + 重复值因子化 + 骨架。

    骨架 = 原文（叶子值替换为 ⟦VAL-<ID>⟧ 占位符，键/结构/空白逐字保留）；
    值表去重（相同原文切片复用同一 ID）-> 重建 = 占位符回填，逐字节还原。
    """
    spans = _json_leaf_spans(sentinelized)
    values: dict[str, str] = {}
    id_by_slice: dict[str, str] = {}
    schema: list[dict[str, Any]] = []
    skeleton = sentinelized
    # 从后往前替换，避免偏移错乱
    for start, end, val in sorted(spans, key=lambda s: -s[0]):
        slice_text = sentinelized[start:end]
        vid = id_by_slice.get(slice_text)
        if vid is None:
            vid = f"⟦VAL-{len(values) + 1:06d}⟧"
            id_by_slice[slice_text] = vid
            values[vid] = slice_text
        skeleton = skeleton[:start] + vid + skeleton[end:]
    # schema 索引（键路径；按键稳定排序输出 -> 稳定键排序语义）
    parsed = json.loads(sentinelized)

    def walk_tree(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key in sorted(node):
                child = node[key]
                child_path = f"{path}.{key}" if path else str(key)
                if isinstance(child, (dict, list)):
                    walk_tree(child, child_path)
                else:
                    slice_text = json.dumps(child, ensure_ascii=False, separators=(",", ":"))
                    schema.append({
                        "key_path": child_path,
                        "value_type": type(child).__name__,
                        "value_len": len(slice_text),
                        "value_id": id_by_slice.get(slice_text, ""),
                    })
        elif isinstance(node, list):
            for idx, child in enumerate(node):
                child_path = f"{path}[{idx}]"
                if isinstance(child, (dict, list)):
                    walk_tree(child, child_path)
                else:
                    slice_text = json.dumps(child, ensure_ascii=False, separators=(",", ":"))
                    schema.append({
                        "key_path": child_path,
                        "value_type": type(child).__name__,
                        "value_len": len(slice_text),
                        "value_id": id_by_slice.get(slice_text, ""),
                    })

    walk_tree(parsed, "")
    return {"schema": schema, "values": values, "skeleton": skeleton}


def rebuild_json(fold: dict[str, Any]) -> str:
    """json_fold 逆向：骨架占位符回填 -> sentinelized 原文。"""
    result = fold["skeleton"]
    for vid, slice_text in sorted(fold["values"].items(), reverse=True):
        result = result.replace(vid, slice_text)
    return result


def fold_log(sentinelized: str) -> dict[str, Any]:
    """log_index：行级索引（keepends 逐字节）；重复行去重计数+位置索引；唯一行原样保留。"""
    rows = sentinelized.splitlines(keepends=True)
    by_text: dict[str, list[int]] = {}
    for idx, row in enumerate(rows):
        by_text.setdefault(row, []).append(idx)
    lines = []
    for idx, row in enumerate(rows):
        positions = by_text[row]
        if positions and positions[0] == idx:
            lines.append({"index": idx, "text": row, "repeat_positions": positions[1:]})
        # 重复行的后续出现不单独存文本（引用首次位置）
    return {"lines": lines}


def rebuild_log(fold: dict[str, Any]) -> str:
    """log_index 逆向：按行号展开（重复行引用首次文本）-> sentinelized 原文。"""
    text_by_index: dict[int, str] = {}
    for line in fold["lines"]:
        text_by_index[line["index"]] = line["text"]
        for pos in line["repeat_positions"]:
            text_by_index[pos] = line["text"]
    return "".join(text_by_index[i] for i in sorted(text_by_index))


def fold_code(sentinelized: str) -> dict[str, Any]:
    """code_index：全行索引（parity 必需）+ 符号索引（def/class）；不重写函数体、不改写引用片段。"""
    rows = sentinelized.splitlines(keepends=True)
    lines = [{"index": i, "text": row} for i, row in enumerate(rows)]
    symbols = []
    for i, row in enumerate(rows, start=1):
        match = re.match(r"^\s*(?:def|class|function)\s+([A-Za-z_]\w*)", row)
        if match:
            symbols.append({"name": match.group(1), "line": i,
                            "kind": "def" if "def " in row[:8] or "function " in row[:12] else "class"})
    return {"lines": lines, "symbols": symbols, "changed_lines": []}


def rebuild_code(fold: dict[str, Any]) -> str:
    """code_index 逆向：按行号重建 -> sentinelized 原文。"""
    lines = sorted(fold["lines"], key=lambda item: item["index"])
    return "".join(item["text"] for item in lines)


_FOLD_BUILDERS = {"json": fold_json, "log": fold_log, "code": fold_code, "text": None}
_FOLD_REBUILDERS = {"json": rebuild_json, "log": rebuild_log, "code": rebuild_code}


def fold_content(content_type: str, sentinelized: str) -> dict[str, Any] | None:
    """按类型折叠；text 直存；未知/失败返回 None（-> SUMMARY_NOT_SAFE）。"""
    if content_type == "text":
        return {"content": sentinelized}
    builder = _FOLD_BUILDERS.get(content_type)
    if builder is None:
        return None
    try:
        return builder(sentinelized)
    except (ValueError, TypeError, KeyError):
        return None


def rebuild_fold(content_type: str, fold: dict[str, Any]) -> str | None:
    """fold 逆向 -> sentinelized 文本；失败返回 None。"""
    if content_type == "text":
        return fold.get("content")
    rebuilder = _FOLD_REBUILDERS.get(content_type)
    if rebuilder is None:
        return None
    try:
        return rebuilder(fold)
    except (KeyError, TypeError, ValueError):
        return None


# =====================================================================
# T4 摘要产物组装与序列化（双锚点 + 六要素 + content_hash + 原子写）
# =====================================================================

def _full_entry(source_path: str, content_type: str, content_bytes: int, content_sha256: str,
                sentinel_list: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source_path": source_path,
        "content_type": content_type,
        "byte_range": [0, content_bytes],
        "sha256": content_sha256,
        "retrieve_handle": f"rel://{source_path}#B0-{content_bytes}",
        "sentinel_list": sentinel_list,
    }


def build_summary(content: str, source_path: str, source_base: str,
                  summary_type: str = "package_summary",
                  declared_type: str | None = None,
                  max_passes: int = MAX_RESTORE_PASSES) -> dict[str, Any]:
    """生成摘要产物（OK 或 SUMMARY_NOT_SAFE 均为合法产物）。

    流程：分类（原文）-> sentinel 化 -> 折叠 -> 索引条目 -> 双锚点序列化。
    max_passes 为 sentinel 嵌套恢复上限（默认 MAX_RESTORE_PASSES=8；
    测试可用更小值验证嵌套超限 fail-closed 路径）。
    """
    content_bytes = len(content.encode("utf-8"))
    content_sha256 = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

    ctype = classify(content, source_path, declared_type)
    if ctype is None:
        # 无法识别 / P1 内部冲突 -> SUMMARY_NOT_SAFE，只存原文索引
        entry = _full_entry(source_path, "unknown", content_bytes, content_sha256, [])
        body = {
            "summary_format_version": SUMMARY_FORMAT_VERSION,
            "summary_format_sha256": SUMMARY_FORMAT_SHA256,
            "summary_type": summary_type,
            "status": SUMMARY_NOT_SAFE,
            "source_base": source_base,
            "entries": [entry],
            "fold": {},
        }
        return _finalize(body)

    sentinelized, sentinels, ok = protect_fields(content, content_type=ctype, max_passes=max_passes)
    if not ok:
        # 保护字段无法完整隔离 -> SUMMARY_NOT_SAFE，只存原文索引
        entry = _full_entry(source_path, ctype, content_bytes, content_sha256, [])
        body = {
            "summary_format_version": SUMMARY_FORMAT_VERSION,
            "summary_format_sha256": SUMMARY_FORMAT_SHA256,
            "summary_type": summary_type,
            "status": SUMMARY_NOT_SAFE,
            "source_base": source_base,
            "entries": [entry],
            "fold": {},
        }
        return _finalize(body)

    fold_data = fold_content(ctype, sentinelized)
    if fold_data is None:
        # 折叠失败（如魔数判定 json 但严格解析失败）-> fail-closed
        entry = _full_entry(source_path, ctype, content_bytes, content_sha256, [])
        body = {
            "summary_format_version": SUMMARY_FORMAT_VERSION,
            "summary_format_sha256": SUMMARY_FORMAT_SHA256,
            "summary_type": summary_type,
            "status": SUMMARY_NOT_SAFE,
            "source_base": source_base,
            "entries": [entry],
            "fold": {},
        }
        return _finalize(body)

    entry = _full_entry(source_path, ctype, content_bytes, content_sha256, sentinels)
    body = {
        "summary_format_version": SUMMARY_FORMAT_VERSION,
        "summary_format_sha256": SUMMARY_FORMAT_SHA256,
        "summary_type": summary_type,
        "status": "OK",
        "source_base": source_base,
        "entries": [entry],
        "fold": fold_data,
    }
    return _finalize(body)


def _finalize(body: dict[str, Any]) -> dict[str, Any]:
    """content_hash = 产物自身（不含 content_hash 字段）稳定序列化后的 SHA-256。"""
    serialized = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    body["content_hash"] = "sha256:" + hashlib.sha256(serialized).hexdigest()
    return body


def serialize_summary(summary: dict[str, Any]) -> bytes:
    """稳定序列化：sort_keys=True + 固定换行；相同输入两次运行逐字节一致。"""
    return json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def summary_filename(summary: dict[str, Any]) -> str:
    """产物文件名按内容幂等命名：summary-<content_hash 前 16 hex>.json。"""
    return f"summary-{summary['content_hash'][7:23]}.json"


def verify_summary(summary: dict[str, Any]) -> tuple[bool, str]:
    """双锚点 + content_hash 校验（C7-P9）：

    - summary_format_version 与当前版本不一致 -> 旧产物（版本变 -> 旧包失效）拒绝；
    - summary_format_sha256 与当前规则内容重算不一致 -> 内容篡改拒绝（fail-closed）；
    - content_hash 与自身重算不一致 -> 产物被篡改拒绝。
    """
    if summary.get("summary_format_version") != SUMMARY_FORMAT_VERSION:
        return False, f"{SUMMARY_VERIFY_FAILED}: format version mismatch"
    if summary.get("summary_format_sha256") != SUMMARY_FORMAT_SHA256:
        return False, f"{SUMMARY_VERIFY_FAILED}: format sha256 mismatch"
    body = {k: v for k, v in summary.items() if k != "content_hash"}
    serialized = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    expected = "sha256:" + hashlib.sha256(serialized).hexdigest()
    if summary.get("content_hash") != expected:
        return False, f"{SUMMARY_VERIFY_FAILED}: content hash mismatch"
    return True, "ok"


def atomic_write_artifact(path: Path, data: bytes, expected_sha256: str) -> str:
    """temp+rename 原子写 + readback + 幂等（C7-P10）：

    - 目标已存在且内容 hash 一致 -> 幂等返回 "idempotent"（不重写）；
    - 目标已存在但 hash 不一致 -> 冲突失败（禁止覆盖既有产物）；
    - 写入后 readback 重算 hash 不一致 -> 删除目标、保持失败（无半成品）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    actual_existing = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    if actual_existing is not None:
        if actual_existing == expected_sha256:
            return "idempotent"
        raise ValueError(f"{SUMMARY_READBACK_MISMATCH}: target exists with different content: {path}")
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected_sha256:
        path.unlink(missing_ok=True)
        raise ValueError(
            f"{SUMMARY_READBACK_MISMATCH}: readback hash mismatch: {path} "
            f"(expected {expected_sha256}, got {actual})"
        )
    return "written"


# =====================================================================
# T5 retrieve 校验器 + rebuild parity
# =====================================================================

def parse_handle(retrieve_handle: str) -> tuple[str, int, int]:
    """解析 rel://<source_path>#B<start>-<end>；非法 -> ValueError（fail-closed）。"""
    if not retrieve_handle.startswith("rel://"):
        raise ValueError(f"{SUMMARY_RETRIEVE_FAILED}: invalid handle: {retrieve_handle}")
    path_part, _, range_part = retrieve_handle[6:].partition("#")
    if not range_part.startswith("B") or "-" not in range_part:
        raise ValueError(f"{SUMMARY_RETRIEVE_FAILED}: invalid handle: {retrieve_handle}")
    try:
        start_s, end_s = range_part[1:].split("-", 1)
        start, end = int(start_s), int(end_s)
    except ValueError as exc:
        raise ValueError(f"{SUMMARY_RETRIEVE_FAILED}: invalid handle: {retrieve_handle}") from exc
    if start < 0 or end < start:
        raise ValueError(f"{SUMMARY_RETRIEVE_FAILED}: invalid byte range: {retrieve_handle}")
    return path_part, start, end


def retrieve(source_base: Path, entry: dict[str, Any]) -> bytes:
    """索引 retrieve：句柄解析 -> 字节范围读取 -> hash 校验（anchor_check 单向依赖）。

    校验失败/文件缺失/句柄非法 -> ValueError（fail-closed，不返回部分/篡改内容）。
    """
    handle = entry.get("retrieve_handle")
    if not isinstance(handle, str):
        raise ValueError(f"{SUMMARY_RETRIEVE_FAILED}: missing retrieve_handle")
    rel_path, start, end = parse_handle(handle)
    target = (source_base / rel_path).resolve()
    base_resolved = source_base.resolve()
    if base_resolved not in target.parents and target != base_resolved:
        raise ValueError(f"{SUMMARY_RETRIEVE_FAILED}: path escapes source_base: {rel_path}")
    if not target.is_file():
        raise ValueError(f"{SUMMARY_RETRIEVE_FAILED}: source file missing: {rel_path}")
    data = target.read_bytes()
    if end > len(data):
        raise ValueError(f"{SUMMARY_RETRIEVE_FAILED}: byte range out of bounds: {handle}")
    chunk = data[start:end]
    if not anchor_check.check_hash_matches(chunk.decode("utf-8", errors="surrogateescape"),
                                           entry.get("sha256")):
        raise ValueError(f"{SUMMARY_RETRIEVE_FAILED}: hash mismatch: {handle}")
    return chunk


def rebuild(summary: dict[str, Any], source_base: Path) -> bytes:
    """parity 重建（C7-P5）：fold 逆向 -> sentinel 还原 -> 与 retrieve 原文逐字节比对。

    重建成功且逐字节相等 -> 返回重建字节；任何失败 -> ValueError（fail-closed）。
    """
    if summary.get("status") != "OK":
        raise ValueError(f"{SUMMARY_VERIFY_FAILED}: cannot rebuild SUMMARY_NOT_SAFE artifact")
    entries = summary.get("entries", [])
    if not entries:
        raise ValueError(f"{SUMMARY_VERIFY_FAILED}: missing entries")
    entry = entries[0]
    ctype = entry.get("content_type")
    sentinelized = rebuild_fold(ctype, summary.get("fold", {}))
    if sentinelized is None:
        raise ValueError(f"{SUMMARY_VERIFY_FAILED}: fold rebuild failed for {ctype}")
    restored = restore_fields(sentinelized, entry.get("sentinel_list", []))
    original = retrieve(source_base, entry)
    if restored.encode("utf-8") != original:
        raise ValueError(f"{SUMMARY_VERIFY_FAILED}: parity mismatch: rebuilt != original bytes")
    return restored.encode("utf-8")


# =====================================================================
# T6 CLI 子命令（--simulate 零写入）
# =====================================================================

def add_lossless_summary_subparsers(subparsers) -> None:
    p = subparsers.add_parser(
        "lossless-summary",
        help="V5.2.5 B-14 lossless reversible summary: content classify + sentinel protect + fold (no state change)",
    )
    p.add_argument("--source-base", required=True, help="base dir of original files (evidence/ or .execution/)")
    p.add_argument("--input", required=True, help="original file path (relative to source-base)")
    p.add_argument("--output-dir", required=True, help="output directory for summary artifacts")
    p.add_argument("--type", default="package_summary",
                   choices=["package_summary", "stage_summary", "tool_output_summary"],
                   help="summary_type (default package_summary)")
    p.add_argument("--declared-type", default=None, choices=["json", "log", "code", "text"],
                   help="trusted content declaration (P2, must be in controlled enum)")
    p.add_argument("--simulate", action="store_true", help="zero-write mode: compute everything, write nothing")
    p.set_defaults(func=cmd_lossless_summary)


def cmd_lossless_summary(args) -> int:
    """CLI 入口：读取原文 -> 生成摘要 -> 原子写 / simulate 拟写清单。

    退出码：0 成功（含 SUMMARY_NOT_SAFE 合法产物）；非 0 fail-closed
    （输入非法 / 校验失败 / 原子写失败）。
    """
    source_base = Path(args.source_base)
    rel_path = Path(args.input)
    if rel_path.is_absolute():
        print(f"{SUMMARY_INPUT_INVALID}: input must be relative to source-base: {args.input}", file=sys.stderr)
        return 2
    target = (source_base / rel_path).resolve()
    if source_base.resolve() not in target.parents:
        print(f"{SUMMARY_INPUT_INVALID}: input escapes source-base: {args.input}", file=sys.stderr)
        return 2
    if not target.is_file():
        print(f"{SUMMARY_INPUT_INVALID}: source file missing: {args.input}", file=sys.stderr)
        return 2
    try:
        # newline=""：不做换行符转换（\r\n 保留），保证 content.encode("utf-8") 与文件原始字节一致
        # （否则 retrieve 的逐字节 hash 校验在 CRLF 文件上必然失配）
        with target.open("r", encoding="utf-8", newline="") as handle:
            content = handle.read()
    except (UnicodeDecodeError, OSError) as exc:
        print(f"{SUMMARY_INPUT_INVALID}: cannot read source as UTF-8: {exc}", file=sys.stderr)
        return 2

    summary = build_summary(content, rel_path.as_posix(), args.source_base, args.type, args.declared_type)
    ok, reason = verify_summary(summary)
    if not ok:
        print(reason, file=sys.stderr)
        return 2

    serialized = serialize_summary(summary)
    expected_sha256 = hashlib.sha256(serialized).hexdigest()  # readback/幂等校验目标 = 写入字节 hash
    filename = summary_filename(summary)
    out_path = Path(args.output_dir) / filename

    if args.simulate:
        print(f"simulate: would write {out_path} ({len(serialized)} bytes, "
              f"content_hash {summary['content_hash']})")
        return 0

    try:
        action = atomic_write_artifact(out_path, serialized, expected_sha256)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"lossless-summary: {action} {out_path} (status {summary['status']}, "
          f"format {summary['summary_format_version']})")
    return 0
