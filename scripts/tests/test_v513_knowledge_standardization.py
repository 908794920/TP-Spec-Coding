# -*- coding: utf-8 -*-
"""V5.1.3 Knowledge Content System standardization regression."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import yaml

from cli.content_systems import load_content_systems
from cli.knowledge.eval import evaluate
from cli.knowledge.common import load_source_registry
from cli.knowledge.ingest import disposition, finalize_batch, register_batch
from cli.knowledge.lint import lint_knowledge
from cli.knowledge.migration import migration_plan
from cli.knowledge.normalization import normalization_plan, apply_normalization
from cli.knowledge.projection import build_projection, projection_status, search, telemetry_summary
from cli.knowledge.state import commit_snapshot, create_audit_plan, maintain, record_audit, stage_scan, verify

BASE = Path(__file__).resolve().parents[2]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


class KnowledgeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="v513-knowledge-")
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "workspace"
        self.vault = self.root / "vault"
        self.workspace.mkdir(); self.vault.mkdir()
        write(self.workspace / ".tp-spec/config/content-systems.yaml", f'''schema: tp-spec.content-systems/v1
systems:
  knowledge:
    root: "{self.vault.as_posix()}"
''')
        write(self.vault / "00-system/project-registry.yaml", f'''registry_version: "1.0.0"
projects:
  - id: demo
    display_name: Demo
    source_dir: Demo
    aliases: [Demo]
    status: active
    workspace_roots:
      - "{self.workspace.as_posix()}"
shared_scopes:
  - id: shared
    display_name: Shared
    status: active
''')
        self.cfg = load_content_systems(self.workspace)

    def tearDown(self):
        self.tmp.cleanup()

    def canonical(self, rel: str, *, cid: str, kind: str, title: str, source_refs="[]", evidence_refs="", relations="[]", body=""):
        evidence = f"\nevidence_refs:\n{evidence_refs}" if evidence_refs else ""
        write(self.vault / rel, f'''---
id: {cid}
title: {title}
project: demo
kind: {kind}
status: active
canonical: true
source_refs: {source_refs}
confidence: 0.9
last_verified: '2026-08-11'
relations: {relations}{evidence}
---
# {title}
{body or title + " knowledge"}
''')


class TestKnowledgeContracts(KnowledgeCase):
    def test_shared_resolver_exposes_knowledge_projection_and_evaluation(self):
        self.assertEqual(self.cfg.paths.knowledge_physical_root, self.vault.resolve())
        self.assertEqual(self.cfg.paths.knowledge_projection_db, (self.vault / ".ai-kb/knowledge.db").resolve(strict=False))
        self.assertEqual(self.cfg.knowledge_retrieval["strategy"], "canonical-first-fts5")
        self.assertEqual(self.cfg.knowledge_projection["vector_mode"], "retired-compatible")
        self.assertEqual(self.cfg.knowledge_evaluation["golden_set"], "00-system/eval/golden.jsonl")

    def test_migration_plan_is_read_only_and_classifies_retired_model_services(self):
        write(self.vault / "00-system/model-services/client-config.yaml", "legacy: true\n")
        write(self.vault / "00-system/runbooks/cutover.md", "# old cutover\n")
        write(self.vault / ".pytest_cache/CACHEDIR.TAG", "Signature: 8a477f597d28d172789f06886806bc55\n")
        plan = migration_plan(self.cfg)
        archived = {x["path"] for x in plan["groups"]["ARCHIVE_AFTER_ACCEPTANCE"]}
        generated = {x["path"] for x in plan["groups"]["GENERATED_OR_REBUILDABLE"]}
        self.assertIn("00-system/model-services", archived)
        self.assertIn("00-system/runbooks", archived)
        self.assertIn(".pytest_cache", generated)
        self.assertEqual(plan["unclassified_count"], 0, plan)
        self.assertTrue(plan["read_only"])

    def test_role_split_and_conversational_scheduler(self):
        base_skill=(BASE/"agents/tp-base-maintenance/SKILL.md").read_text(encoding="utf-8")
        knowledge=(BASE/"agents/tp-knowledge/SKILL.md").read_text(encoding="utf-8")
        boot=(BASE/"automation/knowledge/SCHEDULER_BOOTSTRAP.md").read_text(encoding="utf-8")
        daily=(BASE/"automation/knowledge/daily-maintenance.md").read_text(encoding="utf-8")
        knowledge_rule=(BASE/"governance/knowledge-rule.yaml").read_text(encoding="utf-8")
        delivery=(BASE/"skills/tp-integration-engineer/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("TP-Spec-Coding Installation + Project Binding", base_skill)
        self.assertIn("Workspace Inventory", base_skill)
        self.assertIn("Project Scope", base_skill)
        self.assertIn("SYNC_REQUIRED", base_skill)
        self.assertIn("Knowledge", knowledge)
        self.assertNotIn("project bootstrap", knowledge)
        self.assertIn("canonical-first FTS5", knowledge)
        self.assertIn("对话模型", boot)
        self.assertIn("automation/knowledge/daily-maintenance.md", boot)
        self.assertIn("AskUserQuestion", daily)
        self.assertIn("knowledge scan", daily)
        self.assertIn("VALIDATE_AND_INDEX", daily)
        self.assertIn("knowledge index update\nknowledge verify", daily)
        self.assertIn("tp-spec knowledge search", knowledge_rule)
        self.assertIn("tp-knowledge", knowledge_rule)
        self.assertNotIn("PRIVATE_VAULT_ROOT", knowledge_rule)
        self.assertIn("compact `knowledge_handoff`", delivery)
        self.assertIn("task-scoped convergence", delivery)
        self.assertIn("Integration 不做 Knowledge qualification", delivery)
        self.assertIn("task-scoped", knowledge)

    def test_lint_accepts_verifies_and_structured_code_evidence(self):
        self.canonical("10-projects/demo/30-features/DEMO-FEAT-001-Feature.md", cid="DEMO-FEAT-001", kind="feature", title="Feature", source_refs="[TASK-1]")
        self.canonical(
            "10-projects/demo/70-operations/DEMO-OPS-001-Verify.md", cid="DEMO-OPS-001", kind="operation", title="Verify", source_refs="[]",
            evidence_refs="  - type: code\n    ref: src/check.py\n    locator: verify()",
            relations="[{type: verifies, target: DEMO-FEAT-001}]",
        )
        result=lint_knowledge(self.cfg)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["errors"], 0)


    def test_legacy_source_catalog_project_id_is_preserved_and_advisories_do_not_block_verify(self):
        self.canonical(
            "10-projects/demo/30-features/DEMO-FEAT-001-Legacy.md",
            cid="DEMO-FEAT-001", kind="feature", title="Legacy",
            source_refs="[SRC-demo-001]", body="[[DEMO-OTHER-001]]",
        )
        write(
            self.vault / "00-system/migration/source-catalog.jsonl",
            json.dumps({
                "source_id": "SRC-demo-001",
                "project_id": "demo",
                "old_path": "external/legacy.docx",
                "new_path": "10-projects/demo/90-sources/SRC-demo-001.md",
                "sha256": "a" * 64,
            }, ensure_ascii=False) + "\n",
        )
        registry = load_source_registry(self.cfg)
        self.assertEqual(registry["SRC-demo-001"]["project"], "demo")
        build_projection(self.cfg)
        lint = lint_knowledge(self.cfg)
        self.assertEqual(lint["errors"], 0, lint)
        self.assertEqual(lint["warnings"], 0, lint)
        self.assertGreaterEqual(lint["advisories"], 1)
        verified = verify(self.cfg)
        self.assertEqual(verified["status"], "PASS", verified)

    def test_legacy_symbolic_source_and_basename_wikilink_are_migration_warnings(self):
        self.canonical("10-projects/demo/30-features/DEMO-FEAT-001-Legacy.md", cid="DEMO-FEAT-001", kind="feature", title="Legacy", source_refs="[SRC-shared-legacy]", body="[[DEMO-OTHER-001]]")
        result=lint_knowledge(self.cfg)
        self.assertEqual(result["errors"], 0, result)
        rules={x["rule_id"] for x in result["advisory_records"]}
        self.assertIn("K015", rules); self.assertIn("K010", rules)
        self.assertEqual(result["warnings"], 0)


class TestProjectionAndBaseline(KnowledgeCase):
    def setUp(self):
        super().setUp()
        self.canonical("10-projects/demo/30-features/DEMO-FEAT-001-Access.md", cid="DEMO-FEAT-001", kind="feature", title="Access Control", source_refs="[TASK-ACCESS]", body="园区门禁授权 取消授权 access_auth_status")
        self.canonical("10-projects/demo/70-operations/DEMO-OPS-001-Check.md", cid="DEMO-OPS-001", kind="operation", title="Check", source_refs="[TASK-CHECK]", body="检查门禁授权状态")

    def test_projection_search_telemetry_hash_only_and_retired_vector_warning(self):
        built=build_projection(self.cfg)
        self.assertTrue(built["fresh"])
        hits=search(self.cfg,"门禁授权",limit=5)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["layer"], "canonical")
        summary=telemetry_summary(self.cfg,days=7)
        self.assertEqual(summary["queries"],1)
        conn=sqlite3.connect(self.cfg.paths.knowledge_projection_db)
        row=conn.execute("SELECT query_hash FROM retrieval_runs ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row[0], hashlib.sha256("门禁授权".encode("utf-8")).hexdigest())
        cols=[r[1] for r in conn.execute("PRAGMA table_info(retrieval_runs)")]
        self.assertNotIn("query",cols)
        chunk_id=conn.execute("SELECT id FROM chunks LIMIT 1").fetchone()[0]
        conn.execute("INSERT INTO chunk_embeddings(chunk_id,content_hash,chunker_version,embedding_model,dim,vector,config_hash,created_at) VALUES(?,?,?,?,?,?,?,?)",(chunk_id,"0"*64,"legacy","retired",1,b"x","legacy","2026-08-11T00:00:00Z"))
        conn.commit(); conn.close()
        status=projection_status(self.cfg)
        self.assertEqual(status["status"],"WARN")
        self.assertTrue(any("embedding rows" in x for x in status["issues"]))

    def test_initial_baseline_is_fail_closed_and_commits_after_index_verify_l4(self):
        m=maintain(self.cfg)
        self.assertEqual(m["status"],"INITIAL_BASELINE_REQUIRED")
        before=verify(self.cfg)
        self.assertEqual(before["status"],"FAIL")
        build_projection(self.cfg)
        ok=verify(self.cfg)
        self.assertEqual(ok["status"],"PASS",ok)
        plan=create_audit_plan(self.cfg,full=True)
        self.assertTrue(plan["required"])
        record_audit(self.cfg,result="PASS",summary="reviewed",documents=plan["mandatory_documents"])
        committed=commit_snapshot(self.cfg)
        self.assertTrue(committed["baseline_advanced"])

    def _commit_initial_baseline(self):
        self.assertEqual(maintain(self.cfg)["status"], "INITIAL_BASELINE_REQUIRED")
        build_projection(self.cfg)
        self.assertEqual(verify(self.cfg)["status"], "PASS")
        plan = create_audit_plan(self.cfg, full=True)
        record_audit(self.cfg, result="PASS", summary="initial reviewed", documents=plan["mandatory_documents"])
        return commit_snapshot(self.cfg)

    def test_canonical_only_change_is_validate_and_index(self):
        self._commit_initial_baseline()
        target = self.vault / "10-projects/demo/30-features/DEMO-FEAT-001-Access.md"
        target.write_text(target.read_text(encoding="utf-8") + "\n新增已验证规则。\n", encoding="utf-8", newline="\n")
        result = maintain(self.cfg)
        self.assertEqual(result["status"], "VALIDATE_AND_INDEX", result)
        self.assertEqual(result["change_set"]["counts_by_scope"], {"canonical": 1})
        self.assertTrue(result["change_set"]["semantic_audit_required"])

    def test_final_semantic_write_requires_restage_before_audit_and_snapshot(self):
        self._commit_initial_baseline()
        target = self.vault / "10-projects/demo/30-features/DEMO-FEAT-001-Access.md"

        # A first semantic edit is staged by maintain.
        target.write_text(target.read_text(encoding="utf-8") + "\n第一版语义更新。\n", encoding="utf-8", newline="\n")
        staged = maintain(self.cfg)
        self.assertEqual(staged["status"], "VALIDATE_AND_INDEX", staged)
        staged_id = staged["change_set"]["current_snapshot_id"]

        # Simulate an AI UPDATE after preflight. Projection/verify can bind the new truth,
        # but L4/baseline must not reuse the pre-AI staged change set.
        target.write_text(target.read_text(encoding="utf-8") + "AI 最终修订。\n", encoding="utf-8", newline="\n")
        build_projection(self.cfg)
        self.assertEqual(verify(self.cfg)["status"], "PASS")
        with self.assertRaisesRegex(ValueError, "change set is stale; run knowledge scan"):
            create_audit_plan(self.cfg)
        with self.assertRaisesRegex(ValueError, "truth changed after staged scan"):
            commit_snapshot(self.cfg)

        # The canonical final-binding sequence starts by re-staging current truth.
        restaged = stage_scan(self.cfg)
        self.assertNotEqual(restaged["current_snapshot_id"], staged_id)
        build_projection(self.cfg)
        self.assertEqual(verify(self.cfg)["status"], "PASS")
        plan = create_audit_plan(self.cfg)
        self.assertTrue(plan["required"])
        record_audit(self.cfg, result="PASS", summary="final truth reviewed", documents=plan["mandatory_documents"])
        committed = commit_snapshot(self.cfg)
        self.assertEqual(committed["snapshot_id"], restaged["current_snapshot_id"])

    def test_golden_eval_does_not_pollute_usage_telemetry(self):
        build_projection(self.cfg)
        write(self.vault/"00-system/eval/golden.jsonl", '\n'.join([
            json.dumps({"id":"G1","question":"园区门禁授权","category":"feature","expected_project":"Demo","answer_type":"has_answer"},ensure_ascii=False),
            json.dumps({"id":"G2","question":"不存在的火星量子香蕉","category":"no_answer","expected_project":"Demo","answer_type":"no_answer"},ensure_ascii=False),
        ])+'\n')
        result=evaluate(self.cfg,modes=["canonical_first_fts"])
        metrics=result["modes"]["canonical_first_fts"]["metrics"]
        self.assertEqual(metrics["Recall@20"],1.0)
        self.assertEqual(telemetry_summary(self.cfg)["queries"],0)
        self.assertEqual(result["vector_mode"],"retired-compatible")


class TestIngest(KnowledgeCase):
    def test_registered_source_accountability_and_duplicates(self):
        src=self.root/"external"; src.mkdir()
        write(src/"a.txt","same evidence")
        write(src/"b.txt","same evidence")
        status=register_batch(self.cfg,project="demo",batch="B1",source_root=src)
        self.assertEqual(status["registered"],2)
        self.assertEqual(status["dispositions"].get("duplicate"),1)
        self.assertEqual(status["pending"],1)
        rows=(self.vault/".ai-kb/ingest/B1/manifest.jsonl").read_text(encoding="utf-8").splitlines()
        parsed=[json.loads(x) for x in rows]
        pending=next(x for x in parsed if x["disposition"]=="pending")
        disposition(self.cfg,batch="B1",source_id=pending["source_id"],disposition_name="source_only",canonical_ids=[],reason="evidence only",origin_path=pending["origin_path"])
        final=finalize_batch(self.cfg,"B1")
        self.assertEqual(final["accountability"],1.0)
        self.assertTrue(final["finalized"])


if __name__ == "__main__":
    unittest.main()


class TestKnowledgeConvergenceAndNormalization(KnowledgeCase):
    def test_migration_plan_classifies_local_editor_and_personal_note_roots_out_of_scope(self):
        configured = [str(x) for x in (self.cfg.knowledge.get("maintenance") or {}).get("local_out_of_scope_roots") or []]
        for index, rel in enumerate(configured):
            write(self.vault / rel / f"local-{index}.txt", "local-only\n")
        plan = migration_plan(self.cfg)
        local = {x["path"] for x in plan["groups"]["KEEP_LOCAL_OUT_OF_SCOPE"]}
        self.assertEqual(set(configured), local)
        self.assertEqual(plan["unclassified_count"], 0, plan)

    def test_project_scoped_search_excludes_other_projects_and_can_explicitly_go_global(self):
        self.canonical(
            "10-projects/demo/30-features/DEMO-FEAT-001-Demo.md",
            cid="DEMO-FEAT-001", kind="feature", title="Demo",
            source_refs="[TASK-D]", body="sharedword demo project knowledge",
        )
        write(self.vault / "20-shared/SHARED-SYS-001-Shared.md", """---
