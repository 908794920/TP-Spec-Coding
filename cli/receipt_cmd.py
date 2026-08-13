# -*- coding: utf-8 -*-
"""V5.2.0 高风险动作收据（execution receipt）命令。

receipt 是动作发生时的不可变审计记录：
- 固定落盘 `.tp-spec/tasks/<TASK-ID>/evidence/receipts/REC-<UTC>-<UUID>.json`；
- 以 create-new 方式原子创建，禁止覆盖、改名或删除既有 receipt；
- 不改变 workflow 状态，不写 SQLite 账本，不要求重写阶段主工件；
- 高风险动作收据用于范围变化、阻塞、DML/DDL、生产动作和外部调用；它不承担人员审批。

V5.2.0 B-16（P1 补强，评审表 9.4 第 3 行 / Q2 / Q8）：
- capability 块新增 provenance（trusted/untrusted/unknown）与 delegated_from（V5.2.0 恒 null）
  及 classifier_version/classifier_sha256/classification_status；
- 纯确定性判定器（R1 repo: 前缀 / R2 .json/.yaml/.yml / R3 .py/.go/.ts/.js /
  R4 fail-closed 默认 untrusted），判定器永不输出 unknown；
- 分类失败 fail-closed 原子写 receipt 不丢审计；调用方只能提高风险不能降低。

V5.2.0 9.5-1（P1 补强，评审表 9.5 第 1 行 / 升级计划 §3.1 L115-116）：
- capability 块新增 scan 字段（敏感路径扫描结果，与 B-16 provenance/sensitivity 双轴正交）；
- 扫描命中时 escalate sensitivity 为 secret，扫描错误时 classification_status=error；
- 扫描器异常 fail-closed 按最高敏感度处理，不静默放行（设计 §6：扫描器自身异常
  一律按命中 fail-closed，禁止跳过扫描继续；调用点 try/except 兜底，receipt 仍原子写入）。
设计依据：历史设计记录 sensitive-scan。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


from . import db as dbmod
from .version import active_version
from .sensitive_scanner import (
    scan_resource_ref,
    has_sensitive_hits,
    escalate_sensitivity,
    _SCANNER_VERSION,
    _SCANNER_SHA256,
    _SCAN_STATUS_ERROR,
)

_ACTION_TYPES = (
    "SCOPE_CHANGE",
    "BLOCKER",
    "DML",
    "DDL",
    "PRODUCTION_ACTION",
    "EXTERNAL_CALL",
)
_ALLOWED_ACTORS = ("tp-product-design", "tp-architecture-design", "tp-development-engineering", "tp-verification-engineering", "tp-delivery-convergence", "human_owner", "tp-requirement-analysis", "tp-architecture-review")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

# --- V5.2.0 B-16：provenance 轻量判定规则（版本化 + 内容哈希双锚点） ---
_CLASSIFIER_VERSION = "1.0.0"
_TRUSTED_META_EXTS = (".json", ".yaml", ".yml")    # R2：结构化元数据扩展名
_TRUSTED_CODE_EXTS = (".py", ".go", ".ts", ".js")  # R3：代码扩展名
_PROVENANCE_VALUES = ("trusted", "untrusted", "unknown")
_SENSITIVITY_VALUES = ("public", "internal", "sensitive", "secret", "unknown")
_RULES_SOURCE = json.dumps(
    {
        "repo_prefix": "repo:",
        "meta_exts": sorted(_TRUSTED_META_EXTS),
        "code_exts": sorted(_TRUSTED_CODE_EXTS),
    },
    sort_keys=True,
)
_CLASSIFIER_SHA256 = "sha256:" + hashlib.sha256(_RULES_SOURCE.encode("utf-8")).hexdigest()


def classify_provenance(resource_ref: str | None) -> tuple[str, str]:
    """V5.2.0 B-16 纯确定性判定器（R1-R4，fail-closed）。

    返回 (provenance, classification_status)；判定器永不输出 unknown。
    """
    # R4 fail-closed：缺失/空引用一律 untrusted
    if resource_ref is None or not resource_ref.strip():
        return "untrusted", "complete"
    ref = resource_ref.strip()
    # R1：repo: 前缀（已登记代码仓库文件）
    if ref.startswith("repo:"):
        return "trusted", "complete"
    lower = ref.lower()
    # R2：结构化元数据扩展名
    if lower.endswith(_TRUSTED_META_EXTS):
        return "trusted", "complete"
    # R3：代码扩展名
    if lower.endswith(_TRUSTED_CODE_EXTS):
        return "trusted", "complete"
    # R4：其余及未匹配白名单 -> untrusted
    return "untrusted", "complete"


def _build_capability(resource_ref: str | None, declared_provenance: str | None, declared_sensitivity: str | None) -> dict:
    """构造 receipt capability 块（V5.2.0 B-16）。

    - 判定器确定性输出 trusted/untrusted；unknown 仅允许显式声明（B16 §4.3）；
    - 调用方只能提高风险，不能覆盖为更低风险（升级计划 §3.6 L224）：
      非法声明值或降级尝试直接拒绝写入（ValueError 传播，receipt 不落盘，B16-R11）；
    - 仅 classifier 本身异常走 fail-closed 默认：provenance=untrusted +
      classification_status=error（升级计划 §3.6 L224/L228），receipt 仍原子写入，不丢审计。
    """
    if declared_provenance is not None and declared_provenance not in _PROVENANCE_VALUES:
        raise ValueError("--provenance must be one of " + ", ".join(_PROVENANCE_VALUES))
    if declared_sensitivity is not None and declared_sensitivity not in _SENSITIVITY_VALUES:
        raise ValueError("--sensitivity must be one of " + ", ".join(_SENSITIVITY_VALUES))
    try:
        classified, status = classify_provenance(resource_ref)
    except Exception as exc:
        # 仅 classifier 异常 fail-closed（L224/L228），receipt 仍写入不丢审计
        classified, status = "untrusted", "error"
        print(f"WARNING: classifier error, fail-closed defaults applied: {type(exc).__name__}: {exc}", file=sys.stderr)
    if declared_provenance == "trusted" and classified == "untrusted":
        # 调用方只能提高风险，不能把 untrusted 覆盖为更低风险的 trusted（L224）
        raise ValueError("cannot lower risk: classifier returned untrusted but caller declared trusted")
    provenance = declared_provenance if declared_provenance is not None else classified
    sensitivity = declared_sensitivity if declared_sensitivity is not None else "unknown"

    # V5.2.0 9.5-1：敏感信息路径扫描（与 B-16 provenance/sensitivity 双轴正交）
    # F2 fail-closed 兜底（设计 §6）：扫描器自身异常（规则加载/hash/IO 中断）一律按
    # 命中处理，禁止异常穿透崩溃 receipt 写入；receipt 仍原子写入不丢审计。
    try:
        scan_result = scan_resource_ref(resource_ref)
    except Exception as exc:
        scan_result = {
            "scanner_version": _SCANNER_VERSION,
            "scanner_sha256": _SCANNER_SHA256,
            "scan_status": _SCAN_STATUS_ERROR,
            "hits": [],
        }
        print(
            f"WARNING: sensitive scanner crashed, fail-closed defaults applied: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    if has_sensitive_hits(scan_result):
        sensitivity = escalate_sensitivity(sensitivity, scan_result)
        if scan_result["scan_status"] == "error":
            status = "error"

    return {
        # 未注册工具 fail-closed 默认（L224）：能力分类保守置 true
        "egress": True,
        "scoped": True,
        "stepup": True,
        "resource_scope": [],
        "provenance": provenance,
        "sensitivity": sensitivity,
        "delegated_from": None,  # V5.2.0 恒 null（schema 预留，升级计划 L219）
        "classifier_version": _CLASSIFIER_VERSION,
        "classifier_sha256": _CLASSIFIER_SHA256,
        "classification_status": status,
        # V5.2.0 9.5-1：敏感路径扫描结果（与 B-16 provenance/sensitivity 双轴正交，禁止合并）
        "scan": scan_result,
    }



def _normalize_sha256(value: str, *, field: str) -> str:
    """接受 64 位十六进制或 sha256: 前缀形式，统一为 sha256:<hex>。"""
    candidate = (value or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", candidate):
        candidate = f"sha256:{candidate}"
    if not _SHA256_RE.fullmatch(candidate):
        raise ValueError(f"{field} must be a sha256 hex digest (64 hex chars, optional sha256: prefix)")
    return candidate


def cmd_receipt(args) -> int:
    if not args.task or not args.task_dir:
        raise ValueError("--task and --task-dir are required for 'receipt'")
    if args.actor not in _ALLOWED_ACTORS:
        raise ValueError("unsupported actor")
    task_dir = Path(args.task_dir).resolve()
    status_path = task_dir / "status.yaml"
    if not status_path.is_file():
        raise ValueError(f"task directory has no status.yaml: {task_dir}")
    # --task 必须与 task-dir/status.yaml 的 task_id 一致，避免收据落错任务目录。
    with open(status_path, "r", encoding="utf-8-sig") as handle:
        status_text = handle.read()
    status_match = re.search(r"(?m)^task_id:\s*[\"']?([^\"'\n#]+)", status_text)
    status_task_id = status_match.group(1).strip() if status_match else ""
    if not status_task_id:
        raise ValueError("status.yaml is missing task_id")
    if status_task_id != args.task:
        raise ValueError(f"--task '{args.task}' does not match status.yaml task_id '{status_task_id}'")
    # V5.2.0 单一活动契约：旧契约非终态任务须先经官方 migrate/retire 处理；业务命令不直接在旧契约上追加收据。
    contract_match = re.search(r"(?ms)^artifact_contract:\s*\n\s+version:\s*[\"']?([^\"'\n#]+)", status_text)
    contract_version = contract_match.group(1).strip() if contract_match else ""
    if contract_version != active_version():
        raise ValueError(f"legacy contract task is a frozen static archive; receipts may only be recorded for artifact_contract.version={active_version()}")
    if args.script:
        script_path = Path(args.script)
        if not script_path.is_file():
            raise ValueError(f"--script file not found: {script_path}")
        action_sha256 = "sha256:" + hashlib.sha256(script_path.read_bytes()).hexdigest()
    elif args.action_sha256:
        action_sha256 = _normalize_sha256(args.action_sha256, field="--action-sha256")
    else:
        raise ValueError("either --script or --action-sha256 is required")
    evidence_hash = _normalize_sha256(args.evidence_hash, field="--evidence-hash")

    utc_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt_id = f"REC-{utc_stamp}-{uuid.uuid4().hex}"
    record = {
        "receipt_id": receipt_id,
        "schema_version": active_version(),
        "task_id": args.task,
        "action_type": args.action_type,
        "actor": args.actor,
        "authorized_by": args.authorized_by,
        "authorization_scope": args.authorization_scope,
        "environment": args.environment,
        "action_sha256": action_sha256,
        "summary": args.summary,
        "result": args.result,
        "timestamp": dbmod.now_iso(),
        "evidence_hash": evidence_hash,
        # V5.2.0 B-16：capability 块（纯增量，不删旧字段）
        "capability": _build_capability(args.resource_ref, args.provenance, args.sensitivity),
    }
    receipts_dir = task_dir / "evidence" / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipts_dir / f"{receipt_id}.json"
    # create-new：文件已存在时立即失败，绝不覆盖既有 receipt。
    with open(receipt_path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print(f"receipt: {receipt_path.relative_to(task_dir).as_posix()}")
    return 0


def add_receipt_subparsers(subparsers) -> None:
    p = subparsers.add_parser("receipt", help="Record an immutable high-risk execution receipt without changing workflow state")
    p.add_argument("--task", required=False)
    p.add_argument("--task-dir", required=False)
    p.add_argument("--actor", required=False, choices=sorted(_ALLOWED_ACTORS))
    p.add_argument("--action-type", required=False, choices=sorted(_ACTION_TYPES))
    p.add_argument("--summary", required=False, help="What happened (action or scope summary)")
    p.add_argument("--authorized-by", required=False, help="Optional operator note; not an approval identity")
    p.add_argument("--authorization-scope", required=False, help="Authorized scope of the action")
    p.add_argument("--environment", required=False, help="Environment the action ran in (e.g. dev/test/prod)")
    p.add_argument("--action-sha256", help="SHA-256 of the action/script content (64 hex, optional sha256: prefix)")
    p.add_argument("--script", help="Path to the action script; its SHA-256 is computed automatically")
    p.add_argument("--result", required=False, help="Result / impact range")
    p.add_argument("--evidence-hash", required=False, help="SHA-256 of the evidence payload")
    # V5.2.0 B-16：capability 判定输入（纯增量）
    p.add_argument("--resource-ref", help="Structured resource reference for provenance classification (repo: prefix / file extension); absent defaults to untrusted (fail-closed)")
    p.add_argument("--provenance", choices=sorted(_PROVENANCE_VALUES), help="Explicit provenance declaration; unknown is explicit-declaration only (classifier never outputs it); cannot lower classifier risk")
    p.add_argument("--sensitivity", choices=sorted(_SENSITIVITY_VALUES), help="Data sensitivity; defaults to unknown (never pretend public)")
    p.add_argument("--db", required=False, help="Accepted for CLI consistency; receipts are file-only and do not touch the DB")
    p.set_defaults(func=cmd_receipt)
