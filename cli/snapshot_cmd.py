# -*- coding: utf-8 -*-
"""V5.2.3 B-18 cutover 快照工具（T1，非破坏性）。

设计依据：历史设计记录 B18-cutover-design §2.1-§2.3。
- 快照落 base 仓根 cutover-snapshots/V<base_version>-<UTC-TIMESTAMP>/（不写入消费方 Junction 目标）；
- 快照范围 = governance/{compat-matrix,lifecycle,workflow,ai-role,risk-rule,knowledge-rule,orchestration}
  + agents/role-catalog.yaml + templates/<active-version>/（8 文件）+ VERSION；
- 生成 CUTOVER-SNAPSHOT-MANIFEST.json（每项 path/sha256/size/status；manifest 自身
  manifest_sha256 两段式防篡改，§2.2）；
- cutover receipt 写入 base_root/evidence/receipts/REC-<UTC>-<UUID>.json
  （create-new 原子创建，禁止覆盖；§2.3），快照目录内保留 CUTOVER-RECEIPT 副本；
- 快照文件设只读位（best-effort，Windows 权限模型差异容忍）；
- 同时间戳重复快照幂等不覆盖：目录已存在且与当前源一致 → 返回 already_exists。

纯 stdlib、离线、无网络/模型/DB；本模块不 import review_preflight/s1_validator/sensitive_scanner。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config_loader import default_base_root, read_base_version
from .version import active_version, next_version

MANIFEST_VERSION = "1.0.0"
RECEIPT_VERSION = "1.0.0"
SNAPSHOT_ROOT_NAME = "cutover-snapshots"
MANIFEST_FILE_NAME = "CUTOVER-SNAPSHOT-MANIFEST.json"
RECEIPT_PREFIX = "CUTOVER-RECEIPT-"

# 快照源文件（相对 base 仓根；templates/<active>/ 目录整体入快照，动态枚举）
_GOVERNANCE_FILES = (
    "governance/compat-matrix.yaml",
    "governance/lifecycle.md",
    "governance/workflow.yaml",
    "governance/ai-role.yaml",
    "governance/risk-rule.yaml",
    "governance/knowledge-rule.yaml",
    "governance/orchestration.yaml",
)
_TOP_LEVEL_FILES = ("agents/role-catalog.yaml", "VERSION")


def snapshot_source_paths(base_root: Path) -> list[Path]:
    """枚举快照源文件（governance 7 + agents/role-catalog.yaml + templates/<active>/* + VERSION）。"""
    sources = [base_root / rel for rel in _GOVERNANCE_FILES]
    sources.append(base_root / _TOP_LEVEL_FILES[0])
    tpl_dir = base_root / f"templates/{active_version(base_root)}"
    if not tpl_dir.is_dir():
        raise ValueError(f"snapshot source templates dir missing: {tpl_dir}")
    sources.extend(sorted(p for p in tpl_dir.iterdir() if p.is_file()))
    sources.append(base_root / _TOP_LEVEL_FILES[1])
    return sources


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _entry_for(rel_path: str, base_root: Path) -> dict[str, Any]:
    src = base_root / rel_path
    if not src.is_file():
        raise ValueError(f"snapshot source missing: {rel_path}")
    return {
        "path": rel_path.replace(os.sep, "/"),
        "sha256": _sha256_file(src),
        "size": src.stat().st_size,
        "status": "snapshotted",
    }


def _manifest_body(entries: list[dict[str, Any]], created_at: str, base_version: str, target_version: str) -> dict[str, Any]:
    """§2.2 manifest body（不含 manifest_sha256，两段式防自引用）。"""
    return {
        "manifest_version": MANIFEST_VERSION,
        "created_at": created_at,
        "base_version": base_version,
        "target_version": target_version,
        "entries": entries,
        "total_entries": len(entries),
    }


def _serialize(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _existing_manifest_matches(snap_dir: Path, entries: list[dict[str, Any]]) -> bool:
    """幂等校验：已存在快照的 manifest entries 与当前源逐项一致。"""
    manifest_path = snap_dir / MANIFEST_FILE_NAME
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return manifest.get("entries") == entries


def _set_readonly(path: Path) -> None:
    """best-effort 只读位；Windows 权限模型差异不阻断（§2.1 L65 允许 human_owner 确认）。"""
    try:
        os.chmod(path, 0o444)
    except OSError:
        pass


def build_snapshot(
    base_root: "str | Path | None" = None,
    *,
    timestamp: str | None = None,
    actor: str = "human_owner",
    target_version: "str | None" = None,
) -> dict[str, Any]:
    """建立 base 仓根只读快照 + manifest + cutover receipt（T1）。

    幂等：同时间戳目录已存在且 entries 与当前源一致 → 返回 already_exists=True（不覆盖）。
    target_version 缺省按当前 VERSION 计算下一 minor 版本（不硬编码）。
    """
    base = Path(base_root) if base_root else default_base_root()
    base = base.resolve()
    base_version = read_base_version(base)
    target = target_version or next_version(base)
    ts = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap_dir = base / SNAPSHOT_ROOT_NAME / f"V{base_version}-{ts}"

    sources = snapshot_source_paths(base)
    entries = []
    for src in sources:
        rel = src.relative_to(base).as_posix()
        entries.append(_entry_for(rel, base))

    if snap_dir.exists():
        if _existing_manifest_matches(snap_dir, entries):
            manifest = json.loads((snap_dir / MANIFEST_FILE_NAME).read_text(encoding="utf-8"))
            return {
                "snapshot_dir": str(snap_dir),
                "base_version": base_version,
                "manifest": manifest,
                "receipt_path": None,
                "receipt_snapshot_copy": None,
                "already_exists": True,
            }
        raise ValueError(f"snapshot directory exists but content mismatch; refusing to overwrite: {snap_dir}")

    # 逐文件复制 + 只读位
    snap_dir.mkdir(parents=True, exist_ok=False)
    for entry in entries:
        src = base / entry["path"]
        dst = snap_dir / entry["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        _set_readonly(dst)

    # §2.2 manifest（两段式：body 序列化 → content_hash → 写入 manifest_sha256）
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    body = _manifest_body(entries, created_at, base_version, target)
    content_hash = hashlib.sha256(_serialize(body)).hexdigest()
    manifest = dict(body, manifest_sha256=content_hash)
    manifest_path = snap_dir / MANIFEST_FILE_NAME
    manifest_path.write_bytes(_serialize(manifest))
    _set_readonly(manifest_path)

    # §2.3 cutover receipt：主副本 evidence/receipts/（create-new 原子）+ 快照目录内副本
    utc_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt_id = f"REC-{utc_stamp}-{uuid.uuid4().hex}"
    receipt_record = {
        "receipt_type": "cutover",
        "receipt_version": RECEIPT_VERSION,
        "created_at": created_at,
        "actor": actor,
        "snapshot_path": snap_dir.as_posix(),
        "manifest_sha256": content_hash,
        "deletion_manifest": [],
        "human_owner": "human_owner",
    }
    receipts_dir = base / "evidence" / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipts_dir / f"{receipt_id}.json"
    with open(receipt_path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(receipt_record, ensure_ascii=False, indent=2) + "\n")

    # 快照目录内 receipt 副本（§2.1 结构；create-new，防覆盖）
    receipt_copy = snap_dir / f"{RECEIPT_PREFIX}{receipt_id}.json"
    with open(receipt_copy, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(receipt_record, ensure_ascii=False, indent=2) + "\n")
    _set_readonly(receipt_copy)

    return {
        "snapshot_dir": str(snap_dir),
        "base_version": base_version,
        "manifest": manifest,
        "receipt_path": str(receipt_path),
        "receipt_snapshot_copy": str(receipt_copy),
        "already_exists": False,
    }


def cmd_cutover_snapshot(args) -> int:
    """cutover-snapshot CLI：建立 base 仓根只读快照 + manifest + receipt。"""
    try:
        result = build_snapshot(
            base_root=getattr(args, "base_root", None),
            timestamp=getattr(args, "timestamp", None),
            actor=getattr(args, "actor", "human_owner"),
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    state = "already-exists (idempotent)" if result["already_exists"] else "created"
    print(f"cutover-snapshot: {state}: {result['snapshot_dir']}")
    print(f"  base-version: {result['base_version']}  target-version: {result['manifest'].get('target_version')}")
    print(f"  manifest: {result['manifest']['manifest_sha256']} ({result['manifest']['total_entries']} entries)")
    if result["receipt_path"]:
        print(f"  receipt: {result['receipt_path']}")
    return 0


def add_cutover_snapshot_subparsers(subparsers) -> None:
    """注册 cutover-snapshot 子命令（V5.2.3 B-18 T1）。"""
    p = subparsers.add_parser(
        "cutover-snapshot",
        help="V5.2.3 B-18 T1: create a read-only base-repo snapshot + manifest + cutover receipt (non-destructive, no state change)",
    )
    p.add_argument("--base-root", default=None, help="base repo root (default: parent of cli/ package)")
    p.add_argument("--actor", default="human_owner", help="receipt actor (design §2.3 defaults to human_owner)")
    p.add_argument("--timestamp", default=None, help="explicit UTC timestamp YYYYMMDDTHHMMSSZ (testing/determinism)")
    p.set_defaults(func=cmd_cutover_snapshot)
