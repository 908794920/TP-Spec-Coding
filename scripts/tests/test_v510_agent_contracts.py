# -*- coding: utf-8 -*-
"""V5.1.3 Agent 契约测试：10 个 SKILL.md 版本、role-catalog hash、无旧模板引用。

Pure stdlib unittest; offline. 验证：
- 10 个活动 Agent SKILL.md front matter version == 5.1.3
- SKILL.md 正文无旧版模板路径引用（历史版本模板已移除）
- role-catalog content_sha256 与规范化 SKILL.md 重算一致（UTF-8 无 BOM、LF、单末尾换行）

Run:
    python scripts/tests/test_v510_agent_contracts.py
"""

from __future__ import annotations

import hashlib
import re
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent  # ai-work-base
sys.path.insert(0, str(BASE))

from cli.config_loader import load_config  # noqa: E402

AGENTS = (
    "tp-requirement-analysis",
    "tp-architecture-design",
    "tp-architecture-review",
    "tp-product-design",
    "tp-development-engineering",
    "tp-verification-engineering",
    "tp-delivery-convergence",
    "tp-base-maintenance",
    "tp-knowledge",
    "tp-wiki",
)


def normalized_sha256(path: Path) -> str:
    """role-catalog 规范化 hash 契约：UTF-8 无 BOM、LF、恰好一个末尾换行。"""
    text = path.read_text(encoding="utf-8")
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r\n", "\n")
    text = text.rstrip("\n") + "\n"
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


ACTIVE_VERSION = (BASE / "VERSION").read_text(encoding="utf-8").strip()


def role_skill_path(role_id: str) -> Path:
    catalog = load_config(
        "agents/role-catalog.yaml", schema_name="role-catalog", base_root=str(BASE)
    )
    by_role = {r["workflow_role"]: r for r in catalog["roles"]}
    return BASE / by_role[role_id]["skill_path"]


class TestAgentContracts(unittest.TestCase):
    def test_all_skills_version_511(self):
        for agent in AGENTS:
            path = role_skill_path(agent)
            self.assertTrue(path.is_file(), path)
            text = path.read_text(encoding="utf-8")
            m = re.search(r"(?m)^version:\s*([\d.]+)", text)
            self.assertIsNotNone(m, f"{agent}: no version in front matter")
            self.assertEqual(m.group(1).strip(), ACTIVE_VERSION, agent)

    def test_no_legacy_template_path_in_skills(self):
        legacy_tpl = "templates/5.0." + "6"
        legacy_ver = "5.0." + "6"
        for agent in AGENTS:
            path = role_skill_path(agent)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(legacy_tpl, text, agent)
            self.assertNotIn(legacy_ver, text, agent)

    def test_role_catalog_hashes_match(self):
        catalog = load_config(
            "agents/role-catalog.yaml", schema_name="role-catalog", base_root=str(BASE)
        )
        by_role = {r["workflow_role"]: r for r in catalog["roles"]}
        for agent in AGENTS:
            entry = by_role.get(agent)
            self.assertIsNotNone(entry, f"{agent} missing in role-catalog")
            skill_path = BASE / entry["skill_path"]
            self.assertTrue(skill_path.is_file(), skill_path)
            self.assertEqual(
                normalized_sha256(skill_path),
                entry["content_sha256"],
                f"{agent} content_sha256 mismatch",
            )

    def test_role_catalog_version_511(self):
        catalog = load_config(
            "agents/role-catalog.yaml", schema_name="role-catalog", base_root=str(BASE)
        )
        self.assertEqual(catalog["catalog_version"], ACTIVE_VERSION)
        self.assertEqual(catalog["base_version"], ACTIVE_VERSION)


if __name__ == "__main__":
    unittest.main(verbosity=2)