id: SHARED-SYS-001
title: Shared
project: shared
kind: system
status: active
canonical: true
source_refs: [TASK-S]
confidence: 0.9
last_verified: '2026-08-11'
relations: []
---
# Shared
sharedword shared knowledge
""")
        write(self.vault / "10-projects/other/30-features/OTHER-FEAT-001-Other.md", """---
id: OTHER-FEAT-001
title: Other
project: other
kind: feature
status: active
canonical: true
source_refs: [TASK-O]
confidence: 0.9
last_verified: '2026-08-11'
relations: []
---
# Other
otheronly global knowledge
""")
        registry = yaml.safe_load((self.vault / "00-system/project-registry.yaml").read_text(encoding="utf-8"))
        registry["projects"].append({"id":"other","display_name":"Other","status":"active","workspace_roots":[]})
        write(self.vault / "00-system/project-registry.yaml", yaml.safe_dump(registry, allow_unicode=True, sort_keys=False))
        self.cfg = load_content_systems(self.workspace)
        build_projection(self.cfg)
        scoped = search(self.cfg, "otheronly", limit=10)
        self.assertEqual(scoped, [], scoped)
        shared = search(self.cfg, "sharedword", limit=10)
        projects = {h["project"] for h in shared}
        self.assertIn("demo", projects)
        self.assertIn("shared", projects)
        self.assertNotIn("other", projects)
        global_hits = search(self.cfg, "otheronly", limit=10, scope="global")
        self.assertTrue(global_hits)
        self.assertEqual(global_hits[0]["project"], "other")

    def test_deterministic_legacy_normalization_does_not_invent_semantics(self):
        write(self.vault / "10-projects/demo/30-features/DEMO-FEAT-071-Legacy.md", """---
