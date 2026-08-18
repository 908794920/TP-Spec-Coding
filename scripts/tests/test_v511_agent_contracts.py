# -*- coding: utf-8 -*-
"""Role-contract regression lineage, updated for V5.1.3 Record-first.

The file name is retained so historical CI entry points remain stable. The
active invariant is now low-overhead role behavior, not the old L2/L3 mandatory
review/handoff protocol.
"""
from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent.parent
ACTIVE_VERSION = (BASE / "VERSION").read_text(encoding="utf-8").strip()
ALL_AGENTS = (
    "tp-spec-coding", "tp-software-lifecycle", "tp-project-autonomy",
    "tp-base-maintenance", "tp-knowledge", "tp-wiki",
    "tp-product-manager", "tp-software-architect", "tp-tech-lead",
    "tp-security-engineer", "tp-development-engineer", "tp-database-engineer",
    "tp-test-engineer", "tp-code-reviewer", "tp-integration-engineer",
)


def normalized_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").rstrip("\n") + "\n"
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def read_skill(agent: str) -> str:
    catalog = yaml.safe_load((BASE / "agents" / "role-catalog.yaml").read_text(encoding="utf-8"))
    item = next(r for r in catalog["roles"] if r["workflow_role"] == agent)
    return (BASE / item["skill_path"]).read_text(encoding="utf-8")


class TestRoleCatalog(unittest.TestCase):
    def test_catalog_has_expected_roles_and_hashes(self):
        catalog = yaml.safe_load((BASE / "agents" / "role-catalog.yaml").read_text(encoding="utf-8"))
        self.assertEqual(catalog["catalog_version"], ACTIVE_VERSION)
        self.assertEqual({r["workflow_role"] for r in catalog["roles"]}, set(ALL_AGENTS))
        for role in catalog["roles"]:
            path = BASE / role["skill_path"]
            self.assertTrue(path.is_file())
            self.assertEqual(role["content_sha256"], normalized_sha256(path))


class TestAgentSkills(unittest.TestCase):
    def test_agent_versions(self):
        for agent in ALL_AGENTS:
            text = read_skill(agent)
            m = re.search(r"(?m)^version:\s*([\d.]+)", text)
            self.assertIsNotNone(m, agent)
            self.assertEqual(m.group(1), ACTIVE_VERSION, agent)

    def test_requirement_analysis_is_pretask_and_low_bookkeeping(self):
        text = read_skill("tp-product-manager")
        self.assertIn("需求分析允许发生在正式 Task 创建之前", text)
        self.assertIn("没有 TaskId", text)
        self.assertIn("task checkpoint --phase requirement|product", text)
        self.assertIn("不创建空文档", text)
        self.assertNotIn("max_search_rounds", text)

    def test_architecture_review_is_risk_triggered_not_default_gate(self):
        design = read_skill("tp-software-architect")
        review = read_skill("tp-software-architect")
        self.assertIn("只有高风险", design)
        self.assertIn("缺失默认只是 WARN", design)
        self.assertIn("不是所有 L2/L3 的固定门禁", review)
        self.assertNotIn("强制 PASS", design)

    def test_roles_do_business_not_projection_bookkeeping(self):
        for agent in (
            "tp-software-architect", "tp-development-engineer",
            "tp-test-engineer", "tp-integration-engineer",
        ):
            text = read_skill(agent)
            self.assertNotIn("stage_handoff:", text, agent)
        self.assertIn("测试角色不自行 `task complete`", read_skill("tp-test-engineer"))
        integration = read_skill("tp-integration-engineer")
        self.assertIn("Delivery Result", integration)
        self.assertIn("不重新裁决 PASS/FAIL", integration)


class TestCostTiering(unittest.TestCase):
    def test_l0_l3_are_risk_labels_not_fixed_expensive_flows(self):
        wf = yaml.safe_load((BASE / "governance" / "workflow.yaml").read_text(encoding="utf-8"))
        for level in ("L0", "L1", "L2", "L3"):
            self.assertIn(level, wf["levels"])
            self.assertEqual([x["state"] for x in wf["levels"][level]["flow"]], ["NEW", "ACTIVE", "COMPLETED"])
        self.assertEqual(wf["rules"]["architecture_review"]["default"], "optional")


if __name__ == "__main__":
    unittest.main(verbosity=2)
