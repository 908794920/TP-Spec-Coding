# -*- coding: utf-8 -*-
"""V5.2.3 B-18 cutover 回滚工具（T2，依赖 T1 快照）。

设计依据：历史设计记录 B18-cutover-design §2.2/§4.2-§4.3/§9.2-T2。
- 从快照还原 governance/agents/VERSION/templates，还原后逐项 sha256 与 manifest 一致
  （含 agents/role-catalog.yaml；§4.2 阶段 3）；
- 回滚后验证断言（§4.3 / §3.8 L258）：
  D1 目标版本（默认下一版本 5.2.3）新写入被拒（gate_task_contract → VERSION_MISMATCH）
  D2 当前活动版本（VERSION 文件）恢复为唯一可写契约（gate 通过）
  D3 任意未声明版本仍被拒（gate → VERSION_MISMATCH）
  D4 快照自身 sha256 不变（verify_snapshot）
- CLI 默认 --dry-run 零写入（演练/审阅安全）；--apply 才真正还原（须 human_owner 授权）。

纯 stdlib、离线、无网络/模型/DB；不修改消费方 Junction 目标。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from .config_loader import default_base_root, gate_task_contract, read_base_version
from .snapshot_cmd import (
    MANIFEST_FILE_NAME,
    SNAPSHOT_ROOT_NAME,
    _serialize,
)
from .version import active_version, next_version

# 回滚后恢复为唯一可写契约 = 当前活动版本（VERSION 文件）
PREVIOUS_VERSION = active_version()
# 任意未声明版本（断言静态旧任务仍被拒）
LEGACY_VERSION = "9.9.9"


def list_snapshots(base_root: "str | Path | None" = None) -> list[Path]:
    """枚举 base 仓根 cutover-snapshots/ 下的快照目录（按名称倒序，最新在前）。"""
    base = Path(base_root) if base_root else default_base_root()
    snap_root = base / SNAPSHOT_ROOT_NAME
    if not snap_root.is_dir():
        return []
    return sorted((p for p in snap_root.iterdir() if p.is_dir()), reverse=True)


def load_manifest(snap_dir: Path) -> dict[str, Any]:
    manifest_path = snap_dir / MANIFEST_FILE_NAME
    if not manifest_path.is_file():
        raise ValueError(f"snapshot has no manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != "1.0.0":
        raise ValueError(f"unsupported manifest version: {manifest.get('manifest_version')}")
    return manifest


def _verify_manifest_self_hash(manifest: dict[str, Any]) -> bool:
    """重算 manifest 自身 sha256（两段式：body 不含 manifest_sha256）。"""
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    return hashlib.sha256(_serialize(body)).hexdigest() == manifest.get("manifest_sha256")


def verify_snapshot(snap_dir: Path) -> dict[str, Any]:
    """校验快照完整性：manifest 自 hash + 每项文件 sha256/size 与 entries 一致。"""
    errors: list[str] = []
    try:
        manifest = load_manifest(snap_dir)
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "errors": [f"manifest unreadable: {exc}"]}
    if not _verify_manifest_self_hash(manifest):
        errors.append("manifest_sha256 self-hash mismatch")
    for entry in manifest.get("entries", []):
        rel = entry.get("path")
        file_path = snap_dir / rel
        if not file_path.is_file():
            errors.append(f"missing snapshot file: {rel}")
            continue
        actual = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if actual != entry.get("sha256"):
            errors.append(f"sha256 mismatch: {rel}")
        if file_path.stat().st_size != entry.get("size"):
            errors.append(f"size mismatch: {rel}")
    return {"ok": not errors, "errors": errors}


def restore_snapshot(
    snap_dir: Path,
    base_root: "str | Path | None" = None,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """从快照还原 governance/agents/VERSION/templates（§4.2 阶段 3）。

    apply=False（默认）→ 只打印 would-restore 清单（零写入）；
    apply=True → 逐项复制回 base 仓根，还原后逐项 sha256 与 manifest 比对。
    """
    base = Path(base_root) if base_root else default_base_root()
    base = base.resolve()
    manifest = load_manifest(snap_dir)
    restored: list[dict[str, Any]] = []
    for entry in manifest.get("entries", []):
        if entry.get("status") != "snapshotted":
            continue
        rel = entry["path"]
        src = snap_dir / rel
        dst = base / rel
        restored.append({
            "path": rel,
            "expected_sha256": entry.get("sha256"),
            "would_restore": not apply,
            "restored": False,
        })
        if not apply:
            continue
        if not src.is_file():
            raise ValueError(f"snapshot file missing during restore: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)  # 仅复制内容，不复制快照只读位
        actual = hashlib.sha256(dst.read_bytes()).hexdigest()
        if actual != entry.get("sha256"):
            raise ValueError(f"restore readback sha256 mismatch: {rel}")
        restored[-1]["restored"] = True
    return {"restored": restored, "apply": apply}


def assert_rollback(
    snap_dir: Path,
    base_root: "str | Path | None" = None,
    *,
    target_version: "str | None" = None,
) -> dict[str, Any]:
    """回滚后四项断言（§4.3 / §3.8 L258）：目标版本拒、活动版本可写、未声明版本拒、快照不变。"""
    base = Path(base_root) if base_root else default_base_root()
    base = base.resolve()
    target = target_version or next_version(base)
    previous = active_version(base)
    checks: dict[str, dict[str, Any]] = {}

    def _gate(version: str) -> bool:
        try:
            gate_task_contract(version, base_root=base)
            return True
        except Exception:
            return False

    checks[f"V{target} 新写入被拒"] = {
        "ok": not _gate(target),
        "detail": f"gate_task_contract({target}) must raise VERSION_MISMATCH",
    }
    checks[f"V{previous} 恢复为唯一可写契约"] = {
        "ok": _gate(previous),
        "detail": f"gate_task_contract({previous}) must pass",
    }
    checks["未声明版本静态旧任务仍被拒"] = {
        "ok": not _gate(LEGACY_VERSION),
        "detail": f"gate_task_contract({LEGACY_VERSION}) must raise VERSION_MISMATCH",
    }
    verify = verify_snapshot(snap_dir)
    checks["快照自身 sha256 不变"] = {
        "ok": verify["ok"],
        "detail": "verify_snapshot: " + ("ok" if verify["ok"] else "; ".join(verify["errors"])),
    }
    return {"checks": checks, "all_ok": all(c["ok"] for c in checks.values())}


def cmd_cutover_rollback(args) -> int:
    """cutover-rollback CLI：verify → (dry-run|apply) restore → §4.3 四项断言。"""
    base = Path(args.base_root).resolve() if args.base_root else default_base_root()
    snap_name = args.snapshot
    candidates = [p for p in list_snapshots(base) if p.name == snap_name]
    if not candidates:
        # 允许直接给快照目录完整路径
        direct = Path(snap_name).resolve()
        if direct.is_dir() and (direct / MANIFEST_FILE_NAME).is_file():
            candidates = [direct]
    if not candidates:
        print(f"ERROR: snapshot not found: {snap_name} (base-root={base})", file=sys.stderr)
        return 1
    snap_dir = candidates[0]

    verify = verify_snapshot(snap_dir)
    if not verify["ok"]:
        print(f"ERROR: snapshot verification failed: {'; '.join(verify['errors'])}", file=sys.stderr)
        return 1

    apply = bool(getattr(args, "apply", False))
    result = restore_snapshot(snap_dir, base, apply=apply)
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"cutover-rollback: {mode} from {snap_dir}")
    for item in result["restored"]:
        flag = "would-restore" if item["would_restore"] else ("restored" if item["restored"] else "error")
        print(f"  {flag}: {item['path']}")

    if not apply:
        print("  (zero-write: pass --apply to restore; destructive action requires human_owner authorization)")
        return 0

    assertions = assert_rollback(
        snap_dir, base, target_version=getattr(args, "target_version", None)
    )
    for name, check in assertions["checks"].items():
        print(f"  assert[{name}]: {'PASS' if check['ok'] else 'FAIL'} ({check['detail']})")
    if not assertions["all_ok"]:
        print("ERROR: rollback assertions failed", file=sys.stderr)
        return 1
    print(f"cutover-rollback: ok (base restored to {read_base_version(base)})")
    return 0


def add_cutover_rollback_subparsers(subparsers) -> None:
    """注册 cutover-rollback 子命令（V5.2.3 B-18 T2）。"""
    p = subparsers.add_parser(
        "cutover-rollback",
        help="V5.2.3 B-18 T2: restore base repo from snapshot + §4.3 rollback assertions (default dry-run zero-write)",
    )
    p.add_argument("--snapshot", required=True, help="snapshot directory name under cutover-snapshots/ (or full path)")
    p.add_argument("--base-root", default=None, help="base repo root (default: parent of cli/ package)")
    p.add_argument("--target-version", default=None, help="target version for rollback assertion D1 (default: next minor of VERSION)")
    p.add_argument("--apply", action="store_true", help="actually restore files (destructive; requires human_owner authorization)")
    p.set_defaults(func=cmd_cutover_rollback)
