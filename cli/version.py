# -*- coding: utf-8 -*-
"""TP-Spec-Coding 单一版本来源（V5.2.5）。

所有活动运行常量统一从根目录 VERSION 文件动态读取，禁止散落硬编码版本号。
Python 侧入口：active_version()；PowerShell 侧由各脚本读取 VERSION 文件。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from .config_loader import read_base_version


def active_version(base_root: "Optional[Union[str, Path]]" = None) -> str:
    """读取当前唯一活动契约版本（VERSION 文件内容，strip 后返回）。"""
    return read_base_version(base_root)


def next_version(base_root: "Optional[Union[str, Path]]" = None) -> str:
    """根据当前版本计算下一 minor 版本（cutover 演练目标，不硬编码）。

    5.2.5 -> 5.3.0；5.3.0 -> 5.4.0。
    """
    cur = read_base_version(base_root)
    major, minor, _ = cur.split(".")
    return f"{major}.{int(minor) + 1}.0"
