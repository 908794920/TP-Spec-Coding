# -*- coding: utf-8 -*-
"""V5.1.3 Wiki standardization regression.

Pure local/stdlib+PyYAML tests.  Protects the key product invariants:
- config empty roots resolve under .ai-work and external central roots remain compatible;
- formatting/encoding drift does not become semantic change;
- Python/YAML indentation stays semantic;
- mass-change guard prevents token-explosive rewrites;
- topology changes cannot disappear because no old dependency exists;
- verification/audit must PASS before snapshot baseline advances;
- tp-wiki/tp-knowledge use the shared Content Systems resolver/Junction semantics.
"""
from __future__ import annotations

import json
import tempfile
import unittest
import io
from contextlib import redirect_stdout
from unittest.mock import patch
import sys
import os
from pathlib import Path
from types import SimpleNamespace

import yaml

BASE = Path(__file__).resolve().parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from cli.main import build_parser
import cli.wiki.commands as wiki_commands
from cli.wiki.audit import build_audit_plan
from cli.wiki.config import ContentSystemsConfigError, load_content_systems
from cli.wiki.coverage import compute_wiki_coverage, evaluate_first_build_readiness
from cli.wiki.manifest import extract_citation_sections, refresh_manifest, write_manifest
from cli.wiki.planner import build_plan
from cli.wiki.quality import record_semantic_audit, verify_repo
from cli.wiki.registry import resolve_targets
from cli.wiki.snapshot import build_current_snapshot, commit_baseline, snapshot_paths, stage_scan
from cli.wiki.source import normalized_hash

BASE_CONFIG = BASE / "governance" / "content-systems.yaml"


def write(path: Path, text: str, *, encoding: str = "utf-8", newline: str | None = "\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding, newline=newline)


def content_doc(source: str = "src/A.java") -> str:
    return f'''# A 模块

## 1. 概述
A 模块负责演示当前核心职责与可验证实现。 <cite path="{source}" line="1-3"/>

## 2. 模块结构
当前模块由 A 类承担主要实现入口，并保持单一职责。

## 3. 核心逻辑
真实逻辑由 A 类字段与方法共同实现，修改必须回读源码核对。

## 4. 数据流
输入进入 A 模块后按照源码定义完成处理并形成输出结果。

## 5. 接口
当前样本没有公开网络接口，仅暴露源码中的类级能力。

## 6. 配置
当前样本没有额外运行配置，行为直接由源码实现决定。

## 7. 依赖
该文档直接依赖对应源码文件作为最终技术事实来源。
'''


def write_standard_wiki(root: Path, source: str = "src/A.java") -> None:
    write(root / "index.md", "# Wiki 入口\n\n- [A 模块](core.md)\n")
    write(root / "core.md", content_doc(source))



class WikiCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="v513-wiki-")
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        # Regression fixtures must never inherit the developer machine's
        # ~/.ai-work/installation.yaml.  Use an explicit non-existent installation
        # config so the base config's empty roots resolve inside this temp workspace.
        self.installation_config = self.root / "missing-installation.yaml"
        self.cfg = load_content_systems(
            self.workspace,
            base_config_path=BASE_CONFIG,
            installation_config_path=self.installation_config,
        )
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        self.wiki = self.workspace / ".ai-work" / "wiki" / "repo"

    def tearDown(self):
        self.tmp.cleanup()


class TestContentSystems(WikiCase):
    def test_empty_roots_default_under_ai_work(self):
        self.assertEqual(self.cfg.paths.ai_work_root, self.workspace / ".ai-work")
        self.assertEqual(self.cfg.paths.wiki_system_root, self.workspace / ".ai-work" / "wiki")
        self.assertEqual(self.cfg.paths.knowledge_physical_root, self.workspace / ".ai-work" / "knowledge")
        self.assertEqual(self.cfg.paths.wiki_layout, "workspace-root")

    def test_external_legacy_central_root_and_registry(self):
        central = self.root / "central-wiki"
        registry = central / "00-system" / "repo-registry.yaml"
        write(registry, yaml.safe_dump({"version": 1, "workspaces": [{"id": "ws", "workspace_root": str(self.workspace), "repos": [{"id": "repo", "repo_root": str(self.repo), "enabled": True}]}]}, sort_keys=False))
        override = self.workspace / ".ai-work" / "config" / "content-systems.yaml"
        write(override, yaml.safe_dump({"systems": {"wiki": {"root": str(central)}}}, sort_keys=False))
        cfg = load_content_systems(self.workspace, base_config_path=BASE_CONFIG, installation_config_path=self.installation_config)
        self.assertEqual(cfg.paths.wiki_layout, "legacy-central")
        self.assertEqual(cfg.paths.wiki_registry, registry.resolve())
        target = resolve_targets(cfg)[0]
        self.assertEqual(target.wiki_repo_root, (central / "projects" / "ws" / "repo").resolve())

    def test_existing_registry_mismatch_does_not_guess_workspace(self):
        registry = self.workspace / ".ai-work" / "config" / "wiki-repos.yaml"
        write(registry, yaml.safe_dump({"version": 1, "workspaces": [{"id": "other", "workspace_root": str(self.root / "other"), "repos": []}]}, sort_keys=False))
        cfg = load_content_systems(self.workspace, base_config_path=BASE_CONFIG, installation_config_path=self.installation_config)
        with self.assertRaisesRegex(ValueError, "workspace not registered"):
            resolve_targets(cfg)

    def test_project_override_can_relocate_knowledge(self):
        target = self.root / "canonical-knowledge"
        override = self.workspace / ".ai-work" / "config" / "content-systems.yaml"
        write(override, yaml.safe_dump({"systems": {"knowledge": {"root": str(target)}}}, sort_keys=False))
        cfg = load_content_systems(self.workspace, base_config_path=BASE_CONFIG, installation_config_path=self.installation_config)
        self.assertEqual(cfg.paths.knowledge_physical_root, target.resolve())
        self.assertEqual(cfg.paths.knowledge_logical_root, self.workspace / ".ai-work" / "knowledge")

    def test_invalid_quality_sampling_configuration_fails_closed(self):
        override = self.workspace / ".ai-work" / "config" / "content-systems.yaml"
        write(override, yaml.safe_dump({"systems": {"wiki": {"quality": {"semantic_audit_sample_docs": 0}}}}, sort_keys=False))
        with self.assertRaisesRegex(ContentSystemsConfigError, "positive integer"):
            load_content_systems(self.workspace, base_config_path=BASE_CONFIG, installation_config_path=self.installation_config)

    def test_invalid_mass_change_ratio_fails_closed(self):
        override = self.workspace / ".ai-work" / "config" / "content-systems.yaml"
        write(override, yaml.safe_dump({"systems": {"wiki": {"snapshot": {"mass_change_ratio": 1.5}}}}, sort_keys=False))
        with self.assertRaisesRegex(ContentSystemsConfigError, "within 0..1"):
            load_content_systems(self.workspace, base_config_path=BASE_CONFIG, installation_config_path=self.installation_config)

    def test_initial_build_readiness_default_is_cost_aware_95_percent(self):
        self.assertEqual(float(self.cfg.quality["initial_build_effective_coverage_min"]), 0.95)

    def test_invalid_initial_build_readiness_threshold_fails_closed(self):
        override = self.workspace / ".ai-work" / "config" / "content-systems.yaml"
        write(override, yaml.safe_dump({"systems": {"wiki": {"quality": {"initial_build_effective_coverage_min": 1.1}}}}, sort_keys=False))
        with self.assertRaisesRegex(ContentSystemsConfigError, "within 0..1"):
            load_content_systems(self.workspace, base_config_path=BASE_CONFIG, installation_config_path=self.installation_config)


