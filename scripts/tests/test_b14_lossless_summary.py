# -*- coding: utf-8 -*-
"""V5.1.0 B-14 lossless-summary 回归套件（B-17 C7-P1~P10 强断言）。

设计权威：docs/V5.1.0-B14-lossless-summary-design.md §9.2（C7-P1~P10）；
对齐通用约定 §2（每用例正例+反例；强断言退出码 + status 终值 + STDERR 枚举逐字节 +
文件/hash 存在性；完全隔离临时目录 + 受控 fixture；测试后清理；失败即 FAIL）。

纯 stdlib unittest、离线、无 subprocess/网络/DB；相同输入两次运行逐字节一致。

Run:
    python scripts/tests/test_b14_lossless_summary.py
"""

from __future__ import annotations

import ast
import argparse
import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent  # tp-spec-base
sys.path.insert(0, str(BASE))

from cli import anchor_check  # noqa: E402
from cli import lossless_summary  # noqa: E402
from cli import review_preflight, structured_refs, s1_validator, sensitive_scanner  # noqa: E402

from cli.lossless_summary import (  # noqa: E402
    SUMMARY_FORMAT_VERSION, SUMMARY_FORMAT_SHA256, MAX_RESTORE_PASSES,
    SUMMARY_NOT_SAFE, SUMMARY_INPUT_INVALID, SUMMARY_RETRIEVE_FAILED,
    SUMMARY_READBACK_MISMATCH, SUMMARY_VERIFY_FAILED,
    classify, protect_fields, restore_fields,
    build_summary, serialize_summary, summary_filename, verify_summary,
    atomic_write_artifact, parse_handle, retrieve, rebuild,
    cmd_lossless_summary, fold_json, fold_log, fold_code,
    rebuild_fold, rebuild_json, rebuild_log, rebuild_code,
)
from cli.anchor_check import _normalize_sha256  # noqa: E402


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def run_cmd(source_base: Path, input_rel: str, output_dir: Path, **overrides) -> tuple[int, str, str]:
    """CLI 直调（不走 subprocess）：构造 argparse.Namespace 并捕获 stdout/stderr。"""
    base_args = dict(
        source_base=str(source_base), input=input_rel, output_dir=str(output_dir),
        type="package_summary", declared_type=None, simulate=False,
    )
    base_args.update(overrides)
    args = argparse.Namespace(**base_args)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = cmd_lossless_summary(args)
        except ValueError as exc:
            err.write(f"ValueError: {exc}\n")
            rc = 1
    return rc, out.getvalue(), err.getvalue()


