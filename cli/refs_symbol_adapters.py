# -*- coding: utf-8 -*-
"""V5.2.0 B-12 symbol 适配器（Java/Python/Go/TS/JS 五语言行级正则确定性定位）。

设计依据：历史设计记录 B12-structured-refs-design §4
证据锚点：升级计划 §3.2 L138-139 / §6 L302 / §7 L316。

纯确定性定位，禁止 LLM/模型型定位（§6 L302）。
适配器与规则版本化：symbol_adapters_version + content SHA-256 双锚点。

R4 降级：无适配器/未定位 → LOCAL_UNVERIFIED + 告警码（禁止 NOT_APPLICABLE 消警）。
R5：声明 LOCAL_VERIFIED 但无法定位 → 当次立即失败。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SYMBOL_ADAPTERS_VERSION = "1.0.0"

# 错误码（与 structured_refs 共享定义）
SYMBOL_ADAPTER_MISSING = "SYMBOL_ADAPTER_MISSING"
SYMBOL_NOT_FOUND = "SYMBOL_NOT_FOUND"

# 语言 → 适配器规则
_SYMBOL_ADAPTERS = {
    "python": {
        "patterns": [
            r"^\s*class\s+(\w+)",
            r"^\s*def\s+(\w+)\s*\(",
            r"^\s*async\s+def\s+(\w+)\s*\(",
        ],
    },
    "java": {
        "patterns": [
            r"^\s*(?:public|private|protected|static|final|abstract|synchronized)\s+(?:class|interface|@interface|enum)\s+(\w+)",
            r"^\s*(?:public|private|protected|static|final|abstract|synchronized|native)\s+\w+\s+(\w+)\s*\(",
            r"^\s*(?:public|private|protected)\s+\w+\s+(\w+)\s*\(",
            r"^\s*\w+\s+(\w+)\s*\(",  # fallback for method definition
        ],
    },
    "go": {
        "patterns": [
            r"^func\s+(?:\([^)]*\)\s+)?(\w+)\s*\(",
            r"^type\s+(\w+)\s+(?:struct|interface|func|map|chan|\[\])",
            r"^var\s+(\w+)\s",
            r"^const\s+(\w+)\s",
        ],
    },
    "typescript": {
        "patterns": [
            r"^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)",
            r"^(?:export\s+)?interface\s+(\w+)",
            r"^(?:export\s+)?(?:default\s+)?function\s+(\w+)\s*\(",
            r"^(?:export\s+)?(?:default\s+)?const\s+(\w+)\s*(?::|=[^=])",
            r"^(?:export\s+)?type\s+(\w+)\s*=",
            r"^(?:export\s+)?enum\s+(\w+)",
            r"^(?:export\s+)?abstract\s+class\s+(\w+)",
        ],
    },
    "javascript": {
        "patterns": [
            r"^(?:export\s+)?(?:default\s+)?class\s+(\w+)",
            r"^(?:export\s+)?(?:default\s+)?function\s+(\w+)\s*\(",
            r"^(?:export\s+)?(?:default\s+)?const\s+(\w+)\s*(?::|=[^=])",
            r"^(?:export\s+)?(?:default\s+)?let\s+(\w+)\s*(?::|=[^=])",
            r"^(?:export\s+)?(?:default\s+)?var\s+(\w+)\s*(?::|=[^=])",
            r"^(?:export\s+)?(?:default\s+)?async\s+function\s+(\w+)\s*\(",
        ],
    },
}

SYMBOL_ADAPTERS_SHA256 = "sha256:" + hashlib.sha256(
    json.dumps(_SYMBOL_ADAPTERS, sort_keys=True).encode("utf-8")
).hexdigest()

# 语言 → 扩展名映射
_LANG_EXTENSIONS: dict[str, list[str]] = {
    "python": [".py"],
    "java": [".java"],
    "go": [".go"],
    "typescript": [".ts", ".tsx"],
    "javascript": [".js", ".jsx", ".mjs", ".cjs"],
}


def detect_language(file_path: str) -> str | None:
    """根据文件扩展名检测语言；不在五清单内返回 None。"""
    for lang, exts in _LANG_EXTENSIONS.items():
        if any(file_path.endswith(ext) for ext in exts):
            return lang
    return None


def locate_symbol(file_content: str, symbol_name: str, language: str | None) -> dict[str, Any]:
    """确定性定位符号在文件中的行号。

    输入：
        file_content: 文件内容（字符串）
        symbol_name: 符号名（如 main.run 或 main）
        language: 语言标识（python/java/go/typescript/javascript）；None 表示无适配器

    返回：
        {
            "found": bool,       # 是否定位到
            "line": int | None,  # 1-based 行号
            "location": str,     # 可回链位置 file:symbol:line 或 ''
            "error_code": str | None,  # SYMBOL_ADAPTER_MISSING / SYMBOL_NOT_FOUND / None
        }

    注意：
        - 支持点分符号名（如 module.ClassName.method），依次在各层查找
        - 禁止 LLM/模型型定位；全部 re.search 行级正则
        - 无适配器 → SYMBOL_ADAPTER_MISSING（不阻断，告警级）
        - 有适配器但未定位 → SYMBOL_NOT_FOUND（不阻断，告警级）
    """
    if language is None:
        return {
            "found": False,
            "line": None,
            "location": "",
            "error_code": SYMBOL_ADAPTER_MISSING,
        }

    parts = symbol_name.split(".")
    # 对完整符号名（含点）尝试逐层查找，优先匹配最长后缀
    candidates = []
    for i in range(len(parts)):
        candidate = ".".join(parts[i:])
        candidates.append(candidate)
    # 也尝试直接匹配完整名
    candidates.append(symbol_name)

    lines = file_content.splitlines()
    adapters = _SYMBOL_ADAPTERS.get(language, {})
    patterns = adapters.get("patterns", [])

    for candidate in candidates:
        for pattern in patterns:
            for line_idx, line in enumerate(lines, 1):
                m = re.search(pattern, line)
                if m:
                    # 检查 group 1 是否匹配候选符号名
                    matched = m.group(1)
                    if matched == candidate:
                        return {
                            "found": True,
                            "line": line_idx,
                            "location": f"{candidate}:{line_idx}",
                            "error_code": None,
                        }
                    # 对于点分符号，检查是否匹配最后一段
                    if candidate == symbol_name and "." in symbol_name:
                        parts = symbol_name.split(".")
                        if matched == parts[-1]:
                            return {
                                "found": True,
                                "line": line_idx,
                                "location": f"{matched}:{line_idx}",
                                "error_code": None,
                            }

    return {
        "found": False,
        "line": None,
        "location": "",
        "error_code": SYMBOL_NOT_FOUND,
    }