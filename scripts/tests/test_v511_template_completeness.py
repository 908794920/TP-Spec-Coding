# -*- coding: utf-8 -*-
"""模板完整性回归：当前单活动契约模板集和 canonical requirement 工件可解析。

Pure stdlib unittest; offline. 验证：
- 当前 templates/<active> 包含 canonical requirement 和必要按需工件；
- 5 个按需工件均有可解析的最小 YAML front matter；
- artifact_contract.version == 当前活动版本；
- Requirement Frontier 只扩展既有可选业务记录，不新增工件或 Runtime schema；
- requirement-decisions 保持业务记录而非 front matter 机器状态；
- 当前版本是唯一活动模板目录（单活动契约）。

Run:
    python scripts/tests/test_v511_template_completeness.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

BASE = Path(__file__).resolve().parent.parent.parent  # tp-spec-base

REQUIRED_FILES = (
    "README.md",
    "task.md",
    "implementation.md",
    "acceptance.md",
    "codex-review.md",
    "quality-and-knowledge.md",
    "status.yaml",
    "handoff.json",
    "requirement.md",
    "requirement-clarifications.md",
    "requirement-decisions.md",
    "architecture-review.md",
    "requirement-test-guide.md",
)

NEW_ARTIFACTS = (
    "requirement.md",
    "requirement-clarifications.md",
    "requirement-decisions.md",
    "architecture-review.md",
    "requirement-test-guide.md",
)

ACTIVE_VERSION = (BASE / "VERSION").read_text(encoding="utf-8").strip()


def _parse_front_matter(path: Path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        raise AssertionError(f"{path.name}: no front matter opener")
    end = text.find("\n---", 4)
    if end < 0:
        raise AssertionError(f"{path.name}: no front matter closer")
    body = text[4:end]
    if yaml is None:
        raise AssertionError(f"{path.name}: PyYAML unavailable, cannot parse")
    data = yaml.safe_load(body)
    if not isinstance(data, dict):
        raise AssertionError(f"{path.name}: front matter is not a mapping")
    return data


class TestTemplateCompleteness(unittest.TestCase):
    def test_template_dir_is_single_active(self):
        tpl = BASE / "templates"
        dirs = {p.name for p in tpl.iterdir() if p.is_dir()}
        self.assertEqual(dirs, {ACTIVE_VERSION})

    def test_required_files_present(self):
        d = BASE / "templates" / ACTIVE_VERSION
        for name in REQUIRED_FILES:
            self.assertTrue((d / name).is_file(), name)

    def test_front_matter_fields(self):
        """Optional business artifacts keep only minimal machine identity."""
        for name in NEW_ARTIFACTS:
            p = BASE / "templates" / ACTIVE_VERSION / name
            data = _parse_front_matter(p)
            for field in ("artifact", "task_id", "artifact_contract"):
                self.assertIn(field, data, f"{name}: missing {field}")
            self.assertEqual(data["artifact_contract"]["version"], ACTIVE_VERSION, name)
            self.assertNotIn("stage_handoff", data, name)

    def test_requirement_test_guide_structure(self):
        """Test guide is optional prose, not a lifecycle state machine."""
        p = BASE / "templates" / ACTIVE_VERSION / "requirement-test-guide.md"
        data = _parse_front_matter(p)
        self.assertEqual(data["artifact"], "requirement-test-guide")
        self.assertNotIn("lifecycle", data)
        self.assertNotIn("section_owners", data)
        text = p.read_text(encoding="utf-8")
        for heading in ("## 前置条件", "## 非可视化验证", "## 可视化验证", "## 回归范围"):
            self.assertIn(heading, text)

    def test_requirement_decisions_is_business_record_not_machine_form(self):
        p = BASE / "templates" / ACTIVE_VERSION / "requirement-decisions.md"
        data = _parse_front_matter(p)
        self.assertNotIn("decisions", data)
        text = p.read_text(encoding="utf-8")
        self.assertIn("只记录真实发生", text)
        self.assertIn("| decision_id | 问题 | prerequisites | status | blocking | recommendation | human decision / 受控默认 | impact | evidence_refs | supersedes / history |", text)
        self.assertIn("保留原 decision", text)

    def test_requirement_clarifications_distinguishes_all_blockers_from_frontier(self):
        p = BASE / "templates" / ACTIVE_VERSION / "requirement-clarifications.md"
        data = _parse_front_matter(p)
        self.assertEqual(data["blocking_open"], 0)
        self.assertIsInstance(data["blocking_open"], int)
        self.assertNotIn("current_frontier", data)
        text = p.read_text(encoding="utf-8")
        self.assertIn("全部未解决", text)
        self.assertIn("不是 Current Frontier 的条目数", text)
        for heading in ("## Fact Investigation", "## Current Frontier", "## Deferred Decisions"):
            self.assertIn(heading, text)

    def test_architecture_review_decision_enum(self):
        p = BASE / "templates" / ACTIVE_VERSION / "architecture-review.md"
        data = _parse_front_matter(p)
        self.assertEqual(data["review"]["kind"], "architecture")
        self.assertIn(data["review"]["decision"], ("DRAFT", "PASS", "REVISE", "BLOCKED"))
        text = p.read_text(encoding="utf-8")
        for d in ("DRAFT", "PASS", "REVISE", "BLOCKED"):
            self.assertIn(d, text)

    def test_upgraded_templates_reference_v511_artifacts(self):
        """Current templates are optional business artifacts, not a cross-referenced form set."""
        root = BASE / "templates" / ACTIVE_VERSION
        task = (root / "task.md").read_text(encoding="utf-8")
        self.assertIn("不承担阶段门禁", task)
        for name in (
            "requirement.md", "requirement-clarifications.md", "requirement-decisions.md",
            "architecture-review.md", "requirement-test-guide.md", "implementation.md",
            "codex-review.md", "quality-and-knowledge.md",
        ):
            text = (root / name).read_text(encoding="utf-8")
            self.assertNotIn("stage_handoff", text, name)
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("按需工件", readme)
        self.assertIn("NEW → ACTIVE → COMPLETED", readme)