def collect_imports(path: Path) -> set[str]:
    """AST 收集 import：ast.Import 的 alias.name + ast.ImportFrom 的 module/names。

    覆盖 `from . import X`（module=None，names=[X]）与 `from .anchor_check import Y`（module=".anchor_check"）
    两种相对导入形式，避免遗漏。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                # from <module> import <name>：module 才是模块名，names 是符号名
                found.add(node.module)
            else:
                # from . import X：module=None，names 是相对导入的模块名
                for alias in node.names:
                    found.add(alias.name)
    return found


NINE_KIND_TEXT = (
    "```python\n"
    "def f():\n"
    "    return 1\n"
    "```\n"
    "$ tp-spec task list\n"
    "Error: failed to connect\n"
    "C:\\temp\\file.txt\n"
    "https://example.com/demo\n"
    "port 8080 and version 1.2.3\n"
    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
    "verdict: PASS\n"
    "authorized_by: alice\n"
)


class TestC7SummaryNotSafe(unittest.TestCase):
    """C7-P1：SUMMARY_NOT_SAFE 正例（规则冲突 / 无法识别 / 保护字段无法隔离）。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="c7_p1_")
        self.tmp = Path(self._tmp)
        self.src = self.tmp / "src"
        self.src.mkdir()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _assert_not_safe_artifact(self, summary: dict, ctype: str):
        self.assertEqual(summary["status"], SUMMARY_NOT_SAFE)
        self.assertEqual(summary["fold"], {})  # 不产折叠
        entries = summary["entries"]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        # 索引条目六要素完整
        self.assertEqual(set(entry.keys()),
                         {"source_path", "content_type", "byte_range", "sha256",
                          "retrieve_handle", "sentinel_list"})
        self.assertEqual(entry["content_type"], ctype)
        self.assertEqual(entry["byte_range"][0], 0)
        self.assertGreater(entry["byte_range"][1], 0)
        self.assertTrue(_normalize_sha256(entry["sha256"]) == entry["sha256"])
        self.assertTrue(entry["retrieve_handle"].startswith("rel://"))
        self.assertEqual(entry["sentinel_list"], [])
        # 双锚点
        self.assertEqual(summary["summary_format_version"], SUMMARY_FORMAT_VERSION)
        self.assertEqual(summary["summary_format_sha256"], SUMMARY_FORMAT_SHA256)

    def test_c7_p1_rule_conflict(self):
        # P1 内部冲突：json_magic（[ 开头）与 code_magic（def 行首）同时命中 -> 无法裁决
        content = "[\ndef x():\n]\n"
        (self.src / "conflict.json").write_bytes(content.encode("utf-8"))
        summary = build_summary(content, "conflict.json", str(self.src))
        self._assert_not_safe_artifact(summary, "unknown")

    def test_c7_p1_unrecognized(self):
        # 无法识别：P1-P5 全部未命中（扩展名不在受控表、路径无启发）
        content = "hello world\n"
        (self.src / "data.bin").write_bytes(content.encode("utf-8"))
        summary = build_summary(content, "data.bin", str(self.src))
        self._assert_not_safe_artifact(summary, "unknown")

    def test_c7_p1_protection_incomplete(self):
        # 保护字段无法完整隔离：2 轮才收敛的嵌套文本 + 上限 1 -> 超限不收敛
        content = "a\n```\nb\n```\nc\n```\nd\n```\n"
        (self.src / "nested.txt").write_bytes(content.encode("utf-8"))
        summary = build_summary(content, "nested.txt", str(self.src), max_passes=1)
        self._assert_not_safe_artifact(summary, "text")
        # 直接验证 protect_fields 不收敛（默认上限内正常收敛 -> 正例对照）
        sentinelized, sentinels, ok = protect_fields(content, max_passes=1)
        self.assertFalse(ok)
        self.assertEqual(sentinels, [])
        self.assertEqual(sentinelized, content)
        _, _, ok_default = protect_fields(content)
        self.assertTrue(ok_default)  # 默认 MAX_RESTORE_PASSES=8 内收敛

    def test_c7_p1_exit0_via_cli(self):
        # SUMMARY_NOT_SAFE 是合法产物：CLI 退出码 0
        (self.src / "data.bin").write_text("hello world\n", encoding="utf-8")
        out_dir = self.tmp / "out"
        rc, out, err = run_cmd(self.src, "data.bin", out_dir)
        self.assertEqual(rc, 0, err)
        self.assertIn("SUMMARY_NOT_SAFE", out)
        artifacts = list(out_dir.glob("summary-*.json"))
        self.assertEqual(len(artifacts), 1)
        artifact = json.loads(artifacts[0].read_text(encoding="utf-8"))
        self.assertEqual(artifact["status"], SUMMARY_NOT_SAFE)


