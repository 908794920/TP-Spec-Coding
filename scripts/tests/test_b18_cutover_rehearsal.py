# -*- coding: utf-8 -*-
"""V5.1.3 B-18 cutover 隔离副本演练回归套件（T3）。

设计权威：docs/V5.1.3-B18-cutover-design.md §4.2（阶段 1-4）/§4.3（回滚后验证断言）/§9.1-T3/§9.2-T3。
强断言：快照 manifest 逐项 sha256/size、gate_task_contract 外层门控行为（VERSION_MISMATCH）、
还原后逐项 sha256 与 manifest 一致、演练不修改真实 base 仓关键文件（前后指纹一致）、
演练后隔离副本完整删除无残留。

四阶段（仅在隔离副本内执行，绝不动真实 base 仓 VERSION/治理文件）：
  阶段 1 建立隔离副本 + 快照（build_snapshot(base_root=副本)）
  阶段 2 下一 minor 切换（副本内改 VERSION/compat-matrix/治理版本/templates/<next>/config_schemas 副本）
  阶段 3 从快照回滚（restore_snapshot apply）+ §4.3 四项断言
  阶段 4 清理副本 + 真实 base 仓指纹不变断言 + 演练报告输出

Run:
    python scripts/tests/test_b18_cutover_rehearsal.py
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent  # ai-work-base
sys.path.insert(0, str(BASE))

from cli import snapshot_cmd, rollback_cmd  # noqa: E402
from cli.config_loader import gate_task_contract  # noqa: E402
from cli.config_loader import ConfigLoadError  # noqa: E402

TS_FIXED = "20260801T120000Z"  # 确定性时间戳
# 活体派生：快照目录名跟随隔离副本 VERSION（cutover 后基线 5.1.3），消除版本硬编码
_BASE_VERSION = (BASE / "VERSION").read_text(encoding="utf-8").strip()
SNAP_DIR_NAME = f"V{_BASE_VERSION}-{TS_FIXED}"

# 真实 base 仓关键文件（演练前后指纹核验对象；切不可被演练修改）
REAL_WATCH = (
    "VERSION",
    "governance/compat-matrix.yaml",
    "governance/lifecycle.md",
    "governance/workflow.yaml",
    "governance/ai-role.yaml",
    "governance/risk-rule.yaml",
    "governance/knowledge-rule.yaml",
    "agents/role-catalog.yaml",
    f"templates/{_BASE_VERSION}/status.yaml",
)

# 副本需复制的 base 目录/文件（足够支撑快照源 + gate 测试）
_COPY_ITEMS = ("VERSION", "governance", "agents", "templates", "cli")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint(root: Path, rels: tuple[str, ...]) -> str:
    """对一组文件路径计算指纹（rel:sha256 排序拼接后整体 sha256）。"""
    parts = []
    for rel in rels:
        p = root / rel
        if not p.is_file():
            raise AssertionError(f"watch file missing: {rel}")
        parts.append(f"{rel}:{_sha256_file(p)}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _snapshot_root_fingerprint(root: Path) -> str:
    """真实 base cutover-snapshots/ 目录清单指纹（演练不得新增/删除真实快照）。"""
    snap_root = root / "cutover-snapshots"
    if not snap_root.is_dir():
        return "NO_SNAPSHOTS"
    return "|".join(sorted(p.name for p in snap_root.iterdir()))


def _make_isolated_copy(src: Path, dst: Path) -> None:
    """建立隔离副本：仅复制 _COPY_ITEMS，不复制 .git/docs/scripts/快照目录。"""
    dst.mkdir(parents=True, exist_ok=True)
    for item in _COPY_ITEMS:
        s = src / item
        d = dst / item
        if s.is_dir():
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)


def _force_rmtree(root: Path) -> None:
    """删除目录树（先全量解除只读位，Windows 兼容）。"""
    if not root.exists():
        return
    for p in sorted(root.rglob("*"), reverse=True):
        try:
            mode = stat.S_IREAD | stat.S_IWRITE
            if p.is_dir():
                # Directories need execute/search permission to remain traversable
                # while shutil.rmtree walks them. Root can mask this bug; normal
                # GitHub Actions users cannot.
                mode |= stat.S_IEXEC
            os.chmod(p, mode)
        except OSError:
            pass
    shutil.rmtree(root, ignore_errors=True)
    if root.exists():
        raise AssertionError(f"cleanup failed, residue remains: {root}")


def _next_minor(version: str) -> str:
    major, minor, _ = version.split(".")
    return f"{major}.{int(minor) + 1}.0"


_TARGET_VERSION = _next_minor(_BASE_VERSION)
_TARGET_UPPER = _next_minor(_TARGET_VERSION)


def _switch_copy_to_next(repo: Path) -> None:
    """阶段 2：仅在隔离副本内模拟“当前版本 -> 下一 minor”切换。

    演练目标必须由隔离副本当前 VERSION 动态派生，避免发布后把已经成为
    活动版本的旧目标继续当作 future contract。
    """
    (repo / "VERSION").write_text(f"{_TARGET_VERSION}\n", encoding="utf-8")

    cm_path = repo / "governance" / "compat-matrix.yaml"
    cm_text = cm_path.read_text(encoding="utf-8")
    if f'"{_TARGET_VERSION}"' not in cm_text:
        block = (
            f'  "{_TARGET_VERSION}":\n'
            f'    base_version: "{_TARGET_VERSION}"\n'
            "    governance_ranges:\n"
            f'      workflow: "[{_TARGET_VERSION}, {_TARGET_UPPER})"\n'
            f'      ai-role: "[{_TARGET_VERSION}, {_TARGET_UPPER})"\n'
            '      risk-rule: "[2.0.0, 3.0.0)"\n'
            '      knowledge-rule: "[2.1.0, 3.0.0)"\n'
            f'      role-catalog: "[{_TARGET_VERSION}, {_TARGET_UPPER})"\n'
            f'      orchestration: "[{_TARGET_VERSION}, {_TARGET_UPPER})"\n'
            f'    status_contract: "{_TARGET_VERSION}"\n'
        )
        cm_path.write_text(cm_text.rstrip() + "\n" + block, encoding="utf-8")

    def _bump_version(rel: str, old: str, new: str, count: int = 1) -> None:
        target = repo / rel
        text = target.read_text(encoding="utf-8")
        assert text.count(old) >= count, f"{rel}: pattern {old!r} not found"
        target.write_text(text.replace(old, new, count), encoding="utf-8")

    _bump_version("governance/workflow.yaml", f'version: "{_BASE_VERSION}"', f'version: "{_TARGET_VERSION}"')
    _bump_version("governance/ai-role.yaml", f'version: "{_BASE_VERSION}"', f'version: "{_TARGET_VERSION}"')
    _bump_version("agents/role-catalog.yaml", f'catalog_version: "{_BASE_VERSION}"', f'catalog_version: "{_TARGET_VERSION}"')
    _bump_version("agents/role-catalog.yaml", f'base_version: "{_BASE_VERSION}"', f'base_version: "{_TARGET_VERSION}"')
    _bump_version("governance/orchestration.yaml", f'version: "{_BASE_VERSION}"', f'version: "{_TARGET_VERSION}"')

    source_tpl = repo / "templates" / _BASE_VERSION
    target_tpl = repo / "templates" / _TARGET_VERSION
    shutil.copytree(source_tpl, target_tpl)
    st_path = target_tpl / "status.yaml"
    st_text = st_path.read_text(encoding="utf-8")
    st_text = st_text.replace(f'base_version: "{_BASE_VERSION}"', f'base_version: "{_TARGET_VERSION}"')
    st_text = st_text.replace(f'  version: "{_BASE_VERSION}"', f'  version: "{_TARGET_VERSION}"')
    st_path.write_text(st_text, encoding="utf-8")

    cs_path = repo / "cli" / "config_schemas.py"
    cs_text = cs_path.read_text(encoding="utf-8")
    current_supported = f'"supported_versions": ["{_BASE_VERSION}"]'
    assert cs_text.count(current_supported) >= 4, f"config_schemas {_BASE_VERSION} supported_versions not found"
    cs_text = cs_text.replace(
        current_supported,
        f'"supported_versions": ["{_BASE_VERSION}", "{_TARGET_VERSION}"]',
    )
    cs_path.write_text(cs_text, encoding="utf-8")


class TestB18CutoverRehearsal(unittest.TestCase):
    """隔离副本四阶段演练（设计 §4.2 阶段 1-4 + §4.3 断言）。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="b18_rehearsal_")
        self.tmp = Path(self._tmp)
        self.repo = self.tmp / "repo"
        _make_isolated_copy(BASE, self.repo)
        self.real_fp = _fingerprint(BASE, REAL_WATCH)
        self.real_snap_fp = _snapshot_root_fingerprint(BASE)

    def tearDown(self):
        _force_rmtree(self.tmp)

    # ---- 阶段 1：建立隔离副本 + 快照 ----
    def test_stage1_snapshot_on_isolated_copy(self):
        result = snapshot_cmd.build_snapshot(base_root=self.repo, timestamp=TS_FIXED)
        self.assertFalse(result["already_exists"])
        snap_dir = Path(result["snapshot_dir"])
        self.assertEqual(snap_dir.name, SNAP_DIR_NAME)

        manifest = result["manifest"]
        entries = manifest["entries"]
        # 23 = 7 governance + agents/role-catalog.yaml + 14 active templates + VERSION
        self.assertEqual(manifest["total_entries"], 23)
        paths = {e["path"] for e in entries}
        self.assertIn("agents/role-catalog.yaml", paths)
        self.assertIn("governance/orchestration.yaml", paths)
        self.assertIn("VERSION", paths)
        self.assertIn(f"templates/{_BASE_VERSION}/status.yaml", paths)
        # manifest 自身 sha256 两段式校验
        body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        body_hash = hashlib.sha256(
            __import__("json").dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        self.assertEqual(manifest["manifest_sha256"], body_hash)
        # manifest 落盘且只读位已设
        self.assertTrue((snap_dir / "CUTOVER-SNAPSHOT-MANIFEST.json").is_file())
        # 每项文件存在且 sha256 一致
        for entry in entries:
            f = snap_dir / entry["path"]
            self.assertTrue(f.is_file(), entry["path"])
            self.assertEqual(_sha256_file(f), entry["sha256"], entry["path"])
        # receipt：主副本 evidence/receipts/ + 快照目录内副本
        self.assertIsNotNone(result["receipt_path"])
        self.assertTrue(Path(result["receipt_path"]).is_file())
        self.assertTrue(Path(result["receipt_snapshot_copy"]).is_file())
        # 副本内快照不污染真实 base 仓（T4 后真实 cutover-snapshots/ 为既有产物，目录清单须不变）
        self.assertEqual(_snapshot_root_fingerprint(BASE), self.real_snap_fp)

    # ---- 幂等：同时间戳重复快照不覆盖 ----
    def test_snapshot_idempotent_same_timestamp(self):
        first = snapshot_cmd.build_snapshot(base_root=self.repo, timestamp=TS_FIXED)
        manifest_first = first["manifest"]
        second = snapshot_cmd.build_snapshot(base_root=self.repo, timestamp=TS_FIXED)
        self.assertTrue(second["already_exists"])
        self.assertEqual(second["manifest"]["manifest_sha256"], manifest_first["manifest_sha256"])
        snap_dir = Path(first["snapshot_dir"])
        self.assertEqual(len(list(snap_dir.rglob("CUTOVER-SNAPSHOT-MANIFEST.json"))), 1)

    # ---- 阶段 2→3→4：切换、回滚、清理全流程 ----
    def test_full_flow_switch_rollback_cleanup(self):
        report: list[str] = []

        # ===== 阶段 1：快照（隔离副本内）=====
        snap = snapshot_cmd.build_snapshot(base_root=self.repo, timestamp=TS_FIXED)
        snap_dir = Path(snap["snapshot_dir"])
        report.append(f"阶段1 快照: {snap_dir.name} ({snap['manifest']['total_entries']} entries)")

        # ===== 阶段 2：切换到下一 minor（仅隔离副本）=====
        _switch_copy_to_next(self.repo)
        # VERSION 已切换
        self.assertEqual((self.repo / "VERSION").read_text(encoding="utf-8").strip(), _TARGET_VERSION)
        # compat-matrix 含 5.2.0 条目
        cm_text = (self.repo / "governance" / "compat-matrix.yaml").read_text(encoding="utf-8")
        self.assertIn(f'"{_TARGET_VERSION}"', cm_text)
        # templates/5.2.0/ 已创建且契约字段 5.2.0
        target_status = self.repo / "templates" / _TARGET_VERSION / "status.yaml"
        self.assertTrue(target_status.is_file())
        self.assertIn(f'version: "{_TARGET_VERSION}"', target_status.read_text(encoding="utf-8"))
        # 外层门控：V5.2.0 任务可创建（gate 通过）、V5.1.3（上一代活动契约）被拒
        gate_task_contract(_TARGET_VERSION, base_root=self.repo)  # 不抛
        with self.assertRaises(ConfigLoadError):
            gate_task_contract(_BASE_VERSION, base_root=self.repo)
        report.append(f"阶段2 切换: VERSION={_TARGET_VERSION}, gate({_TARGET_VERSION}) PASS, gate({_BASE_VERSION}) 拒")

        # ===== 阶段 3：从快照回滚（仅隔离副本）=====
        # 先 dry-run：零写入
        dry = rollback_cmd.restore_snapshot(snap_dir, base_root=self.repo, apply=False)
        self.assertTrue(all(not item["restored"] for item in dry["restored"]))
        self.assertEqual((self.repo / "VERSION").read_text(encoding="utf-8").strip(), _TARGET_VERSION)
        report.append(f"阶段3 dry-run: 零写入（VERSION 仍 {_TARGET_VERSION}）")
        # apply 还原
        applied = rollback_cmd.restore_snapshot(snap_dir, base_root=self.repo, apply=True)
        self.assertTrue(all(item["restored"] for item in applied["restored"]))
        # 还原后逐项 sha256 与 manifest 一致（含 agents/role-catalog.yaml）
        for item in applied["restored"]:
            rel = item["path"]
            self.assertEqual(
                _sha256_file(self.repo / rel), item["expected_sha256"], rel
            )
        # VERSION 已还原（快照基线 = 当前 5.1.3）
        self.assertEqual((self.repo / "VERSION").read_text(encoding="utf-8").strip(), _BASE_VERSION)
        # 快照自身 sha256 不变
        verify = rollback_cmd.verify_snapshot(snap_dir)
        self.assertTrue(verify["ok"], verify["errors"])
        report.append("阶段3 回滚: 21 项还原 sha256 一致, 快照 verify ok")

        # ===== §4.3 回滚后四项断言 =====
        # assert_rollback 面向当前活动契约基线（VERSION 动态读取）；演练基线为当前版本：
        #   下一 minor 版本新写入被拒 / 当前版本恢复为唯一可写契约 / 未声明版本静态旧任务仍被拒
        _orig_consts = (
            rollback_cmd.PREVIOUS_VERSION,
            rollback_cmd.LEGACY_VERSION,
        )
        try:
            rollback_cmd.PREVIOUS_VERSION = _BASE_VERSION
            rollback_cmd.LEGACY_VERSION = "9.9.9"
            assertions = rollback_cmd.assert_rollback(snap_dir, base_root=self.repo)
        finally:
            (
                rollback_cmd.PREVIOUS_VERSION,
                rollback_cmd.LEGACY_VERSION,
            ) = _orig_consts
        self.assertTrue(assertions["all_ok"], assertions)
        for name, check in assertions["checks"].items():
            self.assertTrue(check["ok"], f"{name}: {check['detail']}")
            report.append(f"断言[{name}]: PASS")
        # 静态旧任务不可混写：未声明版本被拒（与 V5.1.3 不匹配）
        with self.assertRaises(ConfigLoadError):
            gate_task_contract("9.9.9", base_root=self.repo)
        report.append("断言[未声明版本静态旧任务仍被拒]: PASS（gate 抛 VERSION_MISMATCH）")

        # ===== 阶段 4：清理副本 + 真实 base 仓指纹不变 =====
        _force_rmtree(self.repo)
        self.assertFalse(self.repo.exists())
        # 真实 base 仓关键文件指纹不变（演练未触碰任何真实文件）
        self.assertEqual(_fingerprint(BASE, REAL_WATCH), self.real_fp)
        # 真实 base cutover-snapshots/ 目录清单不变（T4 既有快照未被演练增删）
        self.assertEqual(_snapshot_root_fingerprint(BASE), self.real_snap_fp)
        report.append("阶段4 清理: 副本已删, 真实 base 仓 9 文件指纹不变")

        # ===== 演练报告输出 =====
        print("\n===== B-18 cutover 隔离副本演练报告 =====")
        for line in report:
            print(f"  {line}")
        print("=========================================")


if __name__ == "__main__":
    unittest.main(verbosity=2)
