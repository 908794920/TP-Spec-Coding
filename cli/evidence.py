# -*- coding: utf-8 -*-
"""V5.2.0 统一证据校验（Fourth Hardening P1-2：local_file 显式 schema）。

《V5.2.0 第四轮最终收敛修复任务》P1-2：第三轮 Evidence validator 仍接受
``none`` 与裸 hash（``sha256:...`` / 64 hex），导致"无真实证据的 PASS"可绕过。
本轮将证据语义收敛为唯一 schema：

    {"type": "local_file", "path": "<相对路径>", "sha256": "<64 hex>"}

V5.2.0 仅支持 local_file 类型。其余形式（external_uri / signed_attestation /
inline_digest / none / 裸 hash / ``sha256:`` 前缀字符串）一律拒绝（fail-closed）。

校验规则（10 条，全部满足才 ok=True）：
1. 空字符串 → 拒绝；
2. 字面量 ``none`` → 拒绝；
3. ``sha256:<...>`` / 纯 64 hex 等"无文件指纹"形式 → 拒绝；
4. 相对路径（拒绝绝对路径）；
5. 规范化后必须位于 task_dir 内（拒绝 ``..`` 越界 / symlink 逃逸）；
6. 文件必须存在；
7. 必须是普通文件（非目录、非特殊文件）；
8. 必须可读；
9. 必须非空（st_size > 0；空文件 SHA-256 仍是合法字符串，必须显式检查大小）；
10. SHA-256 可计算且非空。

所有调用方（architecture/verification/acceptance/test-guide/human receipt/
deferred/admin recovery）统一走本模块，禁止各自实现"跳过 none"类旁路。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

_HEX64 = re.compile(r"[0-9a-f]{64}")

# V5.2.0 仅支持的类型
_SUPPORTED_TYPES = ("local_file",)


@dataclass
class EvidenceResult:
    ok: bool
    sha256: str = ""
    error: str = ""
    path: str = ""
    type: str = "local_file"
    item: Dict = field(default_factory=dict)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_evidence(item: Union[str, Dict, None]) -> EvidenceResult:
    """解析并校验一条证据（local_file 显式 schema）。

    接受形式：
    - 字符串相对路径（兼容旧调用，默认视为 local_file）；
    - 字典/对象：{"type": "local_file", "path": "<相对路径>"}（sha256 由本函数计算）。

    拒绝（fail-closed）：
    - 空 / None / ``none`` / 裸 hash / ``sha256:`` 前缀；
    - type 不是 local_file；
    - 其余规则见模块 docstring。
    """
    if item is None:
        return EvidenceResult(ok=False, error="evidence is empty (None)")
    if isinstance(item, str):
        raw = item.strip()
        if not raw:
            return EvidenceResult(ok=False, error="evidence path is empty")
        if raw.lower() == "none":
            return EvidenceResult(ok=False, error="evidence type 'none' is rejected in V5.2.0 (local_file schema only)")
        if raw.lower().startswith("sha256:") or _HEX64.fullmatch(raw.lower()):
            return EvidenceResult(ok=False, error="bare digest evidence is rejected in V5.2.0; provide a real local_file path")
        return _validate_local_file(raw, raw)
    if isinstance(item, dict):
        etype = str(item.get("type") or "").strip().lower()
        if etype not in _SUPPORTED_TYPES:
            return EvidenceResult(ok=False, error=f"evidence type {etype!r} is not supported in V5.2.0 (local_file only)")
        path = str(item.get("path") or "").strip()
        if not path:
            return EvidenceResult(ok=False, error="local_file evidence requires a non-empty 'path'")
        return _validate_local_file(path, str(item.get("path") or ""))
    return EvidenceResult(ok=False, error=f"unsupported evidence form: {type(item).__name__}")


def _validate_local_file(raw: str, original: str) -> EvidenceResult:
    p = Path(raw)
    if p.is_absolute():
        return EvidenceResult(ok=False, path=raw,
                              error=f"evidence path must be relative to the task directory: {original}")
    # 注意：本函数只做结构/格式校验；路径存在性校验依赖调用方提供 task_dir。
    return EvidenceResult(ok=True, path=raw, type="local_file", item={"type": "local_file", "path": raw})


def validate_evidence_path(task_dir: Union[str, Path], evidence_path: Optional[str], *, require_evidence_dir: bool = False) -> EvidenceResult:
    """校验单个证据路径（local_file，强制真实文件）。返回 EvidenceResult。

    若 evidence_path 为已解析的结构（dict）则走 parse_evidence + 存在性校验。
    """
    if isinstance(evidence_path, dict):
        parsed = parse_evidence(evidence_path)
        if not parsed.ok:
            return parsed
        raw = parsed.path
    else:
        parsed = parse_evidence(evidence_path)
        if not parsed.ok:
            return parsed
        raw = parsed.path
    base = Path(task_dir).resolve()
    normalized = Path(raw).as_posix()
    if require_evidence_dir:
        # Governance PASS evidence must be independent, immutable evidence.  Projection
        # files and the review artifact itself cannot prove their own correctness.
        if normalized == "evidence" or not normalized.startswith("evidence/"):
            return EvidenceResult(ok=False, path=raw, type="local_file",
                                  error=f"governance evidence must be stored under evidence/: {raw}")
        forbidden = {
            "events.jsonl", "status.yaml", "handoff.json",
            "architecture-review.md", "codex-review.md",
            "generated/current.md",
        }
        if normalized in forbidden or normalized.startswith("generated/"):
            return EvidenceResult(ok=False, path=raw, type="local_file",
                                  error=f"projection/review artifacts cannot be used as governance evidence: {raw}")
    target = (base / raw).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return EvidenceResult(ok=False, path=raw, type="local_file",
                              error=f"evidence path escapes the task directory: {raw}")
    if not target.exists():
        return EvidenceResult(ok=False, path=raw, type="local_file",
                              error=f"evidence file does not exist: {raw}")
    if not target.is_file() or target.is_dir():
        return EvidenceResult(ok=False, path=raw, type="local_file",
                              error=f"evidence path is not a regular file: {raw}")
    # Final Night Hardening（P0-3）：空文件必须拒绝——空文件的 SHA-256 是合法
    # 非空字符串（e3b0c44...），"digest 非空"判断无法拦截，必须显式检查大小。
    try:
        if target.stat().st_size == 0:
            return EvidenceResult(ok=False, path=raw, type="local_file",
                                  error=f"evidence file is empty (0 bytes): {raw}")
    except OSError as exc:
        return EvidenceResult(ok=False, path=raw, type="local_file",
                              error=f"evidence file is not readable: {raw}: {exc}")
    try:
        digest = _sha256_file(target)
    except OSError as exc:
        return EvidenceResult(ok=False, path=raw, type="local_file",
                              error=f"evidence file is not readable: {raw}: {exc}")
    if not digest:
        return EvidenceResult(ok=False, path=raw, type="local_file",
                              error=f"evidence file is empty: {raw}")
    return EvidenceResult(ok=True, sha256=digest, path=raw, type="local_file",
                          item={"type": "local_file", "path": raw, "sha256": digest})


def validate_evidence_list(task_dir: Union[str, Path], items: Optional[List[Union[str, Dict]]]) -> List[EvidenceResult]:
    """校验证据列表，返回逐项结果（调用方决定 PASS 至少一项真实证据）。"""
    results: List[EvidenceResult] = []
    for item in items or []:
        results.append(validate_evidence_path(task_dir, item))
    return results