class TestC7OkFold(unittest.TestCase):
    """C7-P2：SUMMARY_NOT_SAFE 反例（可识别 + 保护完整 -> OK 正常折叠）。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="c7_p2_")
        self.tmp = Path(self._tmp)
        self.src = self.tmp / "src"
        self.src.mkdir()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_c7_p2_ok_json_with_url(self):
        content = '{"name": "demo", "url": "https://example.com/x", "count": 3}\n'
        (self.src / "data.json").write_bytes(content.encode("utf-8"))
        summary = build_summary(content, "data.json", str(self.src))
        self.assertEqual(summary["status"], "OK")
        self.assertNotEqual(summary["fold"], {})
        # url 保护段存在；json 类型跳过 number 规则（数字逐字保留，无需保护）
        entry = summary["entries"][0]
        self.assertEqual(entry["content_type"], "json")
        rules = [s["rule_id"] for s in entry["sentinel_list"]]
        self.assertIn("url", rules)
        self.assertNotIn("number", rules)
        # 无保护段残损：还原后 == 原文
        restored = restore_fields(
            rebuild_json(summary["fold"]), entry["sentinel_list"])
        self.assertEqual(restored.encode("utf-8"), content.encode("utf-8"))

    def test_c7_p2_ok_log_dedup(self):
        content = "2026-01-01T00:00:00 INFO: start\n2026-01-01T00:00:01 INFO: tick\n2026-01-01T00:00:01 INFO: tick\n"
        (self.src / "app.log").write_bytes(content.encode("utf-8"))
        summary = build_summary(content, "app.log", str(self.src))
        self.assertEqual(summary["status"], "OK")
        fold = summary["fold"]
        self.assertEqual(len(fold["lines"]), 2)  # 重复行去重计数
        dup = [ln for ln in fold["lines"] if ln["repeat_positions"]]
        self.assertEqual(len(dup), 1)
        self.assertEqual(dup[0]["repeat_positions"], [2])
        # 还原逐字节（时间戳原样保留）：fold 逆向 + sentinel 逆序恢复
        entry = summary["entries"][0]
        rebuilt = restore_fields(rebuild_log(fold), entry["sentinel_list"])
        self.assertEqual(rebuilt, content)


class TestC7SentinelRestore(unittest.TestCase):
    """C7-P3：sentinel 九类保护 + 嵌套（限制内/超限）+ 还原逐字节。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="c7_p3_")
        self.tmp = Path(self._tmp)
        self.src = self.tmp / "src"
        self.src.mkdir()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_c7_p3_nine_kinds_restore_byte_equal(self):
        (self.src / "notes.txt").write_bytes(NINE_KIND_TEXT.encode("utf-8"))
        summary = build_summary(NINE_KIND_TEXT, "notes.txt", str(self.src))
        self.assertEqual(summary["status"], "OK")
        entry = summary["entries"][0]
        rules = {s["rule_id"] for s in entry["sentinel_list"]}
        # 九类保护字段全部覆盖
        self.assertEqual(rules, {"code_block", "command", "error", "hash",
                                 "number", "path", "url", "accept_verdict", "auth_field"})
        # 还原（fold 逆向 + sentinel 逆序恢复）与原文逐字节相等
        rebuilt = rebuild(summary, self.src)
        self.assertEqual(rebuilt, NINE_KIND_TEXT.encode("utf-8"))

    def test_c7_p3_nested_within_limit(self):
        # 嵌套语义：外层保护段（code_block）包含内层形态（URL），随块整体保护，
        # 还原逐字节相等（内层随外层按提取逆序恢复）
        content = "```\nhttps://example.com/inner\n```\n"
        (self.src / "nested.txt").write_bytes(content.encode("utf-8"))
        summary = build_summary(content, "nested.txt", str(self.src))
        self.assertEqual(summary["status"], "OK")
        entry = summary["entries"][0]
        rules = [s["rule_id"] for s in entry["sentinel_list"]]
        self.assertIn("code_block", rules)
        self.assertNotIn("url", rules)  # URL 被外层 code_block 覆盖，不单独提取
        self.assertEqual(rebuild(summary, self.src), content.encode("utf-8"))

    def test_c7_p3_nested_over_limit(self):
        # 嵌套超限（上限 1 + 需 2 轮收敛）-> protect_fields 不收敛 -> SUMMARY_NOT_SAFE
        content = "a\n```\nb\n```\nc\n```\nd\n```\n"
        sentinelized, sentinels, ok = protect_fields(content, max_passes=1)
        self.assertFalse(ok)
        self.assertEqual(sentinels, [])
        self.assertEqual(sentinelized, content)
        summary = build_summary(content, "nested.txt", "src", max_passes=1)
        self.assertEqual(summary["status"], SUMMARY_NOT_SAFE)
        self.assertEqual(summary["fold"], {})

    def test_c7_p3_tampered_sentinel_list_fail_closed(self):
        # 任一 sentinel 缺失/位置错 -> fail-closed：verify 拒绝 + rebuild 失败
        (self.src / "notes.txt").write_bytes(NINE_KIND_TEXT.encode("utf-8"))
        summary = build_summary(NINE_KIND_TEXT, "notes.txt", str(self.src))
        tampered = json.loads(json.dumps(summary, ensure_ascii=False))
        tampered["entries"][0]["sentinel_list"] = tampered["entries"][0]["sentinel_list"][1:]
        ok, reason = verify_summary(tampered)
        self.assertFalse(ok)
        self.assertIn(SUMMARY_VERIFY_FAILED, reason)
        with self.assertRaises(ValueError):
            rebuild(tampered, self.src)


