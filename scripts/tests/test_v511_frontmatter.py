# -*- coding: utf-8 -*-
"""V5.1.3 A-01 front matter CRLF/LF/BOM 兼容测试。

覆盖（任务书 §六 测试矩阵）：
- UTF-8 + LF / UTF-8 + CRLF / BOM + LF / BOM + CRLF 均可解析与改写；
- 缺失 front matter 正确失败；
- 改写保持原换行风格与 BOM 状态（digest 稳定性）。

纯 stdlib unittest、离线、无污染。强断言：退出语义、内容字节级、状态终值。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent  # tp-spec-base
sys.path.insert(0, str(BASE))

from cli import frontmatter  # noqa: E402
from cli.frontmatter import FRONTMATTER_RE  # noqa: E402


LF_TPL = "---\ntitle: \"x\"\nstatus: \"draft\"\n---\n\nbody text\n"
CRLF_TPL = "---\r\ntitle: \"x\"\r\nstatus: \"draft\"\r\n---\r\n\r\nbody text\r\n"
BOM_LF_TPL = "\ufeff" + LF_TPL
BOM_CRLF_TPL = "\ufeff" + CRLF_TPL


class TestFrontmatterParse(unittest.TestCase):
    def test_parse_lf(self):
        self.assertTrue(frontmatter.has(LF_TPL))
        parts = frontmatter.split(LF_TPL)
        self.assertIsNotNone(parts)
        front, body, eol = parts
        self.assertEqual(eol, "\n")
        self.assertIn('title: "x"', front)
        self.assertEqual(body, "\nbody text\n")

    def test_parse_crlf(self):
        self.assertTrue(frontmatter.has(CRLF_TPL))
        parts = frontmatter.split(CRLF_TPL)
        self.assertIsNotNone(parts)
        front, body, eol = parts
        self.assertEqual(eol, "\r\n")
        self.assertIn('title: "x"', front)
        self.assertTrue(body.startswith("\r\n"))

    def test_parse_bom_lf(self):
        self.assertTrue(frontmatter.has(BOM_LF_TPL))
        parts = frontmatter.split(BOM_LF_TPL)
        self.assertIsNotNone(parts)
        front, body, eol = parts
        self.assertEqual(eol, "\n")
        self.assertIn('title: "x"', front)

    def test_parse_bom_crlf(self):
        self.assertTrue(frontmatter.has(BOM_CRLF_TPL))
        parts = frontmatter.split(BOM_CRLF_TPL)
        self.assertIsNotNone(parts)
        front, body, eol = parts
        self.assertEqual(eol, "\r\n")
        self.assertIn('title: "x"', front)

    def test_missing_frontmatter_fails(self):
        self.assertFalse(frontmatter.has("no front matter here\n"))
        self.assertIsNone(frontmatter.split("no front matter here\n"))
        self.assertFalse(frontmatter.has("---\nunclosed\n"))

    def test_regex_group_body_compatible(self):
        """task_cmd._FM_RE 依赖 group('body')，必须保持兼容。"""
        m = FRONTMATTER_RE.match(BOM_CRLF_TPL)
        self.assertIsNotNone(m)
        self.assertIn("status: \"draft\"", m.group("body"))
        m = FRONTMATTER_RE.match(CRLF_TPL)
        self.assertIsNotNone(m)
        self.assertIn("status: \"draft\"", m.group("body"))


class TestFrontmatterRewrite(unittest.TestCase):
    def test_set_value_keeps_lf(self):
        out = frontmatter.set_value(LF_TPL, "status", "ready")
        self.assertEqual(out.count("\r\n"), 0)
        self.assertTrue(out.startswith("---\n"))
        self.assertIn('status: "ready"', out)
        self.assertIn("body text", out)

    def test_set_value_keeps_crlf(self):
        out = frontmatter.set_value(CRLF_TPL, "status", "ready")
        self.assertIn("\r\n", out)
        self.assertIn('status: "ready"', out)
        self.assertIn("body text", out)
        # 正文行尾风格保持 CRLF
        self.assertTrue(out.endswith("body text\r\n"))

    def test_set_value_keeps_bom(self):
        out = frontmatter.set_value(BOM_LF_TPL, "status", "ready")
        self.assertTrue(out.startswith("\ufeff---\n"))
        self.assertIn('status: "ready"', out)
        out2 = frontmatter.set_value(BOM_CRLF_TPL, "status", "ready")
        self.assertTrue(out2.startswith("\ufeff---\r\n"))
        self.assertIn('status: "ready"', out2)

    def test_set_value_appends_new_key(self):
        out = frontmatter.set_value(LF_TPL, "intended_next", "DEVELOPING")
        self.assertIn('intended_next: "DEVELOPING"', out)
        parts = frontmatter.split(out)
        front, body, _ = parts
        self.assertIn('intended_next: "DEVELOPING"', front)

    def test_set_value_replaces_in_place_keeps_indent(self):
        indented = "---\n  status: \"draft\"\n---\n\nbody\n"
        out = frontmatter.set_value(indented, "status", "ready")
        self.assertIn('  status: "ready"', out)

    def test_set_value_broken_fm_raises(self):
        with self.assertRaises(frontmatter.FrontMatterError):
            frontmatter.set_value("no front matter\n", "status", "ready")

    def test_set_values_multi(self):
        out = frontmatter.set_values(LF_TPL, {"status": "ready", "decision": "PASS"})
        self.assertIn('status: "ready"', out)
        self.assertIn('decision: "PASS"', out)

    def test_yaml_parseable_via_pyyaml(self):
        """front matter body 可被真实 YAML 解析（preflight 依赖）。"""
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml not available")
        parts = frontmatter.split(CRLF_TPL)
        self.assertIsNotNone(parts)
        front, _, _ = parts
        data = yaml.safe_load(front)
        self.assertEqual(data["status"], "draft")
        self.assertEqual(data["title"], "x")


class TestFrontmatterByteFidelity(unittest.TestCase):
    """V5.1.3 定向修复 §6：字节级格式保真。"""

    def test_single_field_crlf_preserved(self):
        """审查 §3.5 核心缺陷：单字段 CRLF 不得被改成 LF。"""
        single = "---\r\nstatus: draft\r\n---\r\nBody\r\n"
        out = frontmatter.set_value(single, "status", "ready")
        self.assertEqual(out, "---\r\nstatus: \"ready\"\r\n---\r\nBody\r\n")
        self.assertIn("\r\n", out)
        self.assertNotIn("\n---\n", out)

    def test_single_field_bom_crlf_preserved(self):
        single = "\ufeff---\r\nstatus: draft\r\n---\r\nBody\r\n"
        out = frontmatter.set_value(single, "status", "ready")
        self.assertTrue(out.startswith("\ufeff---\r\n"))
        self.assertEqual(out.count("\ufeff"), 1)
        self.assertIn('status: "ready"', out)
        self.assertTrue(out.endswith("Body\r\n"))

    def test_leading_blank_lines_preserved(self):
        """正文开头 0/1/2/3 空行全部保留（禁止 lstrip）。"""
        for blanks in (0, 1, 2, 3):
            body = "\n" * blanks + "正文开始\n"
            text = "---\nstatus: draft\n---\n" + body
            out = frontmatter.set_value(text, "status", "ready")
            expected = "---\nstatus: \"ready\"\n---\n" + body
            self.assertEqual(out, expected, f"blank lines lost for blanks={blanks}")

    def test_crlf_leading_blank_lines_preserved(self):
        body = "\r\n\r\n正文开始\r\n"
        text = "---\r\nstatus: draft\r\n---\r\n" + body
        out = frontmatter.set_value(text, "status", "ready")
        self.assertTrue(out.endswith(body))
        self.assertEqual(out.count("\r\n"), text.count("\r\n"), "CRLF count must be stable")

    def test_chinese_body_untouched(self):
        text = "---\nstatus: draft\n---\n\n# 中文正文\n\n- 需求：架构移交\n- 结论：开始执行\n"
        out = frontmatter.set_value(text, "status", "ready")
        # 仅目标字段变化，正文逐字节一致
        body = text.split("---\n", 2)[2]
        out_body = out.split("---\n", 2)[2]
        self.assertEqual(out_body, body)
        self.assertIn('status: "ready"', out)

    def test_only_target_field_changed(self):
        text = "---\ntitle: \"x\"\nstatus: draft\nintended_next: \"DEVELOPING\"\n---\n\nbody\n"
        out = frontmatter.set_value(text, "status", "ready")
        self.assertIn('title: "x"', out)
        self.assertIn('intended_next: "DEVELOPING"', out)
        self.assertIn('status: "ready"', out)
        self.assertNotIn("draft", out)

    def test_multi_field_crlf(self):
        text = "---\r\ntitle: \"x\"\r\nstatus: draft\r\nintended_next: \"DEVELOPING\"\r\n---\r\n\r\nbody\r\n"
        out = frontmatter.set_value(text, "status", "ready")
        self.assertTrue(out.startswith("---\r\n"))
        self.assertIn('status: "ready"', out)
        self.assertTrue(out.endswith("body\r\n"))


if __name__ == "__main__":
    unittest.main()
