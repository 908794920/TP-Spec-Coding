# -*- coding: utf-8 -*-
"""V5.1.3 A-05 UTF-8 安全输入测试。

覆盖（任务书 §十 编码测试）：
- 中文 summary / UTF-8 正常通过；
- BOM / CRLF / LF 输入文本无碍；
- 乱码拒绝（U+FFFD、Latin-1 mojibake、Windows-1252 mojibake、连续问号）。

纯 stdlib unittest、离线。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent  # ai-work-base
sys.path.insert(0, str(BASE))

from cli import encoding_guard  # noqa: E402
from cli.encoding_guard import EncodingValidationError  # noqa: E402


class TestRoundtrip(unittest.TestCase):
    def test_chinese_roundtrip_ok(self):
        self.assertTrue(encoding_guard.roundtrip_ok("中文 summary 摘要"))
        self.assertTrue(encoding_guard.roundtrip_ok("普通 ASCII text"))

    def test_invalid_surrogate_rejected(self):
        # 非法代理项无法 UTF-8 编码
        self.assertFalse(encoding_guard.roundtrip_ok("\ud800"))

    def test_utf8_bytes_input_type_rejected(self):
        # bytes 不是 str：roundtrip 视为失败（保守）
        self.assertFalse(encoding_guard.roundtrip_ok(b"\xe4\xb8\xad"))


class TestMojibakeDetection(unittest.TestCase):
    def test_replacement_char(self):
        hits = encoding_guard.detect_mojibake("bad \ufffd char")
        self.assertIn("U+FFFD replacement char", hits)

    def test_latin1_mojibake(self):
        # "中文" 的 UTF-8 字节被按 Latin-1 误读的典型痕迹
        hits = encoding_guard.detect_mojibake("Ã¤Â¸Â­Ã¦ÂÂ")
        self.assertTrue(hits)

    def test_cp1252_mojibake(self):
        # UTF-8 三字节被按 Windows-1252 误读（â€ 族）
        hits = encoding_guard.detect_mojibake("â€œquotedâ€")
        self.assertTrue(hits)

    def test_repeated_qmark(self):
        hits = encoding_guard.detect_mojibake("what??? happened")
        self.assertIn("repeated '?' placeholder", hits)

    def test_clean_text_no_hits(self):
        self.assertEqual(encoding_guard.detect_mojibake("正常文本 normal text"), [])
        self.assertEqual(encoding_guard.detect_mojibake("?single question ok"), [])


class TestValidateInput(unittest.TestCase):
    def test_chinese_summary_passes(self):
        encoding_guard.validate_input("架构设计完成，进入开发", "summary")

    def test_mojibake_raises_with_field(self):
        with self.assertRaises(EncodingValidationError) as ctx:
            encoding_guard.validate_input("bad \ufffd summary", "summary")
        self.assertIn("summary", str(ctx.exception))

    def test_list_validation(self):
        encoding_guard.validate_list(["ok", "正常"], "evidence")
        with self.assertRaises(EncodingValidationError):
            encoding_guard.validate_list(["ok", "bad \ufffd"], "evidence")

    def test_error_message_mentions_pattern(self):
        with self.assertRaises(EncodingValidationError) as ctx:
            encoding_guard.validate_input("bad \u00c3\u00a4 text", "summary")
        self.assertIn("mojibake", str(ctx.exception))


class TestChineseMojibakeReversible(unittest.TestCase):
    """V5.1.3 定向修复 §7：中文 UTF-8→Latin-1 误读的真实样本可识别。"""

    # 真实误读样本（UTF-8 字节被按 Latin-1/CP1252 解码的结果）
    SAMPLES = {
        "å¼€å§‹": "开始",
        "æµ‹è¯•": "测试",
        "äº¤æŽ¥": "交接",
        "çŠ¶æ€": "状态",
    }

    def test_real_samples_detected(self):
        for sample, _ in self.SAMPLES.items():
            hits = encoding_guard.detect_mojibake(sample)
            self.assertTrue(hits, f"mojibake sample not detected: {sample!r}")
            self.assertTrue(
                any("suspected_utf8_as" in h for h in hits),
                f"reversible detection missing for {sample!r}: {hits}",
            )

    def test_full_samples_recovered_preview(self):
        """完整 6 字节样本的恢复预览应包含原文中文（尾部截断样本只保证非空）。"""
        for sample, recovered in self.SAMPLES.items():
            with self.assertRaises(EncodingValidationError) as ctx:
                encoding_guard.validate_input(sample, "summary")
            self.assertTrue(ctx.exception.recovered_preview, f"empty preview for {sample!r}")
            if len(sample) >= 6:
                self.assertIn(
                    recovered[:1], ctx.exception.recovered_preview,
                    f"preview mismatch for {sample!r}: {ctx.exception.recovered_preview!r}",
                )

    def test_real_samples_rejected_by_validate(self):
        for sample in self.SAMPLES:
            with self.assertRaises(EncodingValidationError) as ctx:
                encoding_guard.validate_input(sample, "summary")
            self.assertTrue(ctx.exception.reason.startswith("suspected_utf8_as"), ctx.exception.reason)
            self.assertTrue(ctx.exception.sample)
            self.assertTrue(ctx.exception.recovered_preview)

    def test_recovered_preview_content(self):
        with self.assertRaises(EncodingValidationError) as ctx:
            encoding_guard.validate_input("å¼€å§‹ æµ‹è¯•", "summary")
        # 重解码预览包含“开始/测试”之一
        self.assertTrue("开始" in ctx.exception.recovered_preview or "测试" in ctx.exception.recovered_preview,
                        ctx.exception.recovered_preview)

    def test_normal_french_not_rejected(self):
        """正常西欧文本（法语）不得被拒绝。"""
        for text in ("déjà vu", "café au lait été", "français très bien", "naïve façade"):
            self.assertEqual(encoding_guard.detect_mojibake(text), [], f"false positive: {text!r}")
            encoding_guard.validate_input(text, "summary")  # 不抛异常

    def test_normal_chinese_and_english_ok(self):
        for text in ("架构设计完成", "plain english summary", "混合 mixed 中文 text"):
            self.assertEqual(encoding_guard.detect_mojibake(text), [])

    def test_mixed_mojibake_sentence(self):
        hits = encoding_guard.detect_mojibake("任务状态：äº¤æŽ¥å®Œæˆ�")
        self.assertTrue(hits)


if __name__ == "__main__":
    unittest.main()
