# -*- coding: utf-8 -*-
"""V5.1.3 SKILL semantic regressions.

Record-first removes workflow bookkeeping from daily roles, but must not remove
professional reasoning boundaries. These tests keep the compact role packs
small while guarding their core engineering semantics and keep reusable method
skills aligned with the active 5.1.3 contract.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parents[2]
ACTIVE_VERSION = (BASE / "VERSION").read_text(encoding="utf-8").strip()


def read(path: str) -> str:
    return (BASE / path).read_text(encoding="utf-8")


class TestRoleCatalogMetadata(unittest.TestCase):
    def test_catalog_metadata_matches_skill_frontmatter(self):
        catalog = yaml.safe_load((BASE / "agents" / "role-catalog.yaml").read_text(encoding="utf-8"))
        for role in catalog["roles"]:
            text = (BASE / role["skill_path"]).read_text(encoding="utf-8-sig")
            self.assertTrue(text.startswith("---\n"), role["workflow_role"])
            front = yaml.safe_load(text.split("---\n", 2)[1])
            self.assertEqual(front.get("id"), role["workflow_role"], role["workflow_role"])
            self.assertEqual(front.get("type"), role["type"], role["workflow_role"])
            self.assertEqual(str(front.get("version")), ACTIVE_VERSION, role["workflow_role"])



class TestWorkflowRoleSemantics(unittest.TestCase):
    def assertContainsAll(self, path: str, *needles: str):
        text = read(path)
        for needle in needles:
            self.assertIn(needle, text, f"{path}: missing semantic anchor {needle!r}")

    def test_requirement_keeps_fact_assumption_decision_boundary(self):
        self.assertContainsAll(
            "skills/tp-requirement-analysis/SKILL.md",
            "确认事实 / AI 假设 / 待确认决策 / 未知现状",
            "不得静默升级为事实",
            "范围/非范围",
            "验收条件",
            "需求分析允许发生在正式 Task 创建之前",
        )

    def test_product_keeps_product_reasoning_and_role_boundary(self):
        self.assertContainsAll(
            "skills/tp-product-design/SKILL.md",
            "用户角色",
            "异常场景",
            "用户反馈",
            "不决定技术架构",
            "不自行发明业务规则",
        )

    def test_architecture_keeps_planning_risk_and_design_checklist(self):
        self.assertContainsAll(
            "skills/tp-architecture-design/SKILL.md",
            "governance/risk-rule.yaml",
            "governance/planning-strategy.yaml",
            "并发",
            "事务",
            "幂等",
            "acceptance criteria",
            "knowledge_target",
            "缺失默认只是 WARN",
        )

    def test_architecture_review_is_compact_but_professional(self):
        self.assertContainsAll(
            "skills/tp-architecture-review/SKILL.md",
            "不是所有 L2/L3 的固定门禁",
            "不要重新扫描整个仓库",
            "数据、并发、事务、幂等风险",
            "权限、安全、隐私",
            "回滚、恢复或补偿策略",
            "PASS / REVISE / BLOCKED",
        )

    def test_development_keeps_scope_truth_and_production_safety(self):
        self.assertContainsAll(
            "skills/tp-development-engineering/SKILL.md",
            "不自行改变业务目标",
            "开发自测不是独立验收",
            "production read",
            "DML、DDL",
            "动作级 + 环境级",
            "不能因为任务目标明确就自动获得执行授权",
        )

    def test_verification_keeps_independent_review_matrix(self):
        self.assertContainsAll(
            "skills/tp-verification-engineering/SKILL.md",
            "真实代码/diff/配置",
            "错误处理、边界条件、并发、事务、幂等",
            "安全与权限",
            "兼容与运行",
            "证据质量",
            "PASS_STALE",
            "NEEDS_FIX",
            "FAIL",
        )

    def test_delivery_keeps_truthful_knowledge_boundaries(self):
        self.assertContainsAll(
            "skills/tp-delivery-convergence/SKILL.md",
            "knowledge_target=CONFIRMED",
            "90-sources",
            "DEFERRED",
            "不重新做质量裁决",
            "knowledge_required=true",
        )

    def test_tp_wiki_keeps_low_cost_semantic_truth_guardrails(self):
        self.assertContainsAll(
            "agents/tp-wiki/SKILL.md",
            "Currentity 分类",
            "CURRENT / COMPATIBILITY / RECOVERY / DEPRECATED / HISTORICAL",
            "Existence ≠ Authority",
            "Responsibility Attribution",
            "Pipeline Stage Ownership",
            "Wiki 服务检索与研发质量",
            "不为形式评分扩写低价值内容",
            "一个源码文件不等于一篇 Wiki",
            "initial_build_effective_coverage_min",
            "不得为了 100% 调分母",
        )

    def test_wiki_rules_make_l4_adversarial_without_document_bloat(self):
        content = read("wiki/rules/content-standard.md")
        gates = read("wiki/rules/quality-gates.md")
        rebuild = read("automation/wiki/full-rebuild.md")
        for token in ("CURRENT", "COMPATIBILITY", "Existence ≠ Authority", "Responsibility Attribution", "Pipeline Stage Ownership"):
            self.assertIn(token, content)
        for token in ("对抗式语义检查", "竞争/旧路径", "enforce", "流水线"):
            self.assertIn(token, gates)
        self.assertIn("能力/子系统聚类", rebuild)
        self.assertIn("wiki audit --repo <id> --full", rebuild)
        self.assertIn("不得为了 100% 调分母", rebuild)
        self.assertIn("BUILD_INCOMPLETE", rebuild)
        self.assertIn("具体 function/entrypoint", gates)

    def test_compact_roles_still_reject_old_daily_bookkeeping(self):
        for role in (
            "tp-requirement-analysis",
            "tp-product-design",
            "tp-architecture-design",
            "tp-architecture-review",
            "tp-development-engineering",
            "tp-verification-engineering",
            "tp-delivery-convergence",
        ):
            text = read(f"skills/{role}/SKILL.md")
            self.assertNotIn("stage_handoff:", text, role)
            self.assertNotIn("handoff.json.next_prompt", text, role)
            self.assertNotIn("每阶段显式 projection refresh", text, role)


class TestReusableMethodSkills(unittest.TestCase):
    METHOD_SKILLS = (
        "assumption-management",
        "delivery-planning",
        "implementation-control",
        "knowledge-capture",
        "requirement-clarification",
        "systematic-debugging",
        "task-decomposition",
        "technical-review",
        "testing-strategy",
    )

    def test_all_method_skills_are_current_record_first_contract(self):
        forbidden = (
            "V5.1." + "0", "V5.1." + "1", "Qoder", "CodeBuddy", "Codex",
            "DEVELOPING", "VERIFYING", "CHANGE_CONFIRMING",
            "handoff.json", "next_prompt",
        )
        for skill in self.METHOD_SKILLS:
            text = read(f"skills/{skill}/SKILL.md")
            match = re.search(r"(?m)^version:\s*([\d.]+)\s*$", text)
            self.assertIsNotNone(match, skill)
            self.assertEqual(match.group(1), ACTIVE_VERSION, skill)
            self.assertIn("Record-first", text, skill)
            for token in forbidden:
                self.assertNotIn(token, text, f"{skill}: stale active-contract token {token}")

    def test_method_skills_preserve_high_value_safety(self):
        self.assertContains("skills/assumption-management/SKILL.md", "不得作为默认事实继续编码")
        self.assertContains("skills/implementation-control/SKILL.md", "production read")
        self.assertContains("skills/technical-review/SKILL.md", "真实代码/diff/配置")
        self.assertContains("skills/testing-strategy/SKILL.md", "PASS_STALE")
        self.assertContains("skills/knowledge-capture/SKILL.md", "90-sources")

    def test_active_method_skills_are_version_purity_scanned(self):
        import importlib.util
        scanner_path = BASE / "scripts" / "check_version_consistency.py"
        spec = importlib.util.spec_from_file_location("v513_skill_purity", scanner_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertFalse(module._is_allowed_history("skills/technical-review/SKILL.md"))

    def assertContains(self, path: str, needle: str):
        self.assertIn(needle, read(path), f"{path}: missing {needle!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