class TestFingerprint(WikiCase):
    def test_crlf_bom_blank_and_trailing_whitespace_are_cosmetic(self):
        a = b"class A {\r\n\r\n  int x = 1;   \r\n}\r\n"
        b = b"\xef\xbb\xbfclass A {\n  int x = 1;\n}\n"
        ah, _, _ = normalized_hash("src/A.java", a)
        bh, _, _ = normalized_hash("src/A.java", b)
        self.assertEqual(ah, bh)

    def test_comment_change_is_cosmetic_but_url_string_change_is_semantic(self):
        a, _, _ = normalized_hash("A.java", b'class A { String u = "http://one"; } // old\n')
        b, _, _ = normalized_hash("A.java", b'class A { String u = "http://one"; } // new\n')
        c, _, _ = normalized_hash("A.java", b'class A { String u = "http://two"; } // new\n')
        self.assertEqual(a, b)
        self.assertNotEqual(b, c)

    def test_utf8_and_gb18030_same_text_have_same_normalized_hash(self):
        text = "class A { String name = \"中文\"; }\n"
        a, _, _ = normalized_hash("src/A.java", text.encode("utf-8"))
        b, encoding, status = normalized_hash("src/A.java", text.encode("gb18030"))
        self.assertEqual(a, b)
        self.assertEqual(encoding, "gb18030")
        self.assertEqual(status, "fallback")

    def test_utf8_and_utf16_bom_same_text_have_same_normalized_hash(self):
        text = "class A { String name = \"中文\"; }\n"
        a, _, _ = normalized_hash("src/A.java", text.encode("utf-8"))
        b, encoding, status = normalized_hash("src/A.java", text.encode("utf-16"))
        self.assertEqual(a, b)
        self.assertIn(encoding, {"utf-16-le", "utf-16-be"})
        self.assertEqual(status, "certain")

    def test_same_size_same_mtime_real_change_is_not_hidden(self):
        p = self.repo / "src" / "A.java"
        write(p, "class A { int x = 1; }\n")
        baseline = build_current_snapshot("repo", self.repo, self.cfg.source)
        st = p.stat()
        write(p, "class A { int x = 2; }\n")
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
        current = build_current_snapshot("repo", self.repo, self.cfg.source, old=baseline)
        self.assertNotEqual(baseline["files"]["src/A.java"]["content_hash"], current["files"]["src/A.java"]["content_hash"])

    def test_default_discovery_excludes_tests_and_reports(self):
        write(self.repo / "src" / "A.java", "class A {}\n")
        write(self.repo / "tests" / "A.java", "class ATest {}\n")
        write(self.repo / "reports" / "run.md", "report\n")
        snap = build_current_snapshot("repo", self.repo, self.cfg.source)
        self.assertIn("src/A.java", snap["files"])
        self.assertNotIn("tests/A.java", snap["files"])
        self.assertNotIn("reports/run.md", snap["files"])

    def test_python_indentation_change_is_semantic(self):
        a, _, _ = normalized_hash("a.py", b"if ok:\n    run()\n")
        b, _, _ = normalized_hash("a.py", b"if ok:\nrun()\n")
        self.assertNotEqual(a, b)

    def test_yaml_indentation_change_is_semantic(self):
        a, _, _ = normalized_hash("a.yaml", b"a:\n  b: 1\n")
        b, _, _ = normalized_hash("a.yaml", b"a:\nb: 1\n")
        self.assertNotEqual(a, b)

    def test_properties_value_only_is_compat_cosmetic(self):
        a, _, _ = normalized_hash("a.properties", b"host=a\nport=1\n", "keys")
        b, _, _ = normalized_hash("a.properties", b"host=b\nport=999\n", "keys")
        self.assertEqual(a, b)

    def test_properties_key_change_is_semantic(self):
        a, _, _ = normalized_hash("a.properties", b"host=a\n", "keys")
        b, _, _ = normalized_hash("a.properties", b"hostname=a\n", "keys")
        self.assertNotEqual(a, b)


class TestChangePlanning(WikiCase):
    def _baseline(self, count: int = 1):
        for i in range(count):
            write(self.repo / "src" / f"A{i}.java", f"class A{i} {{ int x = 1; }}\n")
        snap = build_current_snapshot("repo", self.repo, self.cfg.source)
        paths = snapshot_paths(self.wiki)
        paths["baseline"].parent.mkdir(parents=True, exist_ok=True)
        paths["baseline"].write_text(json.dumps(snap), encoding="utf-8")
        return snap

    def test_new_unbound_source_enters_topology_review(self):
        self._baseline(1)
        write(self.repo / "src" / "NewCore.java", "class NewCore {}\n")
        cs = stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        self.assertEqual(cs["counts"].get("STRUCTURAL"), 1)
        plan = build_plan(self.wiki)
        self.assertTrue(plan["requires_ai_update"])
        self.assertEqual(plan["topology_review"][0]["file"], "src/NewCore.java")

    def test_delete_add_same_normalized_content_is_visible_as_move(self):
        self._baseline(1)
        old = self.repo / "src" / "A0.java"
        new = self.repo / "module" / "A0.java"
        new.parent.mkdir(parents=True, exist_ok=True)
        new.write_bytes(old.read_bytes())
        old.unlink()
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        plan = build_plan(self.wiki)
        self.assertEqual(plan["source_topology"]["moved"][0]["from"], "src/A0.java")
        self.assertEqual(plan["source_topology"]["moved"][0]["to"], "module/A0.java")

    def test_deleted_unbound_source_is_not_mislabeled_as_excluded(self):
        self._baseline(1)
        (self.repo / "src" / "A0.java").unlink()
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        plan = build_plan(
            self.wiki, repo_root=self.repo, source_cfg=self.cfg.source, coverage_cfg=self.cfg.coverage
        )
        row = next(x for x in plan["topology_review"] if x["file"] == "src/A0.java")
        self.assertEqual(row["wiki_eligibility"], "unknown")
        self.assertEqual(row["expected_semantic_action"], "REVIEW_DELETED_OR_OUT_OF_SCOPE_SOURCE_SIGNIFICANCE")

    def test_bulk_line_ending_drift_is_guarded_as_cosmetic(self):
        self._baseline(60)
        for i in range(60):
            p = self.repo / "src" / f"A{i}.java"
            p.write_bytes(f"class A{i} {{ int x = 1; }}\r\n".encode())
        cs = stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        self.assertEqual(cs["counts"].get("COSMETIC"), 60)
        self.assertEqual(cs["guard"]["status"], "BULK_COSMETIC_DRIFT")
        plan = build_plan(self.wiki)
        self.assertFalse(plan["requires_ai_update"])

    def test_mass_semantic_change_requires_explicit_review(self):
        self._baseline(60)
        for i in range(60):
            write(self.repo / "src" / f"A{i}.java", f"class A{i} {{ int x = 2; }}\n")
        cs = stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        self.assertEqual(cs["guard"]["status"], "MASS_CHANGE_REVIEW_REQUIRED")
        with self.assertRaisesRegex(ValueError, "mass change guard"):
            build_plan(self.wiki)
        with self.assertRaisesRegex(ValueError, "review reason"):
            build_plan(self.wiki, allow_mass_change=True)
        plan = build_plan(self.wiki, allow_mass_change=True, mass_change_reason="confirmed repository-wide semantic migration")
        self.assertTrue(plan["mass_change_approved"])
        self.assertTrue(plan["mass_change_review_reason"])
        self.assertTrue(plan["requires_ai_update"])

    def test_cli_context_annotates_topology_with_wiki_eligibility(self):
        self._baseline(1)
        write(self.repo / "src" / "NewCore.java", "class NewCore {}\n")
        write(self.repo / "skills" / "demo" / "agents" / "openai.yaml", "interface: model\n")
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        plan = build_plan(
            self.wiki,
            repo_root=self.repo,
            source_cfg=self.cfg.source,
            coverage_cfg=self.cfg.coverage,
        )
        rows = {row["file"]: row for row in plan["topology_review"]}
        self.assertEqual(rows["src/NewCore.java"]["wiki_eligibility"], "eligible")
        self.assertEqual(rows["src/NewCore.java"]["expected_semantic_action"], "MAP_TO_EXISTING_OR_GROUPED_WIKI")
        self.assertEqual(rows["skills/demo/agents/openai.yaml"]["wiki_eligibility"], "excluded")
        self.assertEqual(rows["skills/demo/agents/openai.yaml"]["eligibility_reason"], "no-independent-wiki-value")
        self.assertTrue(plan["wiki_coverage_expectation"]["available"])
        self.assertTrue(any("existence does not imply authority" in rule for rule in plan["semantic_guardrails"]))


