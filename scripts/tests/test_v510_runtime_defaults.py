# -*- coding: utf-8 -*-
"""V5.1.0 运行时默认值测试：核心 CLI 模块无旧版本硬编码、默认版本来自 VERSION。

Pure stdlib unittest; offline. 验证：
- commit/project/receipt/review_preflight/snapshot/rollback 模块源码无旧版本字面量
- 各模块 ACTIVE_CONTRACT / 默认版本与 VERSION 文件一致

Run:
    python scripts/tests/test_v510_runtime_defaults.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent  # tp-spec-base
sys.path.insert(0, str(BASE))

from cli import commit_cmd  # noqa: E402
from cli import snapshot_cmd  # noqa: E402
from cli import rollback_cmd  # noqa: E402
from cli.config_loader import read_base_version  # noqa: E402
from cli.version import next_version  # noqa: E402


class TestRuntimeDefaults(unittest.TestCase):
    def test_commit_active_contract_matches_version(self):
        self.assertEqual(commit_cmd.ACTIVE_CONTRACT, read_base_version(BASE))

    def test_snapshot_target_is_next_version_not_legacy(self):
        # 快照目标 = 当前版本的下一个 minor（cutover 演练目标，动态计算不硬编码）
        current = read_base_version(BASE)
        major, minor, _ = current.split(".")
        expected = f"{major}.{int(minor) + 1}.0"
        self.assertEqual(snapshot_cmd.next_version(BASE), expected)
        self.assertEqual(next_version(BASE), expected)
        # 快照源模板目录 = templates/<active>
        self.assertEqual(read_base_version(BASE), (BASE / "VERSION").read_text(encoding="utf-8").strip())

    def test_rollback_previous_is_active_version(self):
        self.assertEqual(rollback_cmd.PREVIOUS_VERSION, read_base_version(BASE))
        # 未声明版本用于静态旧任务拒绝断言
        self.assertEqual(rollback_cmd.LEGACY_VERSION, "9.9.9")

    def test_no_legacy_literal_in_core_modules(self):
        """核心运行时模块源码不得包含旧版本字面量（允许拼接与动态读取）。"""
        legacy = "5.0." + "6"
        modules = (
            "cli/commit_cmd.py",
            "cli/project_cmd.py",
            "cli/projection_cmd.py",
            "cli/receipt_cmd.py",
            "cli/review_preflight.py",
            "cli/snapshot_cmd.py",
            "cli/rollback_cmd.py",
            "cli/task_cmd.py",
            "cli/config_schemas.py",
        )
        for rel in modules:
            text = (BASE / rel).read_text(encoding="utf-8")
            self.assertNotIn('"' + legacy + '"', text, rel)
            self.assertNotIn("'" + legacy + "'", text, rel)


if __name__ == "__main__":
    unittest.main(verbosity=2)