class TestC7Retrieve(unittest.TestCase):
    """C7-P4：索引 retrieve 字节相等；非法/缺失/篡改 fail-closed。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="c7_p4_")
        self.tmp = Path(self._tmp)
        self.src = self.tmp / "src"
        self.src.mkdir()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_c7_p4_valid_retrieve_byte_equal(self):
        content = '{"a": [1, 2, 3], "b": "https://example.com"}\n'
        (self.src / "data.json").write_bytes(content.encode("utf-8"))
        summary = build_summary(content, "data.json", str(self.src))
        entry = summary["entries"][0]
        chunk = retrieve(self.src, entry)
        self.assertEqual(chunk, content.encode("utf-8"))  # 与原文字节相等

    def test_c7_p4_invalid_handle(self):
        with self.assertRaises(ValueError):
            parse_handle("bad")
        with self.assertRaises(ValueError):
            parse_handle("rel://a.txt#B-1-5")
        with self.assertRaises(ValueError):
            parse_handle("rel://a.txt#B5-2")

    def test_c7_p4_missing_file(self):
        content = "hello\n"
        (self.src / "gone.txt").write_bytes(content.encode("utf-8"))
        summary = build_summary(content, "gone.txt", str(self.src))
        (self.src / "gone.txt").unlink()
        with self.assertRaises(ValueError):
            retrieve(self.src, summary["entries"][0])

    def test_c7_p4_hash_tampered(self):
        content = "hello\n"
        (self.src / "data.txt").write_bytes(content.encode("utf-8"))
        summary = build_summary(content, "data.txt", str(self.src))
        entry = dict(summary["entries"][0])
        entry["sha256"] = "sha256:" + "0" * 64  # 篡改 hash
        with self.assertRaises(ValueError):
            retrieve(self.src, entry)  # 不返回部分/篡改内容

    def test_c7_p4_path_escape(self):
        content = "hello\n"
        (self.src / "data.txt").write_bytes(content.encode("utf-8"))
        summary = build_summary(content, "data.txt", str(self.src))
        entry = dict(summary["entries"][0])
        entry["retrieve_handle"] = "rel://../../evil.txt#B0-5"
        with self.assertRaises(ValueError):
            retrieve(self.src, entry)


class TestC7Parity(unittest.TestCase):
    """C7-P5：parity rebuild 逐字节相等（json/log/code/text 四类型）。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="c7_p5_")
        self.tmp = Path(self._tmp)
        self.src = self.tmp / "src"
        self.src.mkdir()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _assert_parity(self, filename: str, content: str):
        (self.src / filename).write_bytes(content.encode("utf-8"))
        summary = build_summary(content, filename, str(self.src))
        self.assertEqual(summary["status"], "OK")
        rebuilt = rebuild(summary, self.src)
        self.assertEqual(rebuilt, content.encode("utf-8"))  # 逐字节相等

    def test_c7_p5_parity_json(self):
        self._assert_parity("data.json", '{"name": "demo", "url": "https://example.com/x", "count": 3}\n')

    def test_c7_p5_parity_log(self):
        self._assert_parity("app.log", "2026-01-01T00:00:00 INFO: start\n2026-01-01T00:00:01 INFO: tick\n")

    def test_c7_p5_parity_code(self):
        self._assert_parity("main.py", "def main():\n    return 42  # https://example.com/api\n")

    def test_c7_p5_parity_text(self):
        self._assert_parity("notes.md", "# demo\n\nverdict: PASS\n")