class TestFirstBuildReadinessAndTargeting(WikiCase):
    def test_initial_low_coverage_is_build_incomplete_even_when_warn_threshold_is_zero(self):
        write(self.repo / "src" / "A.java", "class A {}\n")
        write(self.repo / "src" / "B.java", "class B {}\n")
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        write(self.wiki / "index.md", "# Wiki\n\n- [A](a.md)\n")
        write(self.wiki / "a.md", "# A\n\n## 核心逻辑\nA。 <cite path=\"src/A.java\" line=\"1\"/>\n")
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        report = compute_wiki_coverage(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, coverage_cfg=self.cfg.coverage)
        readiness = evaluate_first_build_readiness(
            self.wiki, report, minimum_effective_coverage=float(self.cfg.quality["initial_build_effective_coverage_min"])
        )
        self.assertEqual(float(self.cfg.quality["effective_wiki_coverage_warn"]), 0.0)
        self.assertEqual(readiness["status"], "BUILD_INCOMPLETE")
        self.assertEqual(readiness["eligible"], 2)
        self.assertEqual(readiness["covered"], 1)

    def test_initial_ready_does_not_require_mechanical_100_percent(self):
        report = {"summary": {"wiki_eligible_files": 20, "trusted_covered_files": 19, "effective_wiki_coverage": 0.95}}
        paths = snapshot_paths(self.wiki)
        paths["changeset"].parent.mkdir(parents=True, exist_ok=True)
        paths["changeset"].write_text(json.dumps({"initial": True}), encoding="utf-8")
        readiness = evaluate_first_build_readiness(self.wiki, report, minimum_effective_coverage=0.95)
        self.assertEqual(readiness["status"], "READY")
        self.assertEqual(readiness["uncovered"], 1)

    def test_provenance_only_cites_do_not_create_precise_section_targeting(self):
        text = """# Demo

## 核心逻辑
这里解释真实逻辑。 <cite path="src/A.java" line="1"/>

## 溯源
<cite path="src/B.java" line="1"/>
"""
        sections = extract_citation_sections(text)
        self.assertEqual(sections["src/A.java"], ["核心逻辑"])
        self.assertNotIn("src/B.java", sections)

    def test_verify_warns_when_cites_exist_only_in_provenance_section(self):
        write(self.repo / "src" / "A.java", "class A {}\n")
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        write(self.wiki / "index.md", "# Wiki\n\n- [A](a.md)\n")
        write(self.wiki / "a.md", "# A\n\n## 概述\nA 模块。\n\n## 溯源\n<cite path=\"src/A.java\" line=\"1\"/>\n")
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        report = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality, coverage_cfg=self.cfg.coverage)
        self.assertTrue(any(i["code"] == "CITATION_TARGETING_WEAK" for i in report["issues"]))

    def test_cli_blocks_full_audit_and_snapshot_commit_while_initial_build_incomplete(self):
        write(self.repo / "src" / "A.java", "class A {}\n")
        write(self.repo / "src" / "B.java", "class B {}\n")
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        write(self.wiki / "index.md", "# Wiki\n\n- [A](a.md)\n")
        write(self.wiki / "a.md", "# A\n\n## 核心逻辑\nA。 <cite path=\"src/A.java\" line=\"1\"/>\n")
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        target = SimpleNamespace(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, coverage={})
        args = SimpleNamespace(full=True)
        with patch.object(wiki_commands, "_resolve", return_value=(self.cfg, [target])):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(wiki_commands.cmd_audit(args), 1)
                self.assertEqual(wiki_commands.cmd_snapshot_commit(SimpleNamespace()), 1)


