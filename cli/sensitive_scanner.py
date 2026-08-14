# -*- coding: utf-8 -*-
"""V5.2.1 9.5-1 敏感信息扫描器（确定性路径/内容模式扫描）。

设计依据：历史设计记录 sensitive-scan
证据锚点：评审表 9.5 第 1 行（L346）；升级计划 §3.1（L115-116）。

核心原则：
- 纯确定性：路径/内容模式扫描，不引入 LLM 启发式判断。
- fail-closed：未登记、规则异常、扫描器失败一律按"命中"处理。
- 与 B-16 provenance/sensitivity 双轴正交：扫描结果独立记录，不合并为单一污点字段。
- 规则版本化 + 内容哈希双锚点（scanner_version + scanner_sha256）。
- 不记录真实凭证：规则文件只含模式类别与脱敏形态。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from typing import Any


# =============================================================================
# 扫描器版本与双锚点
# =============================================================================
_SCANNER_VERSION = "1.0.0"

# 规则源（用于计算 scanner_sha256 内容哈希锚点）
_RULES_SOURCE = json.dumps(
    {
        "path_patterns": {
            "env_file": r"\.env(?:\.\w+)?$",
            # F4 收敛：仅匹配独立路径段/文件名边界（^、/、. 为左边界），
            # 避免 mycredentials.json / mysecrets.txt 等子串误伤（设计 §4）
            "credential_file": r"(?:^|[./])credentials[\w.-]*$",
            "secrets_file": r"(?:^|[./])secrets[\w.-]*$",
            "private_key": r"(?:id_rsa|id_ed25519|id_ecdsa|id_ed448)$",
            "pem_cert": r"\.pem$",
            "key_file": r"\.key$",
            "p12_pfx": r"\.(?:p12|pfx)$",
            "jks": r"\.jks$",
            "connection_string": r"\.(?:connectionstring|connstr)[\w.-]*$",
            "datasource": r"datasource\.[\w.-]*$",
            "token_file": r"\.token$|token\.json$",
            "npmrc": r"\.npmrc$",
            "pypirc": r"\.pypirc$",
            "aws_cred": r"\.aws/credentials$",
            "ssh_dir": r"(?:^|/)\.ssh/",
            "secrets_dir": r"(?:^|/)secrets/",
            "credentials_dir": r"(?:^|/)credentials/",
            "keystore_dir": r"(?:^|/)keystore/",
        },
        "content_patterns": {
            "bearer_token": r"Authorization:\s*Bearer\s+\S{20,}",
            "api_key_prefix": r"\b(?:sk-|pk-|ak-)\S{20,}",
            "aws_akid": r"AKIA[0-9A-Z]{16}",
            "aws_secret_key": r"aws_secret_access_key\s*=\s*\S+",
            "private_key_block": r"-----BEGIN\s+(?:RSA|EC|OPENSSH)\s+PRIVATE\s+KEY-----",
            "db_conn_string": r"(?:mysql|postgres)://[^:]+:[^@]+@",
            "jdbc_url": r"jdbc:\w+://[^:]+:[^@]+@",
            "mongodb_conn": r"mongodb://[^:]+:[^@]+@",
            "password_keyword": r"\b(?:password|passwd|pwd|secret|token|apikey|api_key)\s*[:=]\s*['\"]?\S{8,}",
            # F1：内网地址。作为 scan_content 规则统一生效；具体调用面由 receipt/review-preflight 等上层决定。
            # 私有网段四段 IP（10/8、172.16-31/12、192.168/16）+ 内网主机名（*.internal/*.local）
            "private_ipv4": r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b",
            "internal_hostname": r"\b[\w-]+\.(?:internal|local)\b",
        },
    },
    sort_keys=True,
)
_SCANNER_SHA256 = "sha256:" + hashlib.sha256(_RULES_SOURCE.encode("utf-8")).hexdigest()


# =============================================================================
# 敏感路径模式（编译后的正则）
# =============================================================================
# 从脱敏形态名称到编译正则的映射
_SENSITIVE_PATH_RE: dict[str, re.Pattern] = {}
for name, pat in json.loads(_RULES_SOURCE)["path_patterns"].items():
    _SENSITIVE_PATH_RE[name] = re.compile(pat, re.IGNORECASE)

# 敏感内容模式
_SENSITIVE_CONTENT_RE: dict[str, re.Pattern] = {}
for name, pat in json.loads(_RULES_SOURCE)["content_patterns"].items():
    _SENSITIVE_CONTENT_RE[name] = re.compile(pat)


# =============================================================================
# 扫描结果常量
# =============================================================================
_SCAN_STATUS_CLEAN = "clean"
_SCAN_STATUS_HIT = "hit"
_SCAN_STATUS_ERROR = "error"


def scan_resource_ref(resource_ref: str | None) -> dict[str, Any]:
    """对 resource_ref（文件路径/引用）做敏感路径模式扫描。

    返回：
    {
        "scanner_version": "1.0.0",
        "scanner_sha256": "sha256:...",
        "scan_status": "clean" | "hit" | "error",
        "hits": [{"category": "env_file", "pattern": "\\\\.env", "type": "path"}, ...]
    }

    与 B-16 provenance/sensitivity 双轴正交：扫描结果独立记录，不合并为单一污点字段。
    """
    result: dict[str, Any] = {
        "scanner_version": _SCANNER_VERSION,
        "scanner_sha256": _SCANNER_SHA256,
        "scan_status": _SCAN_STATUS_CLEAN,
        "hits": [],
    }
    if resource_ref is None or not resource_ref.strip():
        return result  # 无引用，清空

    ref = resource_ref.strip()
    try:
        for category, pattern in _SENSITIVE_PATH_RE.items():
            if pattern.search(ref):
                result["hits"].append({
                    "category": category,
                    "pattern": pattern.pattern,
                    "type": "path",
                })
        if result["hits"]:
            result["scan_status"] = _SCAN_STATUS_HIT
    except Exception as exc:
        # fail-closed：扫描器异常按错误处理
        result["scan_status"] = _SCAN_STATUS_ERROR
        print(f"WARNING: sensitive scanner error on resource_ref: {type(exc).__name__}: {exc}", file=sys.stderr)

    return result


def scan_content(content: str | None) -> dict[str, Any]:
    """对文件内容做敏感内容模式扫描。

    返回结构同 scan_resource_ref，但 hits 的 type 为 "content"。
    命中敏感内容时**不得复制原文**，仅记录类别与模式（升级计划 L116）。
    """
    result: dict[str, Any] = {
        "scanner_version": _SCANNER_VERSION,
        "scanner_sha256": _SCANNER_SHA256,
        "scan_status": _SCAN_STATUS_CLEAN,
        "hits": [],
    }
    if content is None or not content.strip():
        return result

    try:
        for category, pattern in _SENSITIVE_CONTENT_RE.items():
            if pattern.search(content):
                result["hits"].append({
                    "category": category,
                    "pattern": pattern.pattern,
                    "type": "content",
                })
        if result["hits"]:
            result["scan_status"] = _SCAN_STATUS_HIT
    except Exception as exc:
        # fail-closed：扫描器异常按错误处理
        result["scan_status"] = _SCAN_STATUS_ERROR
        print(f"WARNING: sensitive scanner error on content: {type(exc).__name__}: {exc}", file=sys.stderr)

    return result


def has_sensitive_hits(scan_result: dict[str, Any]) -> bool:
    """判断扫描结果是否有命中或错误（fail-closed）。"""
    return scan_result.get("scan_status") in (_SCAN_STATUS_HIT, _SCAN_STATUS_ERROR)


# =============================================================================
# 敏感度升级（与 B-16 sensitivity 双轴正交）
# =============================================================================
_SENSITIVITY_ORDER = ("public", "internal", "sensitive", "secret", "unknown")


def escalate_sensitivity(current: str, scan_result: dict[str, Any]) -> str:
    """根据扫描结果升级 sensitivity（仅能提高，不能降低）。

    - 扫描命中 → 升级为 "secret"（最高敏感度）
    - 扫描错误 → 升级为 "secret" 并标注 classification_status=error
    - 未命中 → 保持当前 sensitivity 不变

    与 B-16 provenance 正交：仅升级 sensitivity，不改变 provenance。
    """
    if scan_result["scan_status"] == _SCAN_STATUS_HIT:
        return "secret"
    if scan_result["scan_status"] == _SCAN_STATUS_ERROR:
        return "secret"
    return current  # 保持当前值


def is_higher_sensitivity(new: str, current: str) -> bool:
    """判断 new 是否比 current 更高（或同级）。"""
    if new not in _SENSITIVITY_ORDER or current not in _SENSITIVITY_ORDER:
        return False
    return _SENSITIVITY_ORDER.index(new) >= _SENSITIVITY_ORDER.index(current)