class TestC7NoLossyPath(unittest.TestCase):
    """C7-P6：有损路径不存在（AST 静态断言 + 行为断言 + 无 human_owner 有损开关）。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="c7_p6_")
        self.tmp = Path(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_c7_p6_ast_import_whitelist(self):
        # 静态：B-14 模块 import ⊆ stdlib ∪ {anchor_check}；无 subprocess/网络/模型
        module_path = BASE / "cli" / "lossless_summary.py"
        imports = collect_imports(module_path)
        forbidden = {"subprocess", "socket", "urllib", "requests", "http", "os.system"}
        self.assertTrue(imports.isdisjoint(forbidden), imports & forbidden)
        stdlib = set(sys.stdlib_module_names)
        internal = {name for name in imports if name in {"anchor_check", "lossless_summary"}}
        external = imports - internal - stdlib
        self.assertEqual(external, set(), f"non-stdlib imports: {external}")

    def test_c7_p6_ast_no_lossy_constructs(self):
        # 静态：模块内无压缩/丢弃/模型调用路径与 human_owner 有损开关
        source = (BASE / "cli" / "lossless_summary.py").read_text(encoding="utf-8")
        for forbidden in ("lossy", "row_drop", "human_owner", "enable_lossy", "llm", "openai"):
            self.assertNotIn(forbidden, source, f"forbidden construct present: {forbidden}")

    def test_c7_p6_behavior_no_lossy_fold(self):
        # 行为：任何输入不触发有损折叠（fold 重建 parity 全覆盖）
        samples = {
            "a.json": '{"k": "v", "n": 1}\n',
            "b.log": "2026-01-01T00:00:00 ERROR: boom\n",
            "c.py": "def f():\n    return 1\n",
            "d.md": "# title\n",
        }
        src = self.tmp / "src"
        src.mkdir()
        for name, content in samples.items():
            (src / name).write_bytes(content.encode("utf-8"))
            summary = build_summary(content, name, str(src))
            self.assertEqual(summary["status"], "OK")
            rebuilt = rebuild(summary, src)
            self.assertEqual(rebuilt, content.encode("utf-8"))


class TestC7Priority(unittest.TestCase):
    """C7-P7：规则优先级 P1>P2>P3>P4>P5 裁决；P1 内部冲突 -> SUMMARY_NOT_SAFE。"""

    def test_c7_p7_p1_wins_over_p2(self):
        # P1 魔数（json）> P2 声明（log）
        self.assertEqual(classify('{"a": 1}', "x.json", declared_type="log"), "json")

    def test_c7_p7_p2_wins_over_p3(self):
        # P2 声明（log）> P3 严格解析（json：前导空白使 P1 魔数不命中）
        self.assertEqual(classify('  {"a": 1}', "x.json", declared_type="log"), "log")

    def test_c7_p7_p3_wins_over_p4(self):
        # P3 严格解析（json）> P4 扩展名（.log）
        self.assertEqual(classify('  {"a": 1}', "x.log"), "json")

    def test_c7_p7_p4_wins_over_p5(self):
        # P4 扩展名（.py -> code）> P5 路径启发（logs/）
        self.assertEqual(classify("plain text\n", "logs/app.py"), "code")

    def test_c7_p7_p5_path_hint(self):
        # P5 路径启发（logs/ -> log）；P4 扩展名 .bin 不在受控表
        self.assertEqual(classify("plain text\n", "logs/data.bin"), "log")

    def test_c7_p7_p1_internal_conflict(self):
        # P1 内部冲突 -> 无法裁决 -> SUMMARY_NOT_SAFE
        self.assertIsNone(classify("[\ndef x():\n]\n", "x.txt"))
        summary = build_summary("[\ndef x():\n]\n", "x.txt", "src")
        self.assertEqual(summary["status"], SUMMARY_NOT_SAFE)


class TestC7OrthogonalAst(unittest.TestCase):
    """C7-P8：正交 AST（双向无 import）。"""

    def test_c7_p8_lossless_summary_imports_only_anchor(self):
        imports = collect_imports(BASE / "cli" / "lossless_summary.py")
        internal = {name for name in imports
                    if name in {"anchor_check", "lossless_summary", "review_preflight",
                                "structured_refs", "s1_validator", "sensitive_scanner"}}
        self.assertEqual(internal, {"anchor_check"}, f"internal imports: {internal}")

    def test_c7_p8_four_modules_do_not_import_lossless(self):
        for mod in ("review_preflight", "structured_refs", "s1_validator", "sensitive_scanner"):
            imports = collect_imports(BASE / "cli" / f"{mod}.py")
            self.assertNotIn("lossless_summary", imports, f"{mod} imports lossless_summary")
            self.assertNotIn(".lossless_summary", imports, f"{mod} imports .lossless_summary")


class TestC7DualAnchor(unittest.TestCase):
    """C7-P9：双锚点防逃逸（内容改版本不变 / 版本变 / content_hash 篡改）。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="c7_p9_")
        self.tmp = Path(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _build_ok(self) -> dict:
        summary = build_summary('{"a": 1}\n', "data.json", "src")
        self.assertEqual(summary["status"], "OK")
        return summary

    def test_c7_p9_verify_ok(self):
        ok, reason = verify_summary(self._build_ok())
        self.assertTrue(ok, reason)

    def test_c7_p9_content_change_version_same(self):
        # 内容改（sha256 字段被篡改）而版本不变 -> summary_format_sha256 失配拒绝消费
        tampered = json.loads(json.dumps(self._build_ok(), ensure_ascii=False))
        tampered["summary_format_sha256"] = "sha256:" + "0" * 64
        ok, reason = verify_summary(tampered)
        self.assertFalse(ok)
        self.assertIn("format sha256 mismatch", reason)

    def test_c7_p9_version_change(self):
        # 版本变 -> 旧产物失效（拒绝消费）
        tampered = json.loads(json.dumps(self._build_ok(), ensure_ascii=False))
        tampered["summary_format_version"] = "9.9.9"
        ok, reason = verify_summary(tampered)
        self.assertFalse(ok)
        self.assertIn("format version mismatch", reason)

    def test_c7_p9_content_hash_tampered(self):
        tampered = json.loads(json.dumps(self._build_ok(), ensure_ascii=False))
        tampered["content_hash"] = "sha256:" + "0" * 64
        ok, reason = verify_summary(tampered)
        self.assertFalse(ok)
        self.assertIn("content hash mismatch", reason)


class TestC7AtomicWrite(unittest.TestCase):
    """C7-P10：原子写 readback + 幂等 + simulate 零写入。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="c7_p10_")
        self.tmp = Path(self._tmp)
        self.src = self.tmp / "src"
        self.src.mkdir()
        self.out = self.tmp / "out"

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_c7_p10_write_and_idempotent(self):
        content = '{"a": 1}\n'
        (self.src / "data.json").write_bytes(content.encode("utf-8"))
        summary = build_summary(content, "data.json", str(self.src))
        serialized = serialize_summary(summary)
        path = self.out / summary_filename(summary)
        # 首次写入
        action = atomic_write_artifact(path, serialized, hashlib.sha256(serialized).hexdigest())
        self.assertEqual(action, "written")
        self.assertTrue(path.exists())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), hashlib.sha256(serialized).hexdigest())
        # 重复同 hash -> 幂等返回，不重写
        before = path.read_bytes()
        action = atomic_write_artifact(path, serialized, hashlib.sha256(serialized).hexdigest())
        self.assertEqual(action, "idempotent")
        self.assertEqual(path.read_bytes(), before)

    def test_c7_p10_existing_different_content_fails(self):
        path = self.out / "summary-abcdef1234567890.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"tampered content")
        with self.assertRaises(ValueError):
            atomic_write_artifact(path, b"new data", hashlib.sha256(b"new data").hexdigest())
        # 目标文件保持原内容不变（未被覆盖）
        self.assertEqual(path.read_bytes(), b"tampered content")

    def test_c7_p10_simulate_zero_write(self):
        (self.src / "data.json").write_text('{"a": 1}\n', encoding="utf-8")
        rc, out, err = run_cmd(self.src, "data.json", self.out, simulate=True)
        self.assertEqual(rc, 0, err)
        self.assertIn("simulate: would write", out)
        self.assertFalse(self.out.exists())  # 零写入

    def test_c7_p10_cli_write_and_stable_replay(self):
        (self.src / "data.json").write_text('{"a": 1}\n', encoding="utf-8")
        rc1, out1, _ = run_cmd(self.src, "data.json", self.out)
        self.assertEqual(rc1, 0)
        artifacts = list(self.out.glob("summary-*.json"))
        self.assertEqual(len(artifacts), 1)
        first = artifacts[0].read_bytes()
        # 相同输入两次运行逐字节一致（稳定重放，无时间戳/随机量）
        rc2, out2, _ = run_cmd(self.src, "data.json", self.out)
        self.assertEqual(rc2, 0)
        self.assertIn("idempotent", out2)  # 同 hash 幂等
        self.assertEqual(artifacts[0].read_bytes(), first)


class TestC7CliInputValidation(unittest.TestCase):
    """CLI 输入校验（fail-closed）：缺失/绝对路径/逃逸/非 UTF-8。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="c7_cli_")
        self.tmp = Path(self._tmp)
        self.src = self.tmp / "src"
        self.src.mkdir()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_cli_missing_input(self):
        rc, out, err = run_cmd(self.src, "nope.txt", self.tmp / "out")
        self.assertNotEqual(rc, 0)
        self.assertIn(SUMMARY_INPUT_INVALID, err)

    def test_cli_absolute_input(self):
        rc, out, err = run_cmd(self.src, str(self.tmp / "abs.txt"), self.tmp / "out")
        self.assertNotEqual(rc, 0)
        self.assertIn(SUMMARY_INPUT_INVALID, err)

    def test_cli_escape_input(self):
        rc, out, err = run_cmd(self.src, "../outside.txt", self.tmp / "out")
        self.assertNotEqual(rc, 0)
        self.assertIn(SUMMARY_INPUT_INVALID, err)

    def test_cli_non_utf8(self):
        (self.src / "bin.dat").write_bytes(b"\xff\xfe\x00\x01")
        rc, out, err = run_cmd(self.src, "bin.dat", self.tmp / "out")
        self.assertNotEqual(rc, 0)
        self.assertIn(SUMMARY_INPUT_INVALID, err)


class TestC7VersionSync(unittest.TestCase):
    """T6 版本同步：review_preflight.SUMMARY_FORMAT_VERSION 与 B-14 复合版本一致。"""

    def test_version_constants_synced(self):
        self.assertEqual(review_preflight.SUMMARY_FORMAT_VERSION, SUMMARY_FORMAT_VERSION)
        self.assertEqual(SUMMARY_FORMAT_VERSION, "1.0.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