class TestBaselineAndQuality(WikiCase):
    def setUp(self):
        super().setUp()
        write(self.repo / "src" / "A.java", "class A {\n  int x = 1;\n}\n")
        self.target = SimpleNamespace(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki)

    def test_initial_empty_wiki_cannot_pass_and_commit(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        report = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        self.assertEqual(report["result"], "FAIL")
        self.assertTrue(any(i["code"] == "NO_WIKI_DOCUMENTS" for i in report["issues"]))
        with self.assertRaisesRegex(ValueError, "no PASS verification"):
            commit_baseline(self.wiki, repo_id="repo", repo_root=self.repo, source_cfg=self.cfg.source)

    def test_full_verified_semantic_flow_commits_baseline(self):
        cs = stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki)
        manifest = refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        self.assertEqual(len(manifest["documents"]), 2)
        core = next(d for d in manifest["documents"] if d["path"] == "core.md")
        self.assertEqual(core["type"], "content-doc")
        build_plan(self.wiki)
        report = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        self.assertEqual(report["result"], "PASS", report["issues"])
        self.assertTrue(report["semantic_audit_required"])
        build_audit_plan(self.wiki, self.cfg.quality)
        record_semantic_audit(self.wiki, result="PASS", summary="核对 A.java 与 core.md 的职责和引用一致。", documents=["core.md", "index.md"])
        result = commit_baseline(self.wiki, repo_id="repo", repo_root=self.repo, source_cfg=self.cfg.source)
        self.assertEqual(result["result"], "COMMITTED")
        self.assertTrue(snapshot_paths(self.wiki)["baseline"].is_file())
        self.assertFalse(snapshot_paths(self.wiki)["changeset"].exists())

    def test_semantic_flow_requires_l4_audit(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki)
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        with self.assertRaisesRegex(ValueError, "semantic audit PASS"):
            commit_baseline(self.wiki, repo_id="repo", repo_root=self.repo, source_cfg=self.cfg.source)

    def test_wiki_change_after_verify_blocks_audit_and_commit(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki)
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        build_audit_plan(self.wiki, self.cfg.quality)
        write(self.wiki / "core.md", content_doc() + "\n额外修改。\n")
        with self.assertRaisesRegex(ValueError, "changed after deterministic verification"):
            record_semantic_audit(self.wiki, result="PASS", summary="已核对。", documents=["core.md", "index.md"])
        with self.assertRaisesRegex(ValueError, "changed after verification"):
            commit_baseline(self.wiki, repo_id="repo", repo_root=self.repo, source_cfg=self.cfg.source)

    def test_source_change_after_scan_blocks_commit(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki)
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        build_plan(self.wiki)
        verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        build_audit_plan(self.wiki, self.cfg.quality)
        record_semantic_audit(self.wiki, result="PASS", summary="已核对。", documents=["core.md", "index.md"])
        write(self.repo / "src" / "A.java", "class A {\n  int x = 2;\n}\n")
        with self.assertRaisesRegex(ValueError, "source changed after staged scan"):
            commit_baseline(self.wiki, repo_id="repo", repo_root=self.repo, source_cfg=self.cfg.source)

    def test_mass_guard_cannot_be_bypassed_at_commit(self):
        # Lower threshold for a compact fixture.
        snap_cfg = dict(self.cfg.snapshot)
        snap_cfg.update({"mass_change_min_files": 2, "mass_change_ratio": 0.5, "bulk_cosmetic_ratio": 0.8})
        for i in range(3):
            write(self.repo / "src" / f"M{i}.java", f"class M{i} {{ int x = 1; }}\n")
        baseline = build_current_snapshot("repo", self.repo, self.cfg.source)
        paths = snapshot_paths(self.wiki)
        paths["baseline"].parent.mkdir(parents=True, exist_ok=True)
        paths["baseline"].write_text(json.dumps(baseline), encoding="utf-8")
        for i in range(3):
            write(self.repo / "src" / f"M{i}.java", f"class M{i} {{ int x = 2; }}\n")
        cs = stage_scan("repo", self.repo, self.wiki, self.cfg.source, snap_cfg)
        self.assertEqual(cs["guard"]["status"], "MASS_CHANGE_REVIEW_REQUIRED")
        # Even a forged-looking PASS receipt cannot bypass the commit-level guard.
        paths["verification"].write_text(json.dumps({"change_set_id": cs["change_set_id"], "result": "PASS", "subject_digest": "x", "semantic_audit_required": False}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "mass-change guard"):
            commit_baseline(self.wiki, repo_id="repo", repo_root=self.repo, source_cfg=self.cfg.source)

    def test_unsafe_manifest_source_path_is_l1_error(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki)
        manifest = refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        manifest["documents"][0]["dependencies"].append({"file": "../outside.txt", "role": "context", "sections": []})
        write_manifest(self.wiki, manifest)
        report = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        self.assertEqual(report["result"], "FAIL")
        self.assertTrue(any(i["code"] == "DEPENDENCY_PATH_UNSAFE" for i in report["issues"]))

    def test_missing_navigation_index_is_l1_error(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write(self.wiki / "modules" / "core.md", content_doc())
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        report = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        codes = {i["code"] for i in report["issues"]}
        self.assertEqual(report["result"], "FAIL")
        self.assertIn("NAV_INDEX_MISSING", codes)

    def test_completed_content_doc_placeholder_is_l3_error(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki)
        text = (self.wiki / "core.md").read_text(encoding="utf-8")
        text = text.replace("当前模块由 A 类承担主要实现入口，并保持单一职责。", "<!-- TODO -->")
        write(self.wiki / "core.md", text)
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        report = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        codes = {i["code"] for i in report["issues"]}
        self.assertEqual(report["result"], "FAIL")
        self.assertIn("CONTENT_PLACEHOLDER", codes)
        self.assertIn("CONTENT_SECTION_EMPTY", codes)

    def test_broken_local_wiki_link_is_l1_error(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki)
        write(self.wiki / "index.md", "# Wiki 入口\n\n- [不存在](missing.md)\n")
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        report = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        self.assertEqual(report["result"], "FAIL")
        self.assertTrue(any(i["code"] == "WIKI_LINK_BROKEN" for i in report["issues"]))

    def test_parent_navigation_link_inside_wiki_root_is_allowed(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write(self.wiki / "index.md", "# Wiki 入口\n\n- [模块](modules/index.md)\n")
        write(self.wiki / "modules" / "index.md", "# 模块索引\n\n- [返回仓根](../index.md)\n- [A 模块](core.md)\n")
        write(self.wiki / "modules" / "core.md", content_doc())
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        report = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        self.assertFalse(any(i["code"] == "WIKI_LINK_UNSAFE" for i in report["issues"]))

    def test_parent_navigation_cannot_escape_wiki_root(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki)
        write(self.wiki / "index.md", "# Wiki 入口\n\n- [逃逸](../../outside.md)\n")
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        report = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        self.assertTrue(any(i["code"] == "WIKI_LINK_UNSAFE" for i in report["issues"]))

    def test_h1_title_section_word_does_not_shadow_real_h2_section(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki)
        text = (self.wiki / "core.md").read_text(encoding="utf-8")
        text = text.replace("# A 模块", "# A 模块配置说明")
        write(self.wiki / "core.md", text)
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        report = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        self.assertFalse(any(i["code"] == "CONTENT_SECTION_EMPTY" and (i.get("detail") or {}).get("section") == "配置" for i in report["issues"]))

    def test_missing_line_level_citation_below_target_is_l2_error(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki)
        text = (self.wiki / "core.md").read_text(encoding="utf-8").replace(' line="1-3"', '')
        write(self.wiki / "core.md", text)
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        report = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        self.assertEqual(report["result"], "FAIL")
        issue = next(i for i in report["issues"] if i["code"] == "CITATION_LINE_COVERAGE_LOW")
        self.assertEqual(issue["severity"], "ERROR")

    def test_suspicious_whole_file_citation_is_l1_error(self):
        source = "\n".join(f"class A{i} {{}}" for i in range(40)) + "\n"
        write(self.repo / "src" / "A.java", source)
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki)
        text = (self.wiki / "core.md").read_text(encoding="utf-8").replace('line="1-3"', 'line="1-40"')
        write(self.wiki / "core.md", text)
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        report = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        self.assertEqual(report["result"], "FAIL")
        self.assertTrue(any(i["code"] == "CITE_LINE_SUSPICIOUS_FULL_FILE" for i in report["issues"]))

    def test_legacy_knowledge_card_type_migrates_to_concept_card(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki)
        manifest = refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        core = next(d for d in manifest["documents"] if d["path"] == "core.md")
        core["type"] = "knowledge-card"
        write_manifest(self.wiki, manifest)
        migrated = refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        core = next(d for d in migrated["documents"] if d["path"] == "core.md")
        self.assertEqual(core["type"], "concept-card")

    def test_semantic_audit_pass_must_cover_deterministic_audit_scope(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki)
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        build_plan(self.wiki)
        report = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        self.assertEqual(report["result"], "PASS")
        plan = build_audit_plan(self.wiki, self.cfg.quality)
        self.assertEqual(plan["documents"][0]["document"], "core.md")
        with self.assertRaisesRegex(ValueError, "does not cover deterministic audit plan"):
            record_semantic_audit(self.wiki, result="PASS", summary="核验完成。", documents=[])

    def test_cosmetic_blank_comment_shift_relocates_cite_without_model(self):
        write(self.repo / "src" / "A.java", "package demo;\nclass A {\n  int x = 1;\n}\n")
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki)
        text = (self.wiki / "core.md").read_text(encoding="utf-8").replace('line="1-3"', 'line="2-4"')
        write(self.wiki / "core.md", text)
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        build_plan(self.wiki)
        report = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        self.assertEqual(report["result"], "PASS", report["issues"])
        build_audit_plan(self.wiki, self.cfg.quality)
        record_semantic_audit(self.wiki, result="PASS", summary="初始源码与 Wiki cite 已核对。", documents=["core.md", "index.md"])
        commit_baseline(self.wiki, repo_id="repo", repo_root=self.repo, source_cfg=self.cfg.source)
        self.assertTrue((self.wiki / "meta" / "wiki-cite-anchors.json").is_file())

        # Same Java semantics, but comments/blank lines move the class down two lines.
        write(self.repo / "src" / "A.java", "package demo;\n// checkout/export comment\n\nclass A {\n  int x = 1;\n}\n")
        cs = stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        self.assertEqual(cs["counts"].get("COSMETIC"), 1)
        plan = build_plan(self.wiki)
        self.assertFalse(plan["requires_ai_update"])

        # Verify cannot be used to skip the deterministic line-anchor refresh.
        stale = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        self.assertEqual(stale["result"], "FAIL")
        self.assertTrue(any(i["code"] == "CITE_ANCHOR_STALE" for i in stale["issues"]))

        manifest = refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        self.assertEqual(manifest["stats"]["cite_relocations_last_refresh"], 1)
        updated = (self.wiki / "core.md").read_text(encoding="utf-8")
        self.assertIn('path="src/A.java" line="4-6"', updated)
        passed = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        self.assertEqual(passed["result"], "PASS", passed["issues"])
        self.assertFalse(passed["semantic_audit_required"])
        result = commit_baseline(self.wiki, repo_id="repo", repo_root=self.repo, source_cfg=self.cfg.source)
        self.assertEqual(result["result"], "COMMITTED")

    def test_semantic_wiki_edit_skips_stale_positional_anchor_during_cosmetic_source_change(self):
        write(self.repo / "src" / "A.java", "package demo;\nclass A {\n  int x = 1;\n}\n")
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki)
        text = (self.wiki / "core.md").read_text(encoding="utf-8").replace('line="1-3"', 'line="2-4"')
        write(self.wiki / "core.md", text)
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        build_plan(self.wiki)
        verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        build_audit_plan(self.wiki, self.cfg.quality)
        record_semantic_audit(self.wiki, result="PASS", summary="初始核验。", documents=["core.md", "index.md"])
        commit_baseline(self.wiki, repo_id="repo", repo_root=self.repo, source_cfg=self.cfg.source)

        # Source drift is cosmetic, but Wiki prose/citation sequence is also intentionally edited.
        write(self.repo / "src" / "A.java", "package demo;\n// cosmetic checkout comment\n\nclass A {\n  int x = 1;\n}\n")
        cs = stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        self.assertEqual(cs["counts"].get("COSMETIC"), 1)
        edited = (self.wiki / "core.md").read_text(encoding="utf-8")
        edited = edited.replace("## 2. 模块结构", "补充当前语义说明。\n\n## 2. 模块结构")
        # Change citation order/count deliberately; old anchor indexes must not be applied.
        edited = edited.replace('<cite path="src/A.java" line="2-4"/>', '<cite path="src/A.java" line="4-6"/>\n<cite path="src/A.java" line="5"/>')
        write(self.wiki / "core.md", edited)
        manifest = refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        self.assertEqual(manifest["stats"]["cite_relocations_last_refresh"], 0)
        report = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        self.assertEqual(report["result"], "PASS", report["issues"])

    def test_second_no_change_cycle_does_not_require_semantic_audit(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki)
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        build_plan(self.wiki)
        verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        build_audit_plan(self.wiki, self.cfg.quality)
        record_semantic_audit(self.wiki, result="PASS", summary="已核对。", documents=["core.md", "index.md"])
        commit_baseline(self.wiki, repo_id="repo", repo_root=self.repo, source_cfg=self.cfg.source)

        cs = stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        self.assertEqual(cs["raw_changed_count"], 0)
        plan = build_plan(self.wiki)
        self.assertFalse(plan["requires_ai_update"])
        refresh_manifest(workspace_id="ws", repo_id="repo", repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source)
        report = verify_repo(repo_root=self.repo, wiki_repo_root=self.wiki, source_cfg=self.cfg.source, quality_cfg=self.cfg.quality)
        self.assertEqual(report["result"], "PASS")
        self.assertFalse(report["semantic_audit_required"])
        result = commit_baseline(self.wiki, repo_id="repo", repo_root=self.repo, source_cfg=self.cfg.source)
        self.assertEqual(result["result"], "COMMITTED")