id: DEMO-FEAT-071
title: Legacy
project: demo
kind: canonical
status: active
source_refs: [TASK-1]
confidence: high
last_verified: '2026-08-01'
aliases: [12345]
relations:
  relates_to: [DEMO-SYS-001]
  implemented_by: [DEMO-API-001]
---
# Legacy
Body stays intact.
""")
        write(self.vault / "10-projects/demo/70-operations/DEMO-OPS-005-Legacy.md", """---
id: DEMO-OPS-005
title: Legacy Ops
project: demo
kind: ops
status: active
canonical: true
source_refs: []
confidence: medium
last_verified: '2026-08-01'
relations: []
evidence_type: code
---
# Legacy Ops
No evidence may be fabricated.
""")
        plan = normalization_plan(self.cfg)
        self.assertEqual(plan["status"], "READY")
        self.assertGreaterEqual(plan["safe_documents"], 2)
        reasons = {r for item in plan["review_queue"] for r in item["reasons"]}
        self.assertTrue(any("implemented_by" in r for r in reasons))
        self.assertTrue(any("no usable source/evidence" in r for r in reasons))
        receipt = apply_normalization(self.cfg)
        self.assertEqual(receipt["status"], "APPLIED")
        text=(self.vault / "10-projects/demo/30-features/DEMO-FEAT-071-Legacy.md").read_text(encoding="utf-8")
        self.assertIn("kind: feature", text)
        self.assertIn("confidence: 0.9", text)
        self.assertRegex(text, r"aliases:\s*\n- ['\"]?12345['\"]?")
        self.assertIn("type: related_to", text)
        self.assertIn("type: implemented_by", text)
        self.assertIn("Body stays intact.", text)
        ops=(self.vault / "10-projects/demo/70-operations/DEMO-OPS-005-Legacy.md").read_text(encoding="utf-8")
        self.assertIn("kind: operation", ops)
        self.assertIn("source_refs: []", ops)
        self.assertNotIn("evidence_refs:", ops)
        meta=self.vault / ".ai-kb/meta"
        self.assertTrue((meta / "knowledge-normalization-receipt.json").is_file())
        self.assertTrue((meta / "knowledge-normalization-review.json").is_file())

    def test_part_of_feature_and_data_are_valid_containment_targets(self):
        self.canonical("10-projects/demo/30-features/DEMO-FEAT-001-Parent.md", cid="DEMO-FEAT-001", kind="feature", title="Parent", source_refs="[TASK-P]")
        self.canonical("10-projects/demo/30-features/DEMO-FEAT-002-Child.md", cid="DEMO-FEAT-002", kind="feature", title="Child", source_refs="[TASK-C]", relations="[{type: part_of, target: DEMO-FEAT-001}]")
        self.canonical("10-projects/demo/50-data/DEMO-DATA-001-Parent.md", cid="DEMO-DATA-001", kind="data", title="Data Parent", source_refs="[TASK-DP]")
        self.canonical("10-projects/demo/50-data/DEMO-DATA-002-Child.md", cid="DEMO-DATA-002", kind="data", title="Data Child", source_refs="[TASK-DC]", relations="[{type: part_of, target: DEMO-DATA-001}]")
        result=lint_knowledge(self.cfg)
        relevant=[r for r in result.get("records",[]) if r.get("rule_id")=="K008"]
        self.assertEqual(relevant, [], result)


class TestQualityPolicyGate(KnowledgeCase):
    def test_allowed_backlog_rules_do_not_block_verify_or_snapshot(self):
        # K011 broken vault-root wikilink + K018 related_to-without-note + K010 basename
        # wikilink + K015 unresolved legacy SRC ref must all be LEGACY/INFORMATIONAL backlog:
        # lint still reports them, but the verify gate must PASS and snapshot must commit.
        self.canonical("10-projects/demo/30-features/DEMO-FEAT-001-Base.md", cid="DEMO-FEAT-001", kind="feature", title="Base", source_refs="[TASK-1]")
        self.canonical(
            "10-projects/demo/30-features/DEMO-FEAT-002-Backlog.md", cid="DEMO-FEAT-002", kind="feature", title="Backlog",
            source_refs="[SRC-demo-missing]",
            relations="[{type: related_to, target: DEMO-FEAT-001}]",
            body="[[DEMO-NOPE-001]] [[10-projects/demo/50-data/DEMO-DATA-999-Broken]]",
        )
        lint = lint_knowledge(self.cfg)
        self.assertGreater(lint["errors"], 0, lint)
        self.assertIn("K011", {r["rule_id"] for r in lint["violations"]})
        self.assertIn("K018", {r["rule_id"] for r in lint["warning_records"]})
        self.assertTrue({"K010", "K015"} <= {r["rule_id"] for r in lint["advisory_records"]})
        build_projection(self.cfg)
        ok = verify(self.cfg)
        self.assertEqual(ok["status"], "PASS", ok)
        self.assertEqual(ok["gate"]["gate_errors"], 0)
        self.assertEqual(ok["gate"]["gate_warnings"], 0)
        self.assertGreaterEqual(ok["gate"]["backlog"]["K011"]["errors"], 1)
        self.assertGreaterEqual(ok["gate"]["backlog"]["K018"]["warnings"], 1)
        self.assertGreaterEqual(ok["gate"]["backlog"]["K010"]["advisories"], 1)
        self.assertGreaterEqual(ok["gate"]["backlog"]["K015"]["advisories"], 1)
        # Original lint counts are preserved in the receipt, not hidden by the gate.
        self.assertGreaterEqual(ok["lint"]["errors"], 1)
        plan = create_audit_plan(self.cfg, full=True)
        self.assertTrue(plan["required"])
        record_audit(self.cfg, result="PASS", summary="reviewed", documents=plan["mandatory_documents"])
        committed = commit_snapshot(self.cfg)
        self.assertTrue(committed["baseline_advanced"])

    def test_hard_blocker_still_fails_verify(self):
        self.canonical("10-projects/demo/30-features/DEMO-FEAT-001-Wizard.md", cid="DEMO-FEAT-001", kind="wizard", title="Wizard", source_refs="[TASK-1]")
        lint = lint_knowledge(self.cfg)
        self.assertIn("K005", {r["rule_id"] for r in lint["violations"]})
        result = verify(self.cfg)
        self.assertGreaterEqual(result["gate"]["gate_errors"], 1)
        self.assertEqual(result["status"], "FAIL", result)
