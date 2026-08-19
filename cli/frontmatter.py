# -*- coding: utf-8 -*-
"""V5.2.4 front matter 解析与改写（A-01 修复：格式保真）。

纯 stdlib、离线。统一 front matter 的读取与改写语义：

- 分隔符同时接受 LF（``---\\n``）与 CRLF（``---\\r\\n``）；
- 可选 UTF-8 BOM（``\\ufeff---``）被捕获并记录，改写后按原样恢复；
- EOL 从 opening delimiter 显式捕获（修复单字段 CRLF 被误判为 LF 的缺陷）；
- closing delimiter 之后的正文字节语义原样保留（不使用 lstrip）；
- 改写只改 front matter 内的指定 key，正文不变。

设计依据：V5.2.4 AI-A 定向修复任务书 §6（front matter 格式保真）与审查报告 §3.5。
task_cmd._FM_RE 与 transaction_commit 的 front matter 读写均迁移到本模块。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# 顶层分隔 + body + 闭合分隔；body 非贪婪，DOTALL 跨行。
# 显式捕获：BOM、opening delimiter EOL、closing delimiter EOL、正文 rest。
# rest 为 closing delimiter 之后的原始内容（含开头空行，不做任何归一化）。
FRONTMATTER_RE = re.compile(
    r"\A(?P<bom>\ufeff)?---(?P<open_eol>\r\n|\n)(?P<body>.*?)(?P<pre_close_eol>\r\n|\n)"
    r"---(?P<close_eol>\r\n|\n)(?P<rest>.*)\Z",
    re.DOTALL,
)

# front matter 内顶层或嵌套 key 的替换模式：保留缩进与冒号前缀。
_KEY_RE = re.compile(r"(?m)^(\s*" + r"(?P<key>[A-Za-z0-9_.-]+)" + r"\s*:\s*).*?$")


class FrontMatterError(ValueError):
    """front matter 缺失、损坏或改写失败。"""


def _parse(text: str) -> Optional[re.Match]:
    """解析文本，返回 match 对象或 None。"""
    return FRONTMATTER_RE.match(text)


def split(text: str) -> Optional[Tuple[str, str, str]]:
    """解析文本，返回 (front_body, rest, eol)。

    - 无合法 front matter 返回 None；
    - front_body 不含首尾分隔行；rest 为 closing delimiter 后的正文（原样）；
    - eol 为 opening delimiter 的换行风格（显式捕获，不依赖 body 推断）。
    """
    m = _parse(text)
    if not m:
        return None
    return m.group("body"), m.group("rest"), m.group("open_eol")


def parse(text: str) -> Optional[Dict[str, str]]:
    """解析 front matter 为顶层 key -> value（仅首层，去引号去注释）。"""
    parts = split(text)
    if parts is None:
        return None
    front, _, _ = parts
    result: Dict[str, str] = {}
    for line in front.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith(" ") or line.startswith("\t"):
            continue  # 嵌套块不解析（任务书只要求可解析性，不做完整 YAML）
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        if key:
            result[key] = value
    return result


def has(text: str) -> bool:
    """是否存在合法 front matter（LF/CRLF/BOM 均可）。"""
    return _parse(text) is not None


def set_value(text: str, key: str, value: str) -> str:
    """在 front matter 中设置单个 key=value，返回新文本。

    格式保真：保留 BOM、opening/closing delimiter 原 EOL、正文 rest 原样
    （含开头空行，不使用 lstrip）；key 已存在则原位替换（保留缩进），
    不存在则追加到 front matter 末尾（用 opening EOL）。
    """
    m = _parse(text)
    if m is None:
        raise FrontMatterError("missing or invalid YAML front matter")
    bom = m.group("bom") or ""
    open_eol = m.group("open_eol")
    pre_close_eol = m.group("pre_close_eol")
    close_eol = m.group("close_eol")
    rest = m.group("rest")
    front = m.group("body")
    quote = '"' + _escape_yaml_quote(str(value)) + '"'
    pattern = re.compile(r"(?m)^(\s*" + re.escape(key) + r"\s*:\s*).*?$")
    if pattern.search(front):
        front = pattern.sub(lambda mm: mm.group(1) + quote, front, count=1)
    else:
        front = front + open_eol + key + ": " + quote
    return bom + "---" + open_eol + front + pre_close_eol + "---" + close_eol + rest


def set_values(text: str, values: Dict[str, str]) -> str:
    """批量设置多个 key=value（见 set_value）。"""
    for key, value in values.items():
        text = set_value(text, key, value)
    return text


def _escape_yaml_quote(value: str) -> str:
    """YAML 双引号字符串内转义（与旧实现一致的最小转义）。"""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def read(path: str) -> str:
    """读取文件文本（保留 BOM/CRLF 原样；供解析用）。

    注意用 utf-8 而非 utf-8-sig：BOM 必须以 \\\\ufeff 字符保留在文本中，
    供 set_value/has 识别并原样恢复。
    """
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def rewrite_file(path: str, values: Dict[str, str]) -> None:
    """读取文件、改写 front matter、原格式写回（不改正文）。"""
    text = read(path)
    new_text = set_values(text, values)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(new_text)
