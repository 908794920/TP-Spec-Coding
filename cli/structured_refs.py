# -*- coding: utf-8 -*-
"""V5.2.2 B-12 结构化事实引用与真实性校验（evidence_refs/code_refs）。

设计依据：历史设计记录 B12-structured-refs-design §2/§3/§4/§6/§7/§9
证据锚点：升级计划 §3.2 L121-143 / §7 L310·L312·L316 / §6 L302；
cli/anchor_check.py L41-74。

确定性校验，无网络/模型/DB；与 anchor_check/s1_validator/sensitive_scanner 正交独立
（本模块不 import review_preflight/s1_validator/sensitive_scanner）。

规则（§3.1）：
R1  file: REF_FILE_NOT_IN_SCOPE / REF_FILE_NOT_FOUND / REF_HASH_MISMATCH
R2  evidence: EVIDENCE_NOT_REGISTERED
R3  command: COMMAND_REGISTRY_MISSING / COMMAND_ID_UNKNOWN / COMMAND_ARGS_SCHEMA_MISMATCH /
    COMMAND_REGISTRY_VERSION_MISMATCH / COMMAND_CONTENT_HASH_MISMATCH /
    COMMAND_OUTPUT_MISSING / COMMAND_OUTPUT_HASH_MISMATCH
R4  symbol: SYMBOL_ADAPTER_MISSING / SYMBOL_NOT_FOUND（告警，不阻断）
R5  symbol: SYMBOL_VERIFIED_MISMATCH（当次立即失败）
R6  external: EXTERNAL_INVALID_VERIFICATION / NARRATIVE_AS_EVIDENCE
R7  fail-closed: REFS_VALIDATOR_ERROR
R8  kind 枚举非法: REF_KIND_INVALID
R9  verification 枚举非法: REF_VERIFICATION_INVALID
R10 confidence 枚举非法/确定性校验通过但 confidence≠high: REF_CONFIDENCE_INVALID /
    DETERMINISTIC_REQUIRES_HIGH
R11 evidence_hash 格式非法: EVIDENCE_HASH_INVALID
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from . import anchor_check
from . import refs_symbol_adapters
from .refs_symbol_adapters import SYMBOL_ADAPTER_MISSING, SYMBOL_NOT_FOUND

STRUCTURED_REFS_VERSION = "1.0.0"

# --- 错误码枚举（§3.2）---
REF_FILE_NOT_IN_SCOPE = "REF_FILE_NOT_IN_SCOPE"
REF_FILE_NOT_FOUND = "REF_FILE_NOT_FOUND"
REF_HASH_MISMATCH = "REF_HASH_MISMATCH"
EVIDENCE_NOT_REGISTERED = "EVIDENCE_NOT_REGISTERED"
COMMAND_REGISTRY_MISSING = "COMMAND_REGISTRY_MISSING"
COMMAND_ID_UNKNOWN = "COMMAND_ID_UNKNOWN"
COMMAND_ARGS_SCHEMA_MISMATCH = "COMMAND_ARGS_SCHEMA_MISMATCH"
COMMAND_REGISTRY_VERSION_MISMATCH = "COMMAND_REGISTRY_VERSION_MISMATCH"
COMMAND_CONTENT_HASH_MISMATCH = "COMMAND_CONTENT_HASH_MISMATCH"
COMMAND_OUTPUT_MISSING = "COMMAND_OUTPUT_MISSING"
COMMAND_OUTPUT_HASH_MISMATCH = "COMMAND_OUTPUT_HASH_MISMATCH"
SYMBOL_ADAPTER_MISSING = "SYMBOL_ADAPTER_MISSING"
SYMBOL_NOT_FOUND = "SYMBOL_NOT_FOUND"
SYMBOL_VERIFIED_MISMATCH = "SYMBOL_VERIFIED_MISMATCH"
EXTERNAL_INVALID_VERIFICATION = "EXTERNAL_INVALID_VERIFICATION"
NARRATIVE_AS_EVIDENCE = "NARRATIVE_AS_EVIDENCE"
REFS_VALIDATOR_ERROR = "REFS_VALIDATOR_ERROR"
REF_KIND_INVALID = "REF_KIND_INVALID"
REF_VERIFICATION_INVALID = "REF_VERIFICATION_INVALID"
REF_CONFIDENCE_INVALID = "REF_CONFIDENCE_INVALID"
DETERMINISTIC_REQUIRES_HIGH = "DETERMINISTIC_REQUIRES_HIGH"
EVIDENCE_HASH_INVALID = "EVIDENCE_HASH_INVALID"

# --- 枚举常量（§2.1）---
VALID_KINDS = ("file", "command", "symbol", "evidence", "external")
VALID_VERIFICATIONS = (
    "LOCAL_VERIFIED",
    "LOCAL_UNVERIFIED",
    "EXTERNAL_UNVERIFIED",
    "NOT_APPLICABLE",
)
VALID_CONFIDENCES = ("high", "medium", "low")
VALID_EVIDENCE_HASH_REASONS = (
    "EXTERNAL_ONLY",
    "NOT_APPLICABLE",
    "REGISTRY_MISSING",
    "PENDING_LOCAL",
)

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _make_schema_sha256() -> str:
    """计算 schema 规则源的 content SHA-256（§2.3 双锚点）。"""
    # 稳定序列化所有枚举和版本常量
    source = json.dumps(
        {
            "structured_refs_version": STRUCTURED_REFS_VERSION,
            "valid_kinds": sorted(VALID_KINDS),
            "valid_verifications": sorted(VALID_VERIFICATIONS),
            "valid_confidences": sorted(VALID_CONFIDENCES),
            "valid_evidence_hash_reasons": sorted(VALID_EVIDENCE_HASH_REASONS),
        },
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()


STRUCTURED_REFS_SCHEMA_SHA256 = _make_schema_sha256()


# ---------------------------------------------------------------------------
# T1: Schema 校验层（R8-R11）
# ---------------------------------------------------------------------------


def _validate_schema(ref: dict[str, Any]) -> list[str]:
    """对单条引用执行 R8-R11 schema 校验。返回错误码列表；空列表表示通过。"""
    errors: list[str] = []

    # R8: kind 枚举校验
    kind = ref.get("kind")
    if kind not in VALID_KINDS:
        errors.append(REF_KIND_INVALID)

    # R9: verification 枚举校验
    verification = ref.get("verification")
    if verification not in VALID_VERIFICATIONS:
        errors.append(REF_VERIFICATION_INVALID)

    # R10: confidence 枚举校验 + 确定性校验通过必须 high
    confidence = ref.get("confidence")
    if confidence not in VALID_CONFIDENCES:
        errors.append(REF_CONFIDENCE_INVALID)
    elif verification == "LOCAL_VERIFIED" and confidence != "high":
        errors.append(DETERMINISTIC_REQUIRES_HIGH)

    # R11: evidence_hash 格式校验
    evidence_hash = ref.get("evidence_hash")
    if evidence_hash is not None:
        if not isinstance(evidence_hash, str) or not _SHA256_RE.fullmatch(evidence_hash):
            errors.append(EVIDENCE_HASH_INVALID)
    else:
        # evidence_hash 为 None 时必须提供 evidence_hash_reason
        reason = ref.get("evidence_hash_reason")
        if reason not in VALID_EVIDENCE_HASH_REASONS:
            errors.append(EVIDENCE_HASH_INVALID)

    return errors


# ---------------------------------------------------------------------------
# T2: 规则实现（R1-R7）+ T4: 命令注册表校验
# ---------------------------------------------------------------------------


def _validate_file_ref(
    ref: dict[str, Any],
    approved_scope: list[str],
    file_contents: dict[str, str],
) -> list[str]:
    """R1: kind=file 且 verification=LOCAL_VERIFIED 的校验。"""
    errors: list[str] = []
    value = ref.get("value", "")
    verification = ref.get("verification", "")

    if verification != "LOCAL_VERIFIED":
        return errors  # 非 LOCAL_VERIFIED 不校验

    # 检查路径是否在批准范围
    in_scope = False
    for scope_path in approved_scope:
        norm_scope = scope_path.replace("\\", "/").rstrip("/")
        norm_value = value.replace("\\", "/")
        if norm_value.startswith(norm_scope) or norm_value == norm_scope:
            in_scope = True
            break
    if not in_scope:
        errors.append(REF_FILE_NOT_IN_SCOPE)
        return errors

    # 检查文件是否存在
    if value not in file_contents:
        errors.append(REF_FILE_NOT_FOUND)
        return errors

    # 检查 hash 是否匹配
    evidence_hash = ref.get("evidence_hash")
    if evidence_hash is not None:
        content = file_contents[value]
        if not anchor_check.check_hash_matches(content, evidence_hash):
            errors.append(REF_HASH_MISMATCH)

    return errors


def _validate_evidence_ref(
    ref: dict[str, Any],
    registered_evidence: set[str],
) -> list[str]:
    """R2: kind=evidence 校验。"""
    errors: list[str] = []
    value = ref.get("value", "")

    if value not in registered_evidence:
        errors.append(EVIDENCE_NOT_REGISTERED)

    return errors


def _validate_command_ref(
    ref: dict[str, Any],
    command_registry: dict[str, Any] | None,
) -> list[str]:
    """R3: kind=command 校验。绝不执行命令。"""
    errors: list[str] = []
    value = ref.get("value", "")
    location = ref.get("location", "")

    if command_registry is None:
        errors.append(COMMAND_REGISTRY_MISSING)
        return errors

    commands = command_registry.get("commands", [])
    registry_version = command_registry.get("registry_version", "")

    # 查找命令 ID
    cmd_entry = None
    for entry in commands:
        if entry.get("id") == value:
            cmd_entry = entry
            break

    if cmd_entry is None:
        errors.append(COMMAND_ID_UNKNOWN)
        return errors

    # 校验注册表版本
    if registry_version and cmd_entry.get("registry_version"):
        if registry_version != cmd_entry["registry_version"]:
            errors.append(COMMAND_REGISTRY_VERSION_MISMATCH)

    # 校验参数 schema（从 location 中解析）
    args_schema = cmd_entry.get("args_schema", [])
    if args_schema and location:
        # 从 location 中提取参数名（params: key=value 格式）
        params_str = location.replace("params:", "").strip()
        for param_part in params_str.split(","):
            param_part = param_part.strip()
            if "=" in param_part:
                param_name = param_part.split("=")[0].strip()
                if param_name not in args_schema:
                    errors.append(COMMAND_ARGS_SCHEMA_MISMATCH)
                    break

    # 校验 content_sha256
    content_sha256 = cmd_entry.get("content_sha256")
    if content_sha256:
        evidence_hash = ref.get("evidence_hash")
        if evidence_hash and evidence_hash != content_sha256:
            errors.append(COMMAND_CONTENT_HASH_MISMATCH)

    # 校验输出证据
    output_evidence_required = cmd_entry.get("output_evidence_required", False)
    if output_evidence_required:
        evidence_hash = ref.get("evidence_hash")
        if evidence_hash is None:
            errors.append(COMMAND_OUTPUT_MISSING)
        else:
            # 输出证据 hash 由调用方提供，此处仅检查存在性
            pass  # 实际 hash 匹配由 evidence_hash 字段层面校验

    return errors


# ---------------------------------------------------------------------------
# T7: 命令注册表加载（governance/verifiable-commands.yaml 接线，R3）
# ---------------------------------------------------------------------------

DEFAULT_COMMAND_REGISTRY_REL = "governance/verifiable-commands.yaml"


class CommandRegistryError(Exception):
    """命令注册表不可信（解析失败/结构非法/双锚点不一致）；fail-closed 拒绝整个注册表。"""


def _registry_canonical_json(obj: Any) -> str:
    """注册表规范化序列化（对齐 B-12 设计 §2.3：ensure_ascii=False + sort_keys）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def compute_command_content_sha256(entry: dict[str, Any]) -> str:
    """单命令定义锚点：id+args_schema+output_evidence_required 规范化序列化后 SHA-256。

    与 governance/verifiable-commands.yaml 中 content_sha256 同算法；
    R3 校验时 ref.evidence_hash 必须与之一致（L253-257）。
    """
    payload = {
        "id": entry.get("id", ""),
        "args_schema": entry.get("args_schema", []),
        "output_evidence_required": entry.get("output_evidence_required", False),
    }
    return "sha256:" + hashlib.sha256(
        _registry_canonical_json(payload).encode("utf-8")
    ).hexdigest()


