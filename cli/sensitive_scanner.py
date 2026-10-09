# -*- coding: utf-8 -*-
"""9.5-1 敏感信息扫描器（确定性路径/内容模式扫描）。

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
_SCANNER_VERSION = "1.1.0"

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
            "chinese_password_literal": r"密码[^`\"'“\r\n，,。、;；|→]{0,24}[`\"'“](?P<value>[^`\"'”\r\n]+)[`\"'”]",
            "aes_key_literal": r"(?i:AES\s*(?:密钥|秘钥|key))[^`\"'“\r\n，,。、;；|→]{0,16}[`\"'“](?P<value>[^`\"'”\r\n]+)[`\"'”]",
            "credential_constant": r"(?i:\b(?=[A-Z0-9_.]*(?:PASSWORD|PASSWD|PWD|SECRET|TOKEN|API_KEY|APIKEY|ENCRYPTKEY|DECRYPTKEY|AES_KEY|AESKEY))[A-Z_][A-Z0-9_.]*\s*=\s*)[`\"'](?P<value>[^`\"'\r\n]+)[`\"']",
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

# Content consumers choose the applicable categories; private network addresses
# retain their original classification in scan_content/review-preflight.
_CREDENTIAL_CATEGORIES = frozenset({
    "bearer_token", "api_key_prefix", "aws_akid", "aws_secret_key", "private_key_block",
    "db_conn_string", "jdbc_url", "mongodb_conn", "password_keyword",
    "chinese_password_literal", "aes_key_literal", "credential_constant",
})


def _credential_value_present(match: re.Match, category: str, *, credentials_only: bool = False) -> bool:
    value = match.groupdict().get("value")
    if credentials_only and category in {"db_conn_string", "jdbc_url", "mongodb_conn"}:
        authority = re.split(r"[/\s?#]", match.group().split("://", 1)[-1], maxsplit=1)[0]
        # A host:port URL followed by a later @ annotation is not userinfo.
        if not re.fullmatch(r"[^:@]+:[^@]+@", authority):
            return False
        value = authority.split(":", 1)[1][:-1]
    if value is None and category in {"password_keyword", "bearer_token"}:
        raw = (re.split(r"[:=]", match.group(), maxsplit=1)[-1] if category == "password_keyword"
               else re.split(r"Bearer\s+", match.group(), maxsplit=1)[-1]).strip()
        quoted = raw.startswith(("'", '"', "`"))
        value = raw.strip("`\"',; ")
        yaml_literal = False
        if credentials_only and "\n" in match.group():
            if category != "password_keyword":
                return False
            # Reuse the existing YAML dependency for this small key/value fragment.
            # A scalar on the next line is still a literal; a nested key is not.
            import yaml
            try:
                line_end = match.string.find("\n", match.end())
                parsed = yaml.safe_load(match.string[match.start():line_end if line_end >= 0 else None])
            except yaml.YAMLError:
                return False
            scalar = next(iter(parsed.values())) if isinstance(parsed, dict) and len(parsed) == 1 else None
            if not isinstance(scalar, (str, int, float, bool)):
                return False
            value = str(scalar)
            yaml_literal = True
        if credentials_only and quoted:
            separator = re.search(r"[:=]", match.group())
            value_at = match.start() + separator.end() if separator else match.start()
            value_at += len(match.string[value_at:match.end()]) - len(match.string[value_at:match.end()].lstrip())
            line_start = match.string.rfind("\n", 0, value_at) + 1
            if len(re.findall(r"(?<!\\)" + re.escape(raw[0]), match.string[line_start:value_at])) % 2:
                return False
            end = raw.find(raw[0], 1)
            if end >= 0:
                value = raw[1:end]
        if credentials_only and not quoted and not yaml_literal:
            if category == "bearer_token" and re.match(r"<[^>]+>(?:[`\"'，,。；;（）()]|$)", raw):
                return False
            before = match.string[match.string.rfind("\n", 0, match.start()) + 1:match.start()]
            if category == "password_keyword":
                placeholder = re.match(r"\[(?:redacted|masked)(?:[_ :\-][^\]]+)?\]", raw, re.IGNORECASE)
                if placeholder:
                    tail = raw[placeholder.end():]
                    # The old token regex includes adjacent Markdown/call/URL
                    # syntax. Only a structural closing boundary ends the value;
                    # ordinary suffixes and quoted literal values remain hits.
                    if ((tail.startswith("`") and len(re.findall(r"(?<!\\)`", before)) % 2)
                            or (re.fullmatch(r"[)]+", tail) and before.count("(") > before.count(")"))
                            or (re.match(r"&[A-Za-z_][\w.-]*=", tail)
                                and re.search(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s`]+[?&]$", before))):
                        return False
            if raw.startswith("}") and max(before.rfind("${"), before.rfind("#{")) > before.rfind("}"):
                return False  # An empty property default, not a password value.
            if (re.match(r"\$\{|#\{|\{[\w.]+\}|ENC\(", raw)
                    or re.match(r"(?:[A-Za-z_$][\w$]*\.)*[A-Za-z_$][\w$]*\(", raw.lstrip("="))):
                return False
    if value is None:
        return True
    value = value.strip()
    if (not value or re.fullmatch(r"(?i)(?:\*+|x{3,}|\.{3,}|\[(?:redacted|masked)(?:[_ :\-][^\]]+)?\]|\[?(?:redacted|masked|已脱敏|已隐藏|占位符)\]?|<[^>]+>|\$\{[^}]+\}|#\{[^}]+\}|\{\{[^}]+\}\}|your_[\w-]+)", value)):
        return False
    # Names and algorithm identifiers mentioned as fields/parameters are not
    # literal credentials. Do not turn generic IP/name scanning into a Wiki gate.
    if category in {"chinese_password_literal", "aes_key_literal", "credential_constant"}:
        line_start = match.string.rfind("\n", 0, match.start()) + 1
        opener_at = match.start("value") - 1
        opener = match.string[opener_at]
        if match.group()[-1] != {"“": "”"}.get(opener, opener):
            return False
        if opener in "`\"'" and len(re.findall(r"(?<!\\)" + re.escape(opener), match.string[line_start:opener_at])) % 2:
            return False  # Do not treat an inline-code closing delimiter as an opener.
        prefix = re.split(r"[。；;，,|→]", match.string[line_start:opener_at])[-1]
        description = match.string[match.start():opener_at]
        if re.search(r"<cite\b[^>]*$", prefix, re.IGNORECASE):
            return False
        if re.fullmatch(r"\[?[\w./$-]+\.(?:java|py|xml|properties|md):\d+(?:-\d+)?\]?", value):
            return False
        assignment = re.search(r"(?:默认|初始|超级|固定|特殊|伪)密码|重置密码(?:使用|用|为|是|设为)|密码(?:生成)?固定值|绕过值|(?:密码|密钥|秘钥|key)(?:字段|参数)?(?:默认)?值|(?:密码|密钥|秘钥|key)\s*默认(?:为|是|[:：=])|(?:密码|密钥|秘钥|key)\s*[:：=为是]", prefix, re.IGNORECASE)
        if category != "credential_constant" and (not assignment or re.search(r"配置项|属性名|参数名|字段名", description)) and (
                re.fullmatch(r"[\w./$-]+\.(?:java|py|xml|properties|md|yml|yaml)", value)
                or re.fullmatch(r"[A-Z][\w$]*(?:\.[A-Za-z_$][\w$]*)+", value)):
            return False
        if category != "credential_constant" and not assignment and (re.search(r"算法|机制|方法|哈希|盐|长度|校验|验证|处理|判定|加密|解密|通过|调用|委托|生成|保存|存储|返回|注入|重置|修改|管理|工具|混合|重试|登录|请求头|密码学|密码错误|密码(?:用|经|从|来自|组)", description)
                or re.fullmatch(r"(?:[A-Za-z_$][\w$]*\.)*[A-Za-z_$][\w$]*\([^\r\n]*\)", value)):
            return False
        if category != "credential_constant" and not assignment and re.fullmatch(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+", value):
            nearby = match.string[max(line_start, match.start() - 10):match.end() + 16]
            if re.search(r"加密|解密|校验|验证|配置|字段|参数|存储|对应", nearby) or re.search(r"(?i)\.(?:password|passwd|pwd|secret|token)$", value):
                return False
        if category != "credential_constant":
            before = match.string[max(line_start, match.start() - 8):match.start()]
            after = match.string[match.end():match.end() + 24]
            if not assignment and re.search(r"(?:加密|解密|校验|验证|重置|修改|生成)$", before):
                return False
            if not assignment and re.fullmatch(r"[A-Z][a-z]+(?:[A-Z][A-Za-z0-9]+)+", value) and re.search(r"构造|注入|方法|类|对象|接口|客户端|缓存", description + after):
                return False
            if "加盐" in before and re.fullmatch(r"(?:[A-Za-z_$][\w$]*\.)*[A-Za-z_$][\w$]*\([^\r\n]*\)", value):
                return False
        field_description = re.search(r"字段|参数|属性|标识|常量名", prefix)
        # A relation word can introduce a field name. Only an explicit value
        # description overrides that context; plain credential assignments stay hits.
        literal = re.search(r"默认|重置|固定|绕过|值", prefix) or (
            not field_description and re.search(r"为|是", prefix))
        if category == "chinese_password_literal" and value.lower() in {"password", "passwd", "pwd", "md5", "sha256", "sha-256"} and not literal:
            return False
        if category != "credential_constant" and field_description and not literal:
            return False
    if category == "credential_constant":
        name = match.group().split("=", 1)[0].strip()
        if re.search(r"(?i)(?:FIELD|PARAM|LABEL|COLUMN|HEADER|PREFIX|NAME)(?:_|$)", name):
            return False
        statement = match.string[max(line_start, match.start() - 80):match.end() + 80]
        if (re.search(r"(?i)TOKEN.*(?:KEY|ID)$", name) and not re.search(r"(?i)SECRET|PRIVATE|ENCRYPT|DECRYPT|PASSWORD", name)
                and re.fullmatch(r"[A-Za-z_][\w]*", value) and re.search(r"字段|参数|请求头|缓存|Header|Prefix|TOKEN.*UNIQ", statement, re.IGNORECASE)
                and not re.search(r"密钥|口令", statement)):
            return False  # A documented protocol/cache key name, not a token value.
    return True


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


def scan_content(content: str | None, *, credentials_only: bool = False) -> dict[str, Any]:
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
            if credentials_only and category not in _CREDENTIAL_CATEGORIES:
                continue
            for match in pattern.finditer(content):
                if (credentials_only or category in {"chinese_password_literal", "aes_key_literal", "credential_constant"}) and not _credential_value_present(match, category, credentials_only=credentials_only):
                    continue
                result["hits"].append({
                    "category": category,
                    "pattern": pattern.pattern,
                    "type": "content",
                    "line": content.count("\n", 0, match.start()) + 1,
                    "column": match.start() - content.rfind("\n", 0, match.start()),
                    "mask": "[REDACTED]",
                })
                if not credentials_only:
                    break  # Preserve one result per category for existing consumers.
        if result["hits"]:
            result["scan_status"] = _SCAN_STATUS_HIT
    except Exception as exc:
        # fail-closed：扫描器异常按错误处理
        result["scan_status"] = _SCAN_STATUS_ERROR
        print(f"WARNING: sensitive scanner error on content: {type(exc).__name__}: {exc}", file=sys.stderr)

    return result


def scan_credentials(content: str | None) -> dict[str, Any]:
    """Reuse content rule categories while excluding unrelated path/network risks."""
    return scan_content(content, credentials_only=True)


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
