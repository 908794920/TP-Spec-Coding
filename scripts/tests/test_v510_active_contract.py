# -*- coding: utf-8 -*-
"""V5.1.3 活动契约测试：project init 默认版本、gate 门控、compat-matrix 收敛。

Pure stdlib unittest; offline. 验证：
- `project init` 未传 --base-version 时默认写入 5.1.3（来自 VERSION）
- gate_task_contract 对 5.1.3 通过、对未声明版本拒绝
- compat-matrix 仅声明 5.1.3 一个活动契约
- config_schemas 的 supported_versions 仅含 5.1.3

Run:
    python scripts/tests/test_v510_active_contract.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent  # ai-work-base
sys.path.insert(0, str(BASE))

from cli.config_loader import gate_task_contract  # noqa: E402
from cli.config_loader import ConfigLoadError  # noqa: E402
from cli.config_loader import load_config  # noqa: E402
from cli.config_loader import read_base_version  # noqa: E402
from cli import config_schemas  # noqa: E402

ACTIVE_VERSION = read_base_version(BASE)


class TestActiveContract(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="v510_active_")
        self.tmp = Path(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_version_file_is_510(self):
        self.assertEqual(read_base_version(BASE), ACTIVE_VERSION)

    def test_project_init_default_version(self):
        """project init 未传 --base-version 时，DB 中 base_version 应为 5.1.3。"""
        from cli import db as dbmod
        from cli import project_cmd
        import json

        registry = self.tmp / "registry.local.json"
        registry.write_text(json.dumps({"projects": []}), encoding="utf-8")
        args = type("Args", (), {
            "id": "v510proj",
            "name": None,
            "root": str(self.tmp),
            "base_version": None,
            "db": None,
            "registry": str(registry),
        })()
        rc = project_cmd.cmd_project_init(args)
        self.assertEqual(rc, 0)
        db_path = self.tmp / ".ai-work" / "db" / "v510proj.db"
        self.assertTrue(db_path.is_file())
        conn = dbmod.connect(db_path)
        try:
            row = conn.execute("SELECT * FROM project WHERE project_id='v510proj'").fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["base_version"], ACTIVE_VERSION)

    def test_gate_accepts_active_version(self):
        gate_task_contract(ACTIVE_VERSION, base_root=str(BASE))  # no raise

    def test_gate_rejects_undeclared_version(self):
        major, minor, _ = ACTIVE_VERSION.split(".")
        future = f"{major}.{int(minor) + 1}.0"
        for bad in ("9.9.9", future):
            with self.assertRaises(ConfigLoadError) as ctx:
                gate_task_contract(bad, base_root=str(BASE))
            self.assertEqual(ctx.exception.error_code.value, "VERSION_MISMATCH")

    def test_compat_matrix_only_active_contract(self):
        matrix = load_config(
            "governance/compat-matrix.yaml", schema_name="compat-matrix", base_root=str(BASE)
        )
        contracts = set(matrix["contracts"].keys())
        self.assertEqual(contracts, {ACTIVE_VERSION})

    def test_config_schemas_supported_versions_only_510(self):
        for name in ("workflow", "ai-role", "role-catalog", "status-template"):
            schema = config_schemas.get_schema(name)
            self.assertEqual(schema["supported_versions"], [ACTIVE_VERSION], name)

    def test_project_init_rejects_legacy_version(self):
        """显式 --base-version 传旧版本必须拒绝（RC!=0），不写库。"""
        from cli import project_cmd
        import json

        legacy = "5.0." + "6"
        registry = self.tmp / "reg_legacy.json"
        registry.write_text(json.dumps({"projects": []}), encoding="utf-8")
        args = type("Args", (), {
            "id": "oldproj",
            "name": None,
            "root": str(self.tmp / "oldroot"),
            "base_version": legacy,
            "db": None,
            "registry": str(registry),
        })()
        rc = project_cmd.cmd_project_init(args)
        self.assertNotEqual(rc, 0)
        self.assertFalse((self.tmp / "oldroot" / ".ai-work" / "db" / "oldproj.db").is_file())

    def test_project_init_rejects_future_version(self):
        """显式 --base-version 传未来版本必须拒绝。"""
        from cli import project_cmd
        import json

        registry = self.tmp / "reg_future.json"
        registry.write_text(json.dumps({"projects": []}), encoding="utf-8")
        args = type("Args", (), {
            "id": "futureproj",
            "name": None,
            "root": str(self.tmp / "futureroot"),
            "base_version": f"{ACTIVE_VERSION.split('.')[0]}.{int(ACTIVE_VERSION.split('.')[1]) + 1}.0",
            "db": None,
            "registry": str(registry),
        })()
        rc = project_cmd.cmd_project_init(args)
        self.assertNotEqual(rc, 0)
        self.assertFalse((self.tmp / "futureroot" / ".ai-work" / "db" / "futureproj.db").is_file())

    def test_task_create_rejects_non_active_project(self):
        """非活动版本项目上创建任务必须拒绝。"""
        from cli import db as dbmod
        from cli import task_cmd

        # 构造一个 base_version=旧版本 的 project 记录
        db_path = self.tmp / "legacy.db"
        conn = dbmod.connect(db_path)
        try:
            dbmod.init_schema(conn)
            now = dbmod.now_iso()
            with dbmod.transactional(conn):
                conn.execute(
                    "INSERT INTO project (project_id, project_name, root_path, base_version, schema_version, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                    ("legacyproj", "legacy", str(self.tmp), "5.0." + "6", dbmod.EXPECTED_SCHEMA_VERSION, now, now),
                )
        finally:
            conn.close()
        args = type("Args", (), {
            "id": "TASK-LEGACY-001",
            "project": "legacyproj",
            "risk": "L1",
            "flow": "L1",
            "db": str(db_path),
            "title": None,
        })()
        rc = task_cmd.cmd_task_create(args)
        self.assertNotEqual(rc, 0)

    def test_governance_files_declare_510(self):
        for rel, schema_name in (
            ("governance/workflow.yaml", "workflow"),
            ("governance/ai-role.yaml", "ai-role"),
            ("agents/role-catalog.yaml", "role-catalog"),
        ):
            data = load_config(rel, schema_name=schema_name, base_root=str(BASE))
            field = config_schemas.get_schema(schema_name)["version_field"]
            self.assertEqual(data.get(field), ACTIVE_VERSION, rel)


if __name__ == "__main__":
    unittest.main(verbosity=2)
