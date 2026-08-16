# -*- coding: utf-8 -*-
"""TP-Spec-Coding V5.0 workflow.yaml 解析器（M1）。

不依赖 pyyaml，手写极简 YAML 解析器，只提取 workflow.yaml 的：
- version
- states: {STATE: {owner, name, description}}
- transitions: {STATE: [next states]}

提供：
- load_workflow(base_root) -> WorkflowDef（带缓存）
- WorkflowDef.is_valid_transition(from, to)
- WorkflowDef.get_state_owner(state)
- WorkflowDef.get_state_stage(state)
- WorkflowDef.is_terminal(state)
- WorkflowLoadError
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

# tp-spec-base 根目录
_BASE_ROOT = Path(__file__).resolve().parent.parent


class WorkflowLoadError(Exception):
    """workflow.yaml 加载或解析失败。"""


def _unquote(s: str) -> str:
    """去除 YAML 字符串的引号。"""
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def _preprocess_lines(text: str):
    """预处理 YAML 文本：去 BOM、去尾部空白、跳过空行和注释，返回 [(indent, content)]。"""
    result = []
    for line in text.splitlines():
        if line.startswith("\ufeff"):
            line = line[1:]
        stripped = line.rstrip()
        if not stripped or stripped.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        content = stripped.lstrip()
        result.append((indent, content))
    return result


def _parse_workflow_yaml(text: str) -> dict:
    """解析 workflow.yaml，提取 version/states/transitions/levels。"""
    result = {"version": "", "states": {}, "transitions": {}, "levels": {}}
    lines = _preprocess_lines(text)
    i = 0
    n = len(lines)
    while i < n:
        indent, content = lines[i]
        if indent == 0 and ":" in content:
            key, _, value = content.partition(":")
            key = key.strip()
            value = value.strip()
            if value:
                if key == "version":
                    result["version"] = _unquote(value)
                i += 1
            else:
                # 块
                if key == "states":
                    result["states"], i = _parse_states_block(lines, i + 1)
                elif key == "transitions":
                    result["transitions"], i = _parse_transitions_block(lines, i + 1)
                elif key == "levels":
                    result["levels"], i = _parse_levels_block(lines, i + 1)
                else:
                    # 跳过其他块（workflow/rules）
                    i = _skip_block(lines, i + 1, 0)
        else:
            i += 1
    return result


def _parse_levels_block(lines, idx):
    """解析 levels: 块，提取每个 Lx 的 completion_owner。

    结构：
      levels:
        L0:
          name: ...
          flow:
            - state: "COMPLETED"
              completion_owner: "tp-delivery-convergence"
          human_required: false

    返回 (levels_dict, next_idx)。
    levels_dict: {"L0": "tp-delivery-convergence", "L1": "tp-delivery-convergence", ...}
    """
    levels = {}
    if idx >= len(lines):
        return levels, idx
    block_indent = lines[idx][0]
    i = idx
    while i < len(lines):
        indent, content = lines[i]
        if indent < block_indent:
            break
        if indent > block_indent:
            # Lx 属性块内，由 Lx 循环处理；这里防止死循环
            i += 1
            continue
        # indent == block_indent: Lx 行（如 "L0:"）
        if content.endswith(":") and ":" not in content[:-1]:
            level_name = content[:-1].strip()
            i += 1
            # 遍历 Lx 属性块（indent > block_indent），扫描 completion_owner
            completion_owner = None
            while i < len(lines) and lines[i][0] > block_indent:
                _, p_content = lines[i]
                # completion_owner 可能在 flow 列表项的深层缩进里
                if "completion_owner:" in p_content:
                    parts = p_content.split("completion_owner:", 1)
                    if len(parts) == 2:
                        val = parts[1].strip()
                        completion_owner = _unquote(val)
                i += 1
            if completion_owner:
                levels[level_name] = completion_owner
        else:
            i += 1
    return levels, i


def _parse_states_block(lines, idx):
    """解析 states: 块。返回 (states_dict, next_idx)。

    state_name 行：indent == block_indent，content 形如 "STATE_NAME:"
    state 属性行：indent > block_indent，content 形如 "key: value"
    """
    states = {}
    if idx >= len(lines):
        return states, idx
    block_indent = lines[idx][0]
    i = idx
    while i < len(lines):
        indent, content = lines[i]
        if indent < block_indent:
            break
        if indent > block_indent:
            # 属性行，应该已被 state 解析循环处理；这里跳过防止死循环
            i += 1
            continue
        # indent == block_indent：state_name 行
        if content.endswith(":") and ":" not in content[:-1]:
            state_name = content[:-1].strip()
            state_info = {"owner": None, "name": None, "description": None}
            i += 1
            # 解析属性（indent > block_indent）
            if i < len(lines) and lines[i][0] > block_indent:
                prop_indent = lines[i][0]
                while i < len(lines) and lines[i][0] >= prop_indent:
                    p_indent, p_content = lines[i]
                    if p_indent == prop_indent and ":" in p_content:
                        key, _, value = p_content.partition(":")
                        key = key.strip()
                        value = value.strip()
                        if value:
                            state_info[key] = _unquote(value)
                            i += 1
                        else:
                            # 多行块（如 description: 列表），跳过子块
                            i += 1
                            while i < len(lines) and lines[i][0] > prop_indent:
                                i += 1
                    else:
                        i += 1
            states[state_name] = state_info
        else:
            i += 1
    return states, i


def _parse_transitions_block(lines, idx):
    """解析 transitions: 块。返回 (transitions_dict, next_idx)。

    结构：
      STATE_NAME:
        next:
          - NEXT_STATE1
          - NEXT_STATE2
    """
    transitions = {}
    if idx >= len(lines):
        return transitions, idx
    block_indent = lines[idx][0]
    i = idx
    while i < len(lines):
        indent, content = lines[i]
        if indent < block_indent:
            break
        if indent > block_indent:
            i += 1
            continue
        # indent == block_indent：state_name 行
        if content.endswith(":") and ":" not in content[:-1]:
            state_name = content[:-1].strip()
            i += 1
            next_states = []
            # 期望 next: 块（indent > block_indent）
            if i < len(lines) and lines[i][0] > block_indent:
                next_indent = lines[i][0]
                p_indent, p_content = lines[i]
                if p_indent == next_indent and p_content == "next:":
                    i += 1
                    # 列表项（indent > next_indent）
                    if i < len(lines) and lines[i][0] > next_indent:
                        item_indent = lines[i][0]
                        while i < len(lines) and lines[i][0] >= item_indent:
                            it_indent, it_content = lines[i]
                            if it_indent == item_indent and it_content.startswith("- "):
                                next_states.append(_unquote(it_content[2:].strip()))
                                i += 1
                            else:
                                i += 1
            transitions[state_name] = next_states
        else:
            i += 1
    return transitions, i


def _skip_block(lines, idx, parent_indent):
    """跳过缩进 > parent_indent 的块。"""
    i = idx
    while i < len(lines) and lines[i][0] > parent_indent:
        i += 1
    return i


class WorkflowDef:
    """workflow.yaml 解析结果。"""

    def __init__(self, version: str, states: Dict, transitions: Dict, levels: Dict):
        self.version = version
        self.states = states
        self.transitions = transitions
        self.levels = levels

    def is_valid_transition(self, from_state: str, to_state: str) -> bool:
        if from_state not in self.transitions:
            return False
        return to_state in self.transitions[from_state]

    def get_state_owner(self, state: str) -> Optional[str]:
        info = self.states.get(state)
        if info is None:
            return None
        return info.get("owner")

    def get_completion_owner(self, risk_level: Optional[str], flow_level: Optional[str]) -> Optional[str]:
        """获取 COMPLETED 状态的 completion_owner。

        优先级：risk_level 的 completion_owner，回退 flow_level，再回退 None。
        与 workflow.yaml levels.<Lx>.flow[COMPLETED].completion_owner 对齐：
          V5.2.3 各等级均为 tp-delivery-convergence
        """
        if risk_level and risk_level in self.levels:
            return self.levels[risk_level]
        if flow_level and flow_level in self.levels:
            return self.levels[flow_level]
        return None

    def get_state_stage(self, state: str) -> str:
        """V5.0: stage = state（简化，不强存独立 stage 概念）。"""
        return state

    def is_terminal(self, state: str) -> bool:
        """是否终态（COMPLETED/CANCELLED）。"""
        return state in ("COMPLETED", "CANCELLED")


# 模块级缓存
_WORKFLOW_CACHE: Dict[str, WorkflowDef] = {}


def load_workflow(base_root=None) -> WorkflowDef:
    """加载 workflow.yaml，结果缓存。"""
    cache_key = str(base_root) if base_root else "_default"
    if cache_key in _WORKFLOW_CACHE:
        return _WORKFLOW_CACHE[cache_key]
    root = Path(base_root) if base_root else _BASE_ROOT
    wf_path = root / "governance" / "workflow.yaml"
    if not wf_path.exists():
        raise WorkflowLoadError(f"workflow.yaml not found: {wf_path}")
    try:
        with open(wf_path, "r", encoding="utf-8") as f:
            text = f.read()
        data = _parse_workflow_yaml(text)
    except WorkflowLoadError:
        raise
    except Exception as e:
        raise WorkflowLoadError(f"failed to parse workflow.yaml: {e}")
    # Active governance stays intentionally small. Frozen legacy microstates are
    # merged only inside the Runtime decoder so historical ledgers remain parseable
    # without exposing the old process to roles.
    from .legacy_workflow import LEGACY_STATE_OWNERS, LEGACY_TRANSITIONS
    states = dict(data["states"])
    for state, owner in LEGACY_STATE_OWNERS.items():
        states.setdefault(state, {"owner": owner, "name": "legacy compatibility", "description": None})
    transitions = {k: list(v) for k, v in data["transitions"].items()}
    for state, next_states in LEGACY_TRANSITIONS.items():
        merged = transitions.setdefault(state, [])
        for target in next_states:
            if target not in merged:
                merged.append(target)
    wf = WorkflowDef(
        version=data["version"],
        states=states,
        transitions=transitions,
        levels=data.get("levels", {}),
    )
    # 基本校验
    if not wf.states:
        raise WorkflowLoadError("workflow.yaml: states block empty or missing")
    if not wf.transitions:
        raise WorkflowLoadError("workflow.yaml: transitions block empty or missing")
    _WORKFLOW_CACHE[cache_key] = wf
    return wf