class TestCoverageAndSemanticClosure(WikiCase):
    def setUp(self):
        super().setUp()
        write(self.repo / "src" / "Main.java", "class Main { void run() {} }\n")
        write(self.repo / "src" / "UserMapper.xml", "<mapper></mapper>\n")
        write(self.repo / "src" / "theme.css", "body { color: black; }\n")
        write(self.repo / "README.md", "# Repo docs\n")
        write(self.repo / "agents" / "tp-demo" / "SKILL.md", "# Demo contract\n")
        write(self.repo / "VERSION", "5.1.3\n")

    def test_governance_markdown_contract_is_wiki_eligible(self):
        write(self.repo / "governance" / "lifecycle.md", "# Runtime contract\n")
        classified = __import__("cli.wiki.coverage", fromlist=["classify_wiki_eligible_sources"]).classify_wiki_eligible_sources(
            self.repo, self.cfg.source, self.cfg.coverage
        )
        self.assertIn("governance/lifecycle.md", classified["eligible"])

    def test_effective_coverage_uses_eligible_denominator_and_does_not_count_reference_only(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write(self.wiki / "index.md", "# Wiki\n\n- [Core](core.md)\n")
        write(self.wiki / "core.md", content_doc("src/Main.java"))
        manifest = refresh_manifest(
            workspace_id="ws", repo_id="repo", repo_root=self.repo,
            wiki_repo_root=self.wiki, source_cfg=self.cfg.source,
        )
        core = next(d for d in manifest["documents"] if d["path"] == "core.md")
        # A metadata-only reference must not inflate the headline coverage.
        fp = __import__("cli.wiki.source", fromlist=["fingerprint_file"]).fingerprint_file(
            self.repo, "agents/tp-demo/SKILL.md", self.cfg.source
        )
        core["dependencies"].append({
            "file": "agents/tp-demo/SKILL.md", "role": "reference", "sections": [],
            "content_hash": fp.content_hash, "normalized_hash": fp.normalized_hash, "encoding": fp.encoding,
        })
        write_manifest(self.wiki, manifest)

        report = compute_wiki_coverage(
            repo_root=self.repo, wiki_repo_root=self.wiki,
            source_cfg=self.cfg.source, coverage_cfg=self.cfg.coverage, include_details=True,
        )
        s = report["summary"]
        # Mapper XML, CSS and generic README are excluded from the effective denominator.
        self.assertEqual(s["wiki_eligible_files"], 3)  # Main.java, agents/.../SKILL.md, VERSION
        self.assertEqual(s["trusted_covered_files"], 1)
        self.assertAlmostEqual(s["effective_wiki_coverage"], 1 / 3)
        self.assertEqual(s["reference_only_not_counted"], 1)
        reasons = report["excluded_by_reason"]
        self.assertEqual(reasons["no-independent-wiki-value"], 1)
        self.assertEqual(reasons["low-signal-asset"], 1)
        self.assertEqual(reasons["documentation-artifact"], 1)

    def test_citation_or_primary_context_with_current_normalized_hash_counts_as_covered(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki, "src/Main.java")
        manifest = refresh_manifest(
            workspace_id="ws", repo_id="repo", repo_root=self.repo,
            wiki_repo_root=self.wiki, source_cfg=self.cfg.source,
        )
        report = compute_wiki_coverage(
            repo_root=self.repo, wiki_repo_root=self.wiki,
            source_cfg=self.cfg.source, coverage_cfg=self.cfg.coverage,
        )
        self.assertEqual(report["summary"]["trusted_covered_files"], 1)
        self.assertEqual(report["summary"]["citation_evidence_files"], 1)
        self.assertEqual(report["summary"]["citation_only_covered_files"] + report["summary"]["dual_evidence_files"], 1)
        self.assertGreater(report["summary"]["citation_evidence_coverage"], 0)

    def test_stale_wiki_document_does_not_count_coverage_until_manifest_refresh(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki, "src/Main.java")
        refresh_manifest(
            workspace_id="ws", repo_id="repo", repo_root=self.repo,
            wiki_repo_root=self.wiki, source_cfg=self.cfg.source,
        )
        # The source is unchanged, but prose changed after deterministic manifest refresh.
        # A standalone coverage run must not trust the stale manifest relationship.
        with (self.wiki / "core.md").open("a", encoding="utf-8", newline="\n") as fh:
            fh.write("\n补充但尚未 refresh 的说明。\n")
        report = compute_wiki_coverage(
            repo_root=self.repo, wiki_repo_root=self.wiki,
            source_cfg=self.cfg.source, coverage_cfg=self.cfg.coverage, include_details=True,
        )
        self.assertEqual(report["summary"]["trusted_covered_files"], 0)
        self.assertEqual(report["summary"]["stale_wiki_documents"], 1)
        self.assertEqual(report["details"]["stale_wiki_documents"], ["core.md"])

    def test_bilingual_numbered_heading_matches_logical_section_binding(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write(self.wiki / "index.md", "# Wiki\n\n- [Core](core.md)\n")
        write(self.wiki / "core.md", "# Core\n\n## 1. 概述 (Overview)\n\nMain semantics.\n")
        manifest = refresh_manifest(
            workspace_id="ws", repo_id="repo", repo_root=self.repo,
            wiki_repo_root=self.wiki, source_cfg=self.cfg.source,
        )
        core = next(d for d in manifest["documents"] if d["path"] == "core.md")
        fp = __import__("cli.wiki.source", fromlist=["fingerprint_file"]).fingerprint_file(
            self.repo, "src/Main.java", self.cfg.source
        )
        core["dependencies"] = [{
            "file": "src/Main.java", "role": "primary", "sections": ["概述"],
            "content_hash": fp.content_hash, "normalized_hash": fp.normalized_hash, "encoding": fp.encoding,
        }]
        write_manifest(self.wiki, manifest)
        report = compute_wiki_coverage(
            repo_root=self.repo, wiki_repo_root=self.wiki,
            source_cfg=self.cfg.source, coverage_cfg=self.cfg.coverage,
        )
        self.assertEqual(report["summary"]["trusted_covered_files"], 1)
        self.assertEqual(report["summary"]["invalid_section_binding_files"], 0)

    def test_primary_context_without_real_section_binding_does_not_count(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write(self.wiki / "index.md", "# Wiki\n\n- [Core](core.md)\n")
        # No cite on purpose; this test exercises semantic dependency coverage.
        write(self.wiki / "core.md", content_doc("src/Main.java").replace(
            ' <cite path="src/Main.java" line="1-3"/>', ''
        ))
        manifest = refresh_manifest(
            workspace_id="ws", repo_id="repo", repo_root=self.repo,
            wiki_repo_root=self.wiki, source_cfg=self.cfg.source,
        )
        core = next(d for d in manifest["documents"] if d["path"] == "core.md")
        fp = __import__("cli.wiki.source", fromlist=["fingerprint_file"]).fingerprint_file(
            self.repo, "src/Main.java", self.cfg.source
        )
        core["dependencies"] = [{
            "file": "src/Main.java", "role": "primary", "sections": [],
            "content_hash": fp.content_hash, "normalized_hash": fp.normalized_hash, "encoding": fp.encoding,
        }]
        write_manifest(self.wiki, manifest)
        report = compute_wiki_coverage(
            repo_root=self.repo, wiki_repo_root=self.wiki,
            source_cfg=self.cfg.source, coverage_cfg=self.cfg.coverage, include_details=True,
        )
        self.assertEqual(report["summary"]["trusted_covered_files"], 0)
        self.assertEqual(report["summary"]["invalid_section_binding_files"], 1)

        # Bind the same edge to a section that exists in the current Wiki doc.
        core["dependencies"][0]["sections"] = ["概述"]
        write_manifest(self.wiki, manifest)
        report = compute_wiki_coverage(
            repo_root=self.repo, wiki_repo_root=self.wiki,
            source_cfg=self.cfg.source, coverage_cfg=self.cfg.coverage,
        )
        self.assertEqual(report["summary"]["trusted_covered_files"], 1)
        self.assertEqual(report["summary"]["primary_context_coverage"], 1 / 3)

    def test_stale_dependency_does_not_count_as_effective_coverage(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki, "src/Main.java")
        refresh_manifest(
            workspace_id="ws", repo_id="repo", repo_root=self.repo,
            wiki_repo_root=self.wiki, source_cfg=self.cfg.source,
        )
        # Change semantics after manifest provenance was computed.
        write(self.repo / "src" / "Main.java", "class Main { void changed() {} }\n")
        report = compute_wiki_coverage(
            repo_root=self.repo, wiki_repo_root=self.wiki,
            source_cfg=self.cfg.source, coverage_cfg=self.cfg.coverage,
        )
        self.assertEqual(report["summary"]["trusted_covered_files"], 0)
        self.assertEqual(report["summary"]["stale_claimed_files"], 1)

    def test_initial_semantic_audit_is_full_repo_not_sampled(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki, "src/Main.java")
        write(self.wiki / "concept.md", "# Concept\n\n当前说明。\n")
        refresh_manifest(
            workspace_id="ws", repo_id="repo", repo_root=self.repo,
            wiki_repo_root=self.wiki, source_cfg=self.cfg.source,
        )
        build_plan(self.wiki)
        verify_repo(
            repo_root=self.repo, wiki_repo_root=self.wiki,
            source_cfg=self.cfg.source, quality_cfg=self.cfg.quality, coverage_cfg=self.cfg.coverage,
        )
        plan = build_audit_plan(self.wiki, self.cfg.quality)
        self.assertEqual(plan["audit_scope"], "initial-full-repo")
        self.assertFalse(plan["coverage"]["sampling_of_affected_documents"])
        challenge_ids = {row["id"] for row in plan["semantic_challenges"]}
        self.assertEqual(
            challenge_ids,
            {"currentity", "existence-vs-authority", "responsibility-attribution", "pipeline-stage-owner", "active-contract", "cite-strength", "interface-scope-exactness"},
        )
        self.assertTrue(any("adversarially" in instruction for instruction in plan["instructions"]))
        self.assertEqual(
            {d["document"] for d in plan["documents"]},
            {"core.md", "index.md", "concept.md"},
        )

    def test_current_version_assertion_mismatch_is_deterministic_error(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki, "src/Main.java")
        stale_version = ".".join(["5", "1", "2"])
        write(self.wiki / "version.md", f"# Version\n\n当前基座版本为 `{stale_version}`。\n")
        refresh_manifest(
            workspace_id="ws", repo_id="repo", repo_root=self.repo,
            wiki_repo_root=self.wiki, source_cfg=self.cfg.source,
        )
        report = verify_repo(
            repo_root=self.repo, wiki_repo_root=self.wiki,
            source_cfg=self.cfg.source, quality_cfg=self.cfg.quality, coverage_cfg=self.cfg.coverage,
        )
        self.assertEqual(report["result"], "FAIL")
        self.assertTrue(any(i["code"] == "CANONICAL_VERSION_ASSERTION_STALE" for i in report["issues"]))

    def test_manifest_refresh_derives_citation_section_targets_for_incremental_planning(self):
        write_standard_wiki(self.wiki, "src/Main.java")
        manifest = refresh_manifest(
            workspace_id="ws", repo_id="repo", repo_root=self.repo,
            wiki_repo_root=self.wiki, source_cfg=self.cfg.source,
        )
        core = next(d for d in manifest["documents"] if d["path"] == "core.md")
        dep = next(d for d in core["dependencies"] if d["file"] == "src/Main.java")
        self.assertEqual(dep["role"], "reference")
        self.assertEqual(dep["sections"], ["1. 概述"])

        baseline = build_current_snapshot("repo", self.repo, self.cfg.source)
        paths = snapshot_paths(self.wiki)
        paths["baseline"].parent.mkdir(parents=True, exist_ok=True)
        paths["baseline"].write_text(json.dumps(baseline), encoding="utf-8")
        write(self.repo / "src" / "Main.java", "class Main { void changed() {} }\n")
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        plan = build_plan(
            self.wiki, repo_root=self.repo, source_cfg=self.cfg.source, coverage_cfg=self.cfg.coverage
        )
        affected = next(row for row in plan["affected_documents"] if row["document"] == "core.md")
        self.assertEqual(affected["sections"], ["1. 概述"])

    def test_manifest_refresh_recomputes_current_document_sections(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write(self.wiki / "index.md", "# Wiki\n\n## Current\n")
        manifest = refresh_manifest(
            workspace_id="ws", repo_id="repo", repo_root=self.repo,
            wiki_repo_root=self.wiki, source_cfg=self.cfg.source,
        )
        doc = next(d for d in manifest["documents"] if d["path"] == "index.md")
        doc["sections"] = ["Stale"]
        write_manifest(self.wiki, manifest)
        refreshed = refresh_manifest(
            workspace_id="ws", repo_id="repo", repo_root=self.repo,
            wiki_repo_root=self.wiki, source_cfg=self.cfg.source,
        )
        doc = next(d for d in refreshed["documents"] if d["path"] == "index.md")
        self.assertEqual(doc["sections"], ["Current"])

    def test_manifest_refresh_removes_misleading_single_generator_provenance(self):
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki, "src/Main.java")
        manifest = refresh_manifest(
            workspace_id="ws", repo_id="repo", repo_root=self.repo,
            wiki_repo_root=self.wiki, source_cfg=self.cfg.source,
        )
        manifest["generator"] = {"type": "ai", "model": "old-model"}
        manifest["branch"] = "stale/copied-branch"
        write_manifest(self.wiki, manifest)
        refreshed = refresh_manifest(
            workspace_id="ws", repo_id="repo", repo_root=self.repo,
            wiki_repo_root=self.wiki, source_cfg=self.cfg.source,
        )
        self.assertNotIn("generator", refreshed)
        self.assertNotIn("branch", refreshed)
        self.assertEqual(refreshed["provenance"]["manifest_refresh"]["type"], "deterministic")
        self.assertEqual(refreshed["provenance"]["semantic_content"]["model"], "not-recorded")



    def test_standalone_full_audit_requires_every_manifest_document(self):
        write(self.repo / "src" / "Main.java", "class Main {\n  void run() {}\n}\n")
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki, "src/Main.java")
        write(self.wiki / "concept.md", "# Concept\n\n当前语义说明由 Main 的运行入口支持。 <cite path=\"src/Main.java\" line=\"1-3\"/>\n")
        refresh_manifest(
            workspace_id="ws", repo_id="repo", repo_root=self.repo,
            wiki_repo_root=self.wiki, source_cfg=self.cfg.source,
        )
        # Standalone audit is valid after a current deterministic verify even without
        # a pending source change set.
        paths = snapshot_paths(self.wiki)
        if paths["changeset"].is_file():
            paths["changeset"].unlink()
        if paths["plan"].is_file():
            paths["plan"].unlink()
        report = verify_repo(
            repo_root=self.repo, wiki_repo_root=self.wiki,
            source_cfg=self.cfg.source, quality_cfg=self.cfg.quality, coverage_cfg=self.cfg.coverage,
        )
        self.assertEqual(report["result"], "PASS", report["issues"])
        plan = build_audit_plan(self.wiki, self.cfg.quality, full=True)
        self.assertEqual(plan["mode"], "standalone")
        self.assertEqual(plan["audit_scope"], "standalone-full-repo")
        required = {d["document"] for d in plan["documents"]}
        self.assertEqual(required, {"core.md", "index.md", "concept.md"})
        with self.assertRaisesRegex(ValueError, "does not cover deterministic audit plan"):
            record_semantic_audit(
                self.wiki, result="PASS", summary="只检查了一部分。", documents=["core.md"]
            )
        receipt = record_semantic_audit(
            self.wiki, result="PASS", summary="完整检查全部持久 Wiki 文档。", documents=sorted(required)
        )
        self.assertEqual(receipt["mode"], "standalone")
        self.assertEqual(receipt["audit_scope"], "standalone-full-repo")

    def test_coverage_receipt_does_not_stale_verified_wiki_subject(self):
        write(self.repo / "src" / "Main.java", "class Main {\n  void run() {}\n}\n")
        stage_scan("repo", self.repo, self.wiki, self.cfg.source, self.cfg.snapshot)
        build_plan(self.wiki)
        write_standard_wiki(self.wiki, "src/Main.java")
        refresh_manifest(
            workspace_id="ws", repo_id="repo", repo_root=self.repo,
            wiki_repo_root=self.wiki, source_cfg=self.cfg.source,
        )
        report = verify_repo(
            repo_root=self.repo, wiki_repo_root=self.wiki,
            source_cfg=self.cfg.source, quality_cfg=self.cfg.quality, coverage_cfg=self.cfg.coverage,
        )
        self.assertEqual(report["result"], "PASS", report["issues"])
        before = report["subject_digest"]
        coverage = compute_wiki_coverage(
            repo_root=self.repo, wiki_repo_root=self.wiki,
            source_cfg=self.cfg.source, coverage_cfg=self.cfg.coverage,
        )
        __import__("cli.wiki.coverage", fromlist=["write_coverage_report"]).write_coverage_report(self.wiki, coverage)
        from cli.wiki.snapshot import wiki_subject_digest
        self.assertEqual(wiki_subject_digest(self.wiki), before)
        plan = build_audit_plan(self.wiki, self.cfg.quality, full=True)
        required = sorted(d["document"] for d in plan["documents"])
        receipt = record_semantic_audit(
            self.wiki, result="PASS", summary="coverage receipt is volatile run metadata", documents=required,
            topology_reviewed=bool(plan.get("topology_review_required")),
        )
        self.assertEqual(receipt["result"], "PASS")

    def test_zero_eligible_coverage_is_na_not_fake_one_hundred_percent(self):
        # Remove the default eligible files, leaving only known no-doc/low-signal material.
        for rel in ("src/Main.java", "agents/tp-demo/SKILL.md", "VERSION"):
            p = self.repo / rel
            if p.exists():
                p.unlink()
        report = compute_wiki_coverage(
            repo_root=self.repo, wiki_repo_root=self.wiki,
            source_cfg=self.cfg.source, coverage_cfg=self.cfg.coverage,
        )
        self.assertEqual(report["summary"]["wiki_eligible_files"], 0)
        self.assertIsNone(report["summary"]["effective_wiki_coverage"])

    def test_registry_repo_can_override_coverage_eligibility_without_narrowing_scanner(self):
        central = self.root / "central-wiki"
        registry = central / "00-system" / "repo-registry.yaml"
        write(registry, yaml.safe_dump({
            "version": 1,
            "workspaces": [{
                "id": "ws",
                "workspace_root": str(self.workspace),
                "repos": [{
                    "id": "repo", "repo_root": str(self.repo), "enabled": True,
                    "coverage": {"no_doc_globs": ["**/Generated*.java"]},
                }],
            }],
        }, sort_keys=False))
        override = self.workspace / ".ai-work" / "config" / "content-systems.yaml"
        write(override, yaml.safe_dump({"systems": {"wiki": {"root": str(central)}}}, sort_keys=False))
        write(self.repo / "src" / "GeneratedClient.java", "class GeneratedClient {}\n")
        cfg = load_content_systems(self.workspace, base_config_path=BASE_CONFIG, installation_config_path=self.installation_config)
        target = resolve_targets(cfg, repo_id="repo")[0]
        self.assertEqual(target.coverage["no_doc_globs"], ["**/Generated*.java"])
        merged = dict(cfg.coverage)
        merged.update(target.coverage or {})
        classified = __import__("cli.wiki.coverage", fromlist=["classify_wiki_eligible_sources"]).classify_wiki_eligible_sources(
            self.repo, cfg.source, merged
        )
        self.assertIn("src/GeneratedClient.java", classified["discovered"])
        self.assertNotIn("src/GeneratedClient.java", classified["eligible"])
        excluded = {row["file"]: row["reason"] for row in classified["excluded"]}
        self.assertEqual(excluded["src/GeneratedClient.java"], "no-independent-wiki-value")


class TestWikiContracts(unittest.TestCase):
    def test_cmd_plan_keeps_resolved_config_for_source_and_coverage(self):
        args = SimpleNamespace(allow_mass_change=False, mass_change_reason="")
        cfg = SimpleNamespace(source={"include_extensions": [".py"]}, coverage={"no_doc_globs": []})
        target = SimpleNamespace(
            repo_id="repo", repo_root=Path("repo"), wiki_repo_root=Path("wiki"), coverage={}
        )
        captured = {}

        def fake_build_plan(wiki_repo_root, **kwargs):
            captured.update(kwargs)
            return {"schema": "test-plan"}

        with patch.object(wiki_commands, "_resolve", return_value=(cfg, [target])), \
             patch.object(wiki_commands, "build_plan", side_effect=fake_build_plan):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = wiki_commands.cmd_plan(args)

        self.assertEqual(rc, 0)
        self.assertEqual(captured["source_cfg"], cfg.source)
        self.assertEqual(captured["coverage_cfg"], cfg.coverage)
        self.assertIn('"status": "PASS"', buf.getvalue())

    def test_cli_has_wiki_group(self):
        parser = build_parser()
        args = parser.parse_args(["wiki", "status", "--workspace-root", "."])
        self.assertEqual(args.group, "wiki")
        self.assertEqual(args.wiki_cmd, "status")
        self.assertEqual(parser.parse_args(["wiki", "build"]).wiki_cmd, "build")
        self.assertEqual(parser.parse_args(["wiki", "audit"]).wiki_cmd, "audit")
        self.assertEqual(parser.parse_args(["wiki", "coverage"]).wiki_cmd, "coverage")

    def test_tp_wiki_is_code_understanding_not_task_or_knowledge(self):
        text = (BASE / "agents" / "tp-wiki" / "SKILL.md").read_text(encoding="utf-8")
        for token in ("代码理解", "Source Code", "Content Systems Resolver", "COSMETIC", "MASS_CHANGE_REVIEW_REQUIRED", "snapshot-commit", "L4 Semantic Audit", "Interface / Scope Exactness"):
            self.assertIn(token, text)
        self.assertIn("不触发任务状态", text)
        self.assertIn("不得写入 canonical Knowledge", text)
        self.assertNotIn("D:\\private\\central-wiki", text)

    def test_tp_knowledge_uses_resolved_targets_and_junction_is_compat(self):
        text = (BASE / "agents" / "tp-knowledge" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Content Systems Resolver", text)
        self.assertIn("knowledge_physical_root", text)
        self.assertIn("Junction 仅是兼容/浏览入口", text)
        self.assertIn("automation/", text)
        self.assertNotIn("D:\\private\\knowledge-vault", text)

    def test_scheduler_uses_versioned_canonical_prompt(self):
        boot = (BASE / "automation" / "wiki" / "SCHEDULER_BOOTSTRAP.md").read_text(encoding="utf-8")
        daily = (BASE / "automation" / "wiki" / "daily-maintenance.md").read_text(encoding="utf-8")
        wrapper = (BASE / "scripts" / "Invoke-AiWorkCli.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("automation/wiki/daily-maintenance.md", boot)
        self.assertIn("Invoke-AiWorkCli.ps1", boot)
        self.assertIn("MASS_CHANGE_REVIEW_REQUIRED", daily)
        self.assertIn("snapshot-commit", daily)
        self.assertIn("baseline", daily)
        self.assertIn("Resolve-AiWorkBaseRoot", wrapper)
        self.assertIn("cli\\main.py", wrapper)

    def test_wiki_standard_and_initialized_data_do_not_embed_tools_directory(self):
        self.assertFalse((BASE / "wiki" / "tools").exists())
        with tempfile.TemporaryDirectory(prefix="v513-wiki-data-") as td:
            data_root = Path(td) / "wiki" / "repo"
            (data_root / "meta").mkdir(parents=True)
            self.assertFalse((data_root / "tools").exists())

    def test_cite_anchor_schema_is_versioned_machine_metadata(self):
        schema = (BASE / "wiki" / "schema" / "wiki-cite-anchors.schema.yaml").read_text(encoding="utf-8")
        self.assertIn("ai-work.wiki-cite-anchors/v1", schema)
        self.assertIn("COSMETIC", schema)
        self.assertIn("snapshot_id", schema)


if __name__ == "__main__":
    unittest.main(verbosity=2)