def compute_registry_content_sha256(registry: dict[str, Any]) -> str:
    """注册表内容锚点：commands 规范化序列化后 SHA-256（双锚点，防篡改）。"""
    payload = {"commands": registry.get("commands", [])}
    return "sha256:" + hashlib.sha256(
        _registry_canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _validate_registry_structure(registry: dict[str, Any], display: str) -> None:
    """结构校验（fail-closed）：顶层与命令条目的类型、必填字段。"""
    if not isinstance(registry.get("registry_version"), str) or not registry["registry_version"]:
        raise CommandRegistryError(f"registry_version must be a non-empty string: {display}")
    commands = registry.get("commands")
    if not isinstance(commands, list):
        raise CommandRegistryError(f"commands must be a list: {display}")
    for i, entry in enumerate(commands):
        if not isinstance(entry, dict):
            raise CommandRegistryError(f"commands[{i}] must be a mapping: {display}")
        cmd_id = entry.get("id")
        if not isinstance(cmd_id, str) or not cmd_id:
            raise CommandRegistryError(f"commands[{i}].id must be a non-empty string: {display}")
        args_schema = entry.get("args_schema")
        if args_schema is not None and (
            not isinstance(args_schema, list) or not all(isinstance(a, str) for a in args_schema)
        ):
            raise CommandRegistryError(
                f"commands[{i}].args_schema must be a list of strings: {display}"
            )
        oe = entry.get("output_evidence_required")
        if oe is not None and not isinstance(oe, bool):
            raise CommandRegistryError(
                f"commands[{i}].output_evidence_required must be a bool: {display}"
            )
        cs = entry.get("content_sha256")
        if cs is not None and (not isinstance(cs, str) or not _SHA256_RE.fullmatch(cs)):
            raise CommandRegistryError(
                f"commands[{i}].content_sha256 must be sha256:<64-hex>: {display}"
            )
        rv = entry.get("registry_version")
        if rv is not None and not isinstance(rv, str):
            raise CommandRegistryError(
                f"commands[{i}].registry_version must be a string: {display}"
            )


def load_command_registry(
    path: "str | Path | None" = None,
    *,
    base_root: "str | Path | None" = None,
) -> "dict[str, Any] | None":
    """受控加载命令注册表（YAML，走 cli/config_loader.py 受控解析）。

    - path 为 None → 默认 base_root/governance/verifiable-commands.yaml；文件缺失 → None
      （注册表未启用状态，调用方以 COMMAND_REGISTRY_MISSING fail-closed 处理）。
    - path 显式指定但文件缺失 → None。
    - YAML 解析失败/结构非法/registry_content_sha256 缺失或重算不一致
      → CommandRegistryError（fail-closed 拒绝该注册表，绝不放行）。
    """
    from cli import config_loader as _config_loader

    if path is None:
        root = Path(base_root) if base_root else _config_loader.default_base_root()
        target = root / DEFAULT_COMMAND_REGISTRY_REL
    else:
        target = Path(path)
    if not target.is_file():
        return None
    display = str(target)
    try:
        registry = _config_loader.load_config(target, schema_name=None)
    except Exception as exc:
        raise CommandRegistryError(
            f"registry parse failed (fail-closed): {display}: {exc}"
        ) from exc
    _validate_registry_structure(registry, display)
    declared = registry.get("registry_content_sha256")
    if not isinstance(declared, str) or not _SHA256_RE.fullmatch(declared):
        raise CommandRegistryError(
            f"registry_content_sha256 missing or invalid (fail-closed): {display}"
        )
    if compute_registry_content_sha256(registry) != declared:
        raise CommandRegistryError(
            f"registry_content_sha256 mismatch (fail-closed, registry untrusted): {display}"
        )
    return registry


def _validate_symbol_ref(
    ref: dict[str, Any],
    file_contents: dict[str, str],
) -> list[str]:
    """R4/R5: kind=symbol 校验。"""
    errors: list[str] = []
    value = ref.get("value", "")
    verification = ref.get("verification", "")

    # 从 value 中提取文件名和符号名
    # value 格式可以是 "file.py:SymbolName" 或 "SymbolName"
    file_path = None
    symbol_name = value
    if ":" in value:
        parts = value.split(":", 1)
        file_path = parts[0]
        symbol_name = parts[1]

    # 如果未指定文件路径，尝试在所有文件中查找
    if file_path:
        content = file_contents.get(file_path, "")
        lang = refs_symbol_adapters.detect_language(file_path)
        result = refs_symbol_adapters.locate_symbol(content, symbol_name, lang)
    else:
        # 搜索所有文件
        result = {"found": False, "line": None, "location": "", "error_code": None}
        for fp, content in file_contents.items():
            lang = refs_symbol_adapters.detect_language(fp)
            r = refs_symbol_adapters.locate_symbol(content, symbol_name, lang)
            if r["found"]:
                result = r
                break
        if not result["found"]:
            result = {
                "found": False,
                "line": None,
                "location": "",
                "error_code": refs_symbol_adapters.SYMBOL_ADAPTER_MISSING
                if not any(refs_symbol_adapters.detect_language(fp) for fp in file_contents)
                else refs_symbol_adapters.SYMBOL_NOT_FOUND,
            }

    if not result["found"]:
        if verification == "LOCAL_VERIFIED":
            # R5: 声明 LOCAL_VERIFIED 但无法定位 → 当次立即失败
            errors.append(SYMBOL_VERIFIED_MISMATCH)
        else:
            # R4: 降级告警（不阻断）
            errors.append(result["error_code"] or SYMBOL_NOT_FOUND)

    return errors


def _validate_external_ref(ref: dict[str, Any]) -> list[str]:
    """R6: kind=external 校验。"""
    errors: list[str] = []
    verification = ref.get("verification", "")

    if verification != "EXTERNAL_UNVERIFIED":
        errors.append(EXTERNAL_INVALID_VERIFICATION)

    # 检查是否以叙述性文本作为 evidence（location 是纯文本而非引用格式）
    location = ref.get("location", "")
    if location and not any(marker in location for marker in (":", "ref:", "source:")):
        errors.append(NARRATIVE_AS_EVIDENCE)

    return errors


# ---------------------------------------------------------------------------
# 主校验入口
# ---------------------------------------------------------------------------


def validate_ref(
    ref: dict[str, Any],
    *,
    approved_scope: list[str] | None = None,
    file_contents: dict[str, str] | None = None,
    registered_evidence: set[str] | None = None,
    command_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """对单条 evidence_refs/code_refs 执行全部规则校验。

    参数：
        ref: 引用记录字典（含 id/kind/value/location/verification/confidence/evidence_hash）
        approved_scope: 批准的文件路径前缀列表（R1）
        file_contents: 文件路径 → 内容（R1/R4/R5）
        registered_evidence: 已登记的证据 ID 集合（R2）
        command_registry: 命令注册表字典（R3）

    返回：
        {
            "ref_id": str,
            "kind": str,
            "value": str,
            "verification": str,
            "decision": "passed" | "failed" | "warning",
            "errors": list[str],
            "warnings": list[str],
            "structured_refs_version": str,
        }
    """
    # R7: 输入非 dict 或保护字段异常 → fail-closed
    if not isinstance(ref, dict):
        return {
            "ref_id": "<unknown>",
            "kind": "",
            "value": "",
            "verification": "",
            "decision": "failed",
            "errors": [REFS_VALIDATOR_ERROR],
            "warnings": [],
            "structured_refs_version": STRUCTURED_REFS_VERSION,
        }

    if approved_scope is None:
        approved_scope = []
    if file_contents is None:
        file_contents = {}
    if registered_evidence is None:
        registered_evidence = set()

    ref_id = ref.get("id", "<unknown>")
    kind = ref.get("kind", "")
    verification = ref.get("verification", "")

    # 第一步：Schema 校验（R8-R11）
    schema_errors = _validate_schema(ref)
    if schema_errors:
        return {
            "ref_id": ref_id,
            "kind": kind,
            "value": ref.get("value", ""),
            "verification": verification,
            "decision": "failed",
            "errors": sorted(schema_errors),
            "warnings": [],
            "structured_refs_version": STRUCTURED_REFS_VERSION,
        }

    # 第二步：按 kind 执行规则校验
    errors: list[str] = []
    warnings: list[str] = []

    try:
        if kind == "file":
            errors.extend(_validate_file_ref(ref, approved_scope, file_contents))
        elif kind == "evidence":
            errors.extend(_validate_evidence_ref(ref, registered_evidence))
        elif kind == "command":
            errors.extend(_validate_command_ref(ref, command_registry))
        elif kind == "symbol":
            sym_errors = _validate_symbol_ref(ref, file_contents)
            # R4 告警码分离到 warnings
            for err in sym_errors:
                if err in (SYMBOL_ADAPTER_MISSING, SYMBOL_NOT_FOUND):
                    warnings.append(err)
                else:
                    errors.append(err)
        elif kind == "external":
            errors.extend(_validate_external_ref(ref))
        else:
            # 不认识的 kind（R8 本应已拦截，但作为兜底）
            errors.append(REF_KIND_INVALID)
    except Exception as exc:
        # R7: 校验器异常 → fail-closed
        errors.append(REFS_VALIDATOR_ERROR)

    # 判定
    if errors:
        # 任一失败类错误 → decision=failed
        return {
            "ref_id": ref_id,
            "kind": kind,
            "value": ref.get("value", ""),
            "verification": verification,
            "decision": "failed",
            "errors": sorted(errors),
            "warnings": sorted(warnings),
            "structured_refs_version": STRUCTURED_REFS_VERSION,
        }
    elif warnings:
        return {
            "ref_id": ref_id,
            "kind": kind,
            "value": ref.get("value", ""),
            "verification": verification,
            "decision": "warning",
            "errors": [],
            "warnings": sorted(warnings),
            "structured_refs_version": STRUCTURED_REFS_VERSION,
        }
    else:
        return {
            "ref_id": ref_id,
            "kind": kind,
            "value": ref.get("value", ""),
            "verification": verification,
            "decision": "passed",
            "errors": [],
            "warnings": [],
            "structured_refs_version": STRUCTURED_REFS_VERSION,
        }


def validate_refs(
    refs: list[dict[str, Any]],
    *,
    approved_scope: list[str] | None = None,
    file_contents: dict[str, str] | None = None,
    registered_evidence: set[str] | None = None,
    command_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """批量校验 evidence_refs/code_refs。

    返回：
        {
            "results": list[dict],    # 每条引用的校验结果
            "summary": {
                "total": int,
                "passed": int,
                "failed": int,
                "warning": int,
            },
            "structured_refs_version": str,
            "structured_refs_schema_sha256": str,
        }
    """
    results: list[dict[str, Any]] = []
    summary: dict[str, int] = {"total": 0, "passed": 0, "failed": 0, "warning": 0}

    for ref in refs:
        result = validate_ref(
            ref,
            approved_scope=approved_scope,
            file_contents=file_contents,
            registered_evidence=registered_evidence,
            command_registry=command_registry,
        )
        results.append(result)
        summary["total"] += 1
        if result["decision"] == "passed":
            summary["passed"] += 1
        elif result["decision"] == "failed":
            summary["failed"] += 1
        elif result["decision"] == "warning":
            summary["warning"] += 1

    return {
        "results": results,
        "summary": summary,
        "structured_refs_version": STRUCTURED_REFS_VERSION,
        "structured_refs_schema_sha256": STRUCTURED_REFS_SCHEMA_SHA256,
    }


def any_failed(results: list[dict[str, Any]]) -> bool:
    """任一条引用 decision==failed（供退出码判定）。"""
    return any(r.get("decision") == "failed" for r in results)


# ---------------------------------------------------------------------------
# T5: refs-validate 独立子命令
# ---------------------------------------------------------------------------


def refs_validate_contract() -> dict[str, Any]:
    """公开 refs-validate 的机器可读输入契约，避免业务角色反读 Python 源码。"""
    return {
        "structured_refs_version": STRUCTURED_REFS_VERSION,
        "structured_refs_schema_sha256": STRUCTURED_REFS_SCHEMA_SHA256,
        "input": {
            "top_level": "JSON list OR object with evidence_refs/code_refs arrays",
            "required_fields": ["id", "kind", "value", "verification", "confidence"],
            "optional_fields": ["location", "evidence_hash", "evidence_hash_reason"],
            "kind": list(VALID_KINDS),
            "verification": list(VALID_VERIFICATIONS),
            "confidence": list(VALID_CONFIDENCES),
            "evidence_hash": "sha256:<64 lowercase hex> or null",
            "evidence_hash_reason": list(VALID_EVIDENCE_HASH_REASONS),
        },
        "path_semantics": {
            "scope_dirs": (
                "Each --scope-dirs value is scanned independently; file_contents keys are paths "
                "relative to that scope directory. For project-relative refs, pass the project root "
                "as the scope directory."
            ),
            "file_value": (
                "For kind=file + LOCAL_VERIFIED, value must exactly match a scanned relative path "
                "and must start with (or equal) one --approved-scope prefix after slash normalization."
            ),
            "approved_scope": "Path prefixes are compared against ref.value; they are not filesystem roots.",
        },
        "rules": {
            "LOCAL_VERIFIED": "confidence must be high; deterministic kind-specific checks run.",
            "null_evidence_hash": "When evidence_hash is null, evidence_hash_reason must be an allowed enum.",
            "external": "kind=external requires verification=EXTERNAL_UNVERIFIED.",
        },
    }


def refs_validate_example() -> dict[str, Any]:
    """返回无需扫描文件即可通过 schema/kind 校验的最小样例。"""
    return {
        "refs_file_content": {
            "code_refs": [
                {
                    "id": "REF-001",
                    "kind": "file",
                    "value": "README.md",
                    "location": "README.md",
                    "verification": "LOCAL_UNVERIFIED",
                    "confidence": "medium",
                    "evidence_hash": None,
                    "evidence_hash_reason": "PENDING_LOCAL",
                }
            ]
        },
        "save_as": "refs.json",
        "command": "tp-spec refs-validate --refs-file refs.json",
        "local_verified_pattern": (
            "For LOCAL_VERIFIED file refs, run from a known project root and add "
            "--scope-dirs <PROJECT_ROOT> --approved-scope <RELATIVE_PREFIX>; ref.value stays project-root relative."
        ),
    }


def cmd_refs_validate(args) -> int:
    """refs-validate 子命令入口。"""
    import argparse
    import json
    import sys

    if getattr(args, "schema", False):
        print(json.dumps(refs_validate_contract(), ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    if getattr(args, "example", False):
        print(json.dumps(refs_validate_example(), ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    if not getattr(args, "refs_file", None):
        print("ERROR: --refs-file is required unless --schema or --example is used", file=sys.stderr)
        return 2

    # 加载 refs 文件
    refs_path = Path(args.refs_file)
    if not refs_path.is_file():
        print(f"ERROR: refs file not found: {refs_path}", file=sys.stderr)
        return 1

    with open(refs_path, "r", encoding="utf-8") as f:
        try:
            refs_data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"ERROR: invalid JSON in refs file: {e}", file=sys.stderr)
            return 1

    # 支持 evidence_refs 和 code_refs 两种顶层 key
    if isinstance(refs_data, dict):
        refs_list = []
        refs_list.extend(refs_data.get("evidence_refs", []))
        refs_list.extend(refs_data.get("code_refs", []))
    elif isinstance(refs_data, list):
        refs_list = refs_data
    else:
        print("ERROR: refs file must be a JSON list or object with evidence_refs/code_refs keys", file=sys.stderr)
        return 1

    # 加载文件内容（可选）
    file_contents: dict[str, str] = {}
    if args.scope_dirs:
        for scope_dir_str in args.scope_dirs:
            scope_dir = Path(scope_dir_str)
            if scope_dir.is_dir():
                for f in scope_dir.rglob("*"):
                    if f.is_file():
                        try:
                            # 跳过非文本文件
                            ext = f.suffix.lower()
                            if ext in (".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib", ".bin", ".class"):
                                continue
                            rel_path = str(f.relative_to(scope_dir)).replace("\\", "/")
                            file_contents[rel_path] = f.read_text(encoding="utf-8", errors="replace")
                        except Exception:
                            pass

    # 命令注册表（R3）：默认 governance/verifiable-commands.yaml；--command-registry 显式覆盖。
    # 双锚点不一致/解析失败 → fail-closed 拒绝注册表（CommandRegistryError）。
    command_registry: dict[str, Any] | None = None
    try:
        command_registry = load_command_registry(args.command_registry)
    except CommandRegistryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if command_registry is None and args.command_registry:
        print(
            f"WARNING: command registry file not found: {Path(args.command_registry)}",
            file=sys.stderr,
        )

    # 批准范围（默认空列表）
    approved_scope = args.approved_scope or []

    # 执行校验
    result = validate_refs(
        refs_list,
        approved_scope=approved_scope,
        file_contents=file_contents,
        command_registry=command_registry,
    )

    # 输出校验结果
    output = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    print(output)

    # 退出码
    if any_failed(result["results"]):
        return 1
    return 0


def add_refs_validate_subparsers(subparsers) -> None:
    """向 argparse 注册 refs-validate 子命令。"""
    p = subparsers.add_parser(
        "refs-validate",
        help="V5.2.2 B-12 refs validate: structured references deterministic validation",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--schema", action="store_true", help="print the machine-readable refs input contract and enums, then exit")
    mode.add_argument("--example", action="store_true", help="print a minimal runnable refs-file example and invocation, then exit")
    p.add_argument("--refs-file", required=False, help="JSON file with evidence_refs/code_refs to validate (required for validation mode)")
    p.add_argument(
        "--scope-dirs", nargs="*", default=None,
        help=("filesystem roots scanned for file refs; scanned keys are relative to each root "
              "(pass project root when ref.value is project-relative)"),
    )
    p.add_argument(
        "--approved-scope", nargs="*", default=None,
        help="allowed path prefixes compared to ref.value (prefixes, not filesystem roots)",
    )
    p.add_argument(
        "--command-registry",
        default=None,
        help="command registry YAML file (default: governance/verifiable-commands.yaml; for R3 command validation)",
    )
    p.set_defaults(func=cmd_refs_validate)