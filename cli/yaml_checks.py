# -*- coding: utf-8 -*-
"""V5.2.1 fail-closed YAML 解析与工件结构校验（Hardening P0-3/P1-4）。

依据：《V5.2.1 执行AI统一修复与自验证任务》§9.1（使用真实 YAML 解析，禁止仅正则）
与《V5.2.1 源码级发布审查报告》P1-4（deferred_acceptance 仍使用正则）。

设计：
- ``parse_yaml_fail_closed(text, name)``：真实 YAML 解析（pyyaml 可用时），
  重复 key / 错误缩进 / 类型错误 / 非 mapping 一律抛 ``YamlValidationError``（fail-closed）；
  pyyaml 不可用时抛错（绝不静默放行）。
- ``check_acceptance_yaml(text)``：解析 acceptance.md 正文 YAML 块，返回
  ``AcceptanceCheckResult``：
  - deferred_acceptance 结构校验（list、每项含 ac/recorded_at/residual_risk/
    reverify_owner/trigger，缺失或空值即失败）；
  - page_verification 校验（mode=human 时 human_witness 必须 confirmed）；
  - 强制 AC 无 PENDING/BLOCKED。
- ``validate_frontmatter_yaml(text, name)``：工件 front matter 真实解析校验。

commit_cmd / transition_service / PowerShell validator 共用本模块，保证
"accepted" 与 "rejected" 的判定在 Python 与 PowerShell 两侧语义一致。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import frontmatter


class YamlDuplicateKeyError(ValueError):
    pass


class YamlValidationError(ValueError):
    pass


def _strict_yaml_loader():
    """pyyaml SafeLoader + 重复 key fail-closed。"""
    import yaml

    class _StrictLoader(yaml.SafeLoader):
        pass

    def _construct_mapping(loader, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise YamlDuplicateKeyError(f"duplicate YAML key: {key!r}")
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    _StrictLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
    )
    return _StrictLoader


def parse_yaml_fail_closed(text: str, name: str) -> Dict[str, Any]:
    """解析任意 YAML 文本为 dict；失败/非 mapping/重复 key 一律抛 YamlValidationError。"""
    try:
        import yaml  # type: ignore
    except ImportError:
        raise YamlValidationError(f"{name}: pyyaml unavailable; fail-closed (refusing to accept)")
    try:
        loader = _strict_yaml_loader()
        data = yaml.load(text, Loader=loader)
    except YamlDuplicateKeyError as e:
        raise YamlValidationError(f"{name}: {e}")
    except Exception as e:
        raise YamlValidationError(f"{name}: YAML not parseable: {e}")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise YamlValidationError(f"{name}: YAML must be a mapping")
    return data


def parse_frontmatter_yaml(text: str, name: str) -> Dict[str, Any]:
    """解析 front matter 为 dict；缺失/损坏/重复 key/非 mapping 一律抛 YamlValidationError。"""
    parts = frontmatter.split(text)
    if parts is None:
        raise YamlValidationError(f"{name}: missing or invalid YAML front matter")
    front, _, _ = parts
    return parse_yaml_fail_closed(front, name)


def validate_frontmatter_yaml(text: str, name: str) -> None:
    """仅校验 front matter 可解析（不返回数据）。失败抛 YamlValidationError。"""
    parse_frontmatter_yaml(text, name)


# =============================================================================
# acceptance.md 结构校验（§8.2 / P1-4）
# =============================================================================

_DEFERRED_REQUIRED_FIELDS = (
    "ac", "recorded_at", "residual_risk", "reverify_owner", "trigger",
)
_OWNER_WAIVER_REQUIRED_FIELDS = (
    "ac", "recorded_at", "reason", "residual_risk", "actor",
)

# Final Hardening（Task 4 §6.2 / P0-6）：唯一合法 verdict 枚举。
# 拒绝 PASSED/DONE/OK/YES 等历史别名；允许 "PASS：说明" 后缀。
VERDICT_ENUM = (
    "PASS", "NOT_REQUIRED", "N/A", "PENDING", "BLOCKED", "DEFERRED_ACCEPTED", "OWNER_WAIVED",
)


def normalize_verdict(raw: str) -> str:
    """取结论列的规范 verdict（去掉说明后缀并大写）；非法值原样返回（由调用方拒绝）。"""
    value = str(raw or "").strip().split("：")[0].split(":")[0].strip().upper()
    if value in VERDICT_ENUM:
        return value
    return str(raw or "").strip()


@dataclass
class AcceptanceCheckResult:
    ok: bool = True
    issues: List[str] = field(default_factory=list)
    pending_rows: List[str] = field(default_factory=list)
    deferred_entries: List[Dict[str, Any]] = field(default_factory=list)
    owner_waiver_entries: List[Dict[str, Any]] = field(default_factory=list)
    human_rows: List[Dict[str, str]] = field(default_factory=list)
    no_acceptance_required: Optional[Dict[str, Any]] = None

    @property
    def error_codes(self) -> List[str]:
        return ["ACCEPTANCE_PENDING" if self.pending_rows else "YAML_INVALID"]


def check_acceptance_yaml(text: str, *, enforce_completion: bool = True, allow_human_pending: bool = False) -> AcceptanceCheckResult:
    """校验 acceptance.md 正文 YAML 块 + 验收表格结论列。

    Final Hardening（Task 4 §6.2 / P0-3 / P0-6）：
    - 结论列 verdict 必须是唯一枚举（PASS/NOT_REQUIRED/N/A/PENDING/BLOCKED/
      DEFERRED_ACCEPTED/OWNER_WAIVED），拒绝 PASSED/DONE/OK/YES；
    - 每个 AC 行的验收条件不得为空；
    - verdict=PASS 的 AC 行必须存在证据路径；
    - PENDING/BLOCKED 行在结单时拒绝。
    """
    result = AcceptanceCheckResult()
    ac_row_count = 0

    # 1) 验收表格结论列：verdict 枚举 + PENDING/BLOCKED 拒绝 + PASS 证据
    for line in text.splitlines():
        m = re.match(r"^\s*\|\s*(AC-[^|\s]+)\s*\|", line)
        if not m:
            continue
        ac_row_count += 1
        cells = [c.strip() for c in line.split("|")]
        if len(cells) > 8:
            verdict = normalize_verdict(cells[8])
            condition = cells[2]
            evidence_path = cells[6]
            witness_level = cells[7].strip().lower() if len(cells) > 7 else ""
            if witness_level == "human":
                result.human_rows.append({"ac": m.group(1), "verdict": verdict, "evidence": evidence_path})
            if not condition:
                result.ok = False
                result.issues.append(f"acceptance AC {m.group(1)} has empty acceptance condition")
            if verdict not in VERDICT_ENUM:
                result.ok = False
                result.issues.append(
                    f"acceptance AC {m.group(1)} invalid verdict {cells[8]!r} "
                    f"(must be one of {', '.join(VERDICT_ENUM)})"
                )
                continue
            if verdict in ("PENDING", "BLOCKED"):
                if not (allow_human_pending and witness_level == "human" and verdict == "PENDING"):
                    result.pending_rows.append(f"{m.group(1)}:{cells[8].strip()}")
            if verdict == "PASS" and not evidence_path:
                result.ok = False
                result.issues.append(
                    f"acceptance AC {m.group(1)} PASS requires non-empty evidence path"
                )
    if result.pending_rows and enforce_completion:
        result.ok = False
        result.issues.append("acceptance has PENDING/BLOCKED entries: " + ", ".join(result.pending_rows[:5]))
    # Final Hardening（P0-3 根因一）：存在 AC 行时必须至少一个真实验收条件
    has_valid_condition = any(
        (lambda _c: len(_c) > 8 and _c[2])([c.strip() for c in line.split("|")])
        for line in text.splitlines() if re.match(r"^\s*\|\s*(AC-[^|\s]+)\s*\|", line)
    )
    if ac_row_count and not has_valid_condition:
        result.ok = False
        result.issues.append("acceptance must contain at least one AC row with a non-empty acceptance condition")
    # 2) 正文 YAML 块真实解析（page_verification / deferred_acceptance /
    # database_verification / no_acceptance_required）。
    # Fourth Hardening（P1-1）：no_acceptance_required 豁免声明必须在本节解析完成
    # 后（即顺序②在③之后），才能基于最终值做零 AC 二选一判定；避免"合法声明
    # 未解析就触发零 AC 错误"。见函数末尾。
    yaml_blocks = re.findall(r"```yaml\s*\n(.*?)```", text, re.DOTALL)
    parsed_any = False
    for block in yaml_blocks:
        try:
            data = parse_yaml_fail_closed(block, "acceptance.md")
        except YamlValidationError as e:
            result.ok = False
            result.issues.append(str(e))
            continue
        parsed_any = True
        # page_verification
        pv = data.get("page_verification")
        if isinstance(pv, dict):
            mode = pv.get("mode")
            if enforce_completion and mode == "human":
                human_pass = any(r.get("verdict") == "PASS" for r in result.human_rows)
                if human_pass and pv.get("human_witness") != "confirmed":
                    result.ok = False
                    result.issues.append("page_verification mode=human requires human_witness=confirmed for human PASS rows; deferred/waived rows do not require witness")
        # deferred_acceptance
        deferred = data.get("deferred_acceptance")
        if deferred is not None:
            if not isinstance(deferred, list):
                result.ok = False
                result.issues.append("deferred_acceptance must be a list")
            else:
                for item in deferred:
                    if not isinstance(item, dict):
                        result.ok = False
                        result.issues.append("deferred_acceptance item must be a mapping")
                        continue
                    for req in _DEFERRED_REQUIRED_FIELDS:
                        if req not in item or item.get(req) in (None, ""):
                            result.ok = False
                            result.issues.append(f"deferred_acceptance item missing required field: {req}")
                    result.deferred_entries.append(item)
        # owner_waivers: explicit human_owner skip; never represented as PASS.
        waivers = data.get("owner_waivers")
        if waivers is not None:
            if not isinstance(waivers, list):
                result.ok = False
                result.issues.append("owner_waivers must be a list")
            else:
                for item in waivers:
                    if not isinstance(item, dict):
                        result.ok = False
                        result.issues.append("owner_waivers item must be a mapping")
                        continue
                    for req in _OWNER_WAIVER_REQUIRED_FIELDS:
                        if req not in item or item.get(req) in (None, ""):
                            result.ok = False
                            result.issues.append(f"owner_waivers item missing required field: {req}")
                    if str(item.get("actor") or "") != "human_owner":
                        result.ok = False
                        result.issues.append("owner_waivers item actor must be human_owner")
                    result.owner_waiver_entries.append(item)
        # database_verification DML 强制
        dv = data.get("database_verification")
        if enforce_completion and isinstance(dv, dict) and dv.get("action") == "DML":
            if dv.get("dml_execution") != "passed":
                result.ok = False
                result.issues.append("database_verification action=DML requires dml_execution=passed")
        # Third Hardening（P0-3）：no_acceptance_required 机器可读豁免声明
        nar = data.get("no_acceptance_required")
        if nar is not None:
            if not isinstance(nar, dict):
                result.ok = False
                result.issues.append("no_acceptance_required must be a mapping")
            else:
                required = ("reason",)
                missing = [k for k in required if not nar.get(k)]
                if nar.get("declared") is not True:
                    result.ok = False
                    result.issues.append("no_acceptance_required.declared must be true")
                if missing:
                    result.ok = False
                    result.issues.append("no_acceptance_required missing fields: " + ", ".join(missing))
                if nar.get("declared") is True and not missing:
                    result.no_acceptance_required = nar
    if not parsed_any:
        # 模板中 deferred_acceptance: [] 可能存在；无 YAML 块时仅表格判定生效。
        # 不将"无 YAML 块"视为错误（旧模板可省略），deferred 语义由表格 DEFERRED_ACCEPTED 兜底。
        pass
    # Fourth Hardening（P1-1）：零 AC fail-closed 判定必须在正文 YAML 块解析
    # 之后执行——此时 result.no_acceptance_required 已反映真实声明：
    #   · 有 AC 行        → 正常验证（上述表格校验生效）；
    #   · 无 AC 行+合法声明 → 直接按个人模式机器声明放行；
    #   · 无 AC 行+无声明   → 拒绝（fail-closed）。
    if ac_row_count == 0 and result.no_acceptance_required is None:
        result.ok = False
        result.issues.append(
            "acceptance.md has no acceptance criteria (AC) rows and no valid "
            "no_acceptance_required declaration (machine-readable schema required)"
        )
    return result
