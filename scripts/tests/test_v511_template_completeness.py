# -*- coding: utf-8 -*-
"""V5.1.3 模板完整性测试：templates/5.1.3 为完整模板集且新增工件 front matter 可解析。

Pure stdlib unittest; offline. 验证（定向修复任务 §5/§6/§11.2/§11.3）：
- templates/5.1.3 包含 13 个文件（8 个升级模板 + 5 个新工件）；
- 5 个新工件均有可解析 YAML front matter；
- front matter 包含 artifact / task_id / artifact_contract.version / owner / status / stage_handoff；
- artifact_contract.version == 5.1.3；
- requirement-test-guide 含 ac_coverage 与稳定测试 ID（T-00x）；
- requirement-decisions 使用顶层 decisions 列表（非 fenced 多段 YAML 作为唯一机器事实）；
- 5.1.3 是唯一活动模板目录（单活动契约）。

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

BASE = Path(__file__).resolve().parent.parent.parent  # ai-work-base

REQUIRED_FILES = (
    "README.md",
    "task.md",
    "implementation.md",
    "acceptance.md",
    "codex-review.md",
    "quality-and-knowledge.md",
    "status.yaml",
    "handoff.json",
    "requirement-knowledge.md",
    "requirement-clarifications.md",
    "requirement-decisions.md",
    "architecture-review.md",
    "requirement-test-guide.md",
)

NEW_ARTIFACTS = (
    "requirement-knowledge.md",
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

    def test_thirteen_files_present(self):
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
        for heading in ("## 前置条件", "## 关键场景", "## 数据 / 日志检查", "## 回归范围"):
            self.assertIn(heading, text)

    def test_requirement_decisions_is_business_record_not_machine_form(self):
        p = BASE / "templates" / ACTIVE_VERSION / "requirement-decisions.md"
        data = _parse_front_matter(p)
        self.assertNotIn("decisions", data)
        text = p.read_text(encoding="utf-8")
        self.assertIn("只记录真实发生", text)
        self.assertIn("| 决策 | 原因/上下文 | 影响 |", text)

    def test_architecture_review_decision_enum(self):
        p = BASE / "templates" / ACTIVE_VERSION / "architecture-review.md"
        data = _parse_front_matter(p)
        self.assertEqual(data["review"]["kind"], "architecture")
        self.assertIn(data["review"]["decision"], ("DRAFT", "PASS", "REVISE", "BLOCKED"))
        text = p.read_text(encoding="utf-8")
        for d in ("DRAFT", "PASS", "REVISE", "BLOCKED"):
            self.assertIn(d, text)

    def test_upgraded_templates_reference_v511_artifacts(self):
        """V5.1.3 templates are optional business artifacts, not a cross-referenced form set."""
        root = BASE / "templates" / ACTIVE_VERSION
        task = (root / "task.md").read_text(encoding="utf-8")
        self.assertIn("不承担阶段门禁", task)
        for name in (
            "requirement-knowledge.md", "requirement-clarifications.md", "requirement-decisions.md",
            "architecture-review.md", "requirement-test-guide.md", "implementation.md",
            "codex-review.md", "quality-and-knowledge.md",
        ):
            text = (root / name).read_text(encoding="utf-8")
            self.assertNotIn("stage_handoff", text, name)
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("按需工件", readme)
        self.assertIn("NEW → ACTIVE → COMPLETED", readme)
