from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[2]
TESTS_ROOT = BASE / "scripts" / "tests"
CATALOG_PATH = TESTS_ROOT / "test_catalog.py"
PYTEST_INI = BASE / "pytest.ini"
DOC_PATH = BASE / "docs" / "TESTING.md"


def _load_catalog_module():
    assert CATALOG_PATH.is_file(), "test catalog must exist"
    spec = importlib.util.spec_from_file_location("tp_spec_test_catalog", CATALOG_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _behavior_test_files() -> set[str]:
    files = set()
    for path in TESTS_ROOT.rglob("test_*.py"):
        rel = path.relative_to(BASE).as_posix()
        if rel == "scripts/tests/test_catalog.py":
            continue
        files.add(rel)
    return files


def _nodeid_target_exists(nodeid: str) -> bool:
    path_text, *parts = nodeid.split("::")
    if not parts:
        return False
    path = BASE / path_text
    if not path.is_file():
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"))
    if len(parts) == 1:
        return any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == parts[0]
            for node in tree.body
        )
    if len(parts) == 2:
        class_name, method_name = parts
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                return any(
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name
                    for child in node.body
                )
    return False


def test_pytest_governance_files_exist():
    assert PYTEST_INI.is_file()
    assert CATALOG_PATH.is_file()
    assert (TESTS_ROOT / "conftest.py").is_file()
    assert DOC_PATH.is_file()


def test_catalog_covers_every_behavior_test_file_without_stale_paths():
    catalog = _load_catalog_module()
    assert set(catalog.TEST_FILE_CATALOG) == _behavior_test_files()


def test_catalog_entries_have_one_primary_layer_domain_and_audit_metadata():
    catalog = _load_catalog_module()
    for path, meta in catalog.TEST_FILE_CATALOG.items():
        assert meta["layer"] in catalog.PRIMARY_LAYERS, path
        assert tuple(meta["domains"]), path
        assert set(meta["domains"]) <= catalog.DOMAIN_MARKERS, path
        assert meta["necessity"] in catalog.NECESSITY_CLASSES, path
        assert meta["parallel_candidate"] in {"YES", "REVIEW", "NO"}, path
        resources = meta["resources"]
        assert set(resources) == {
            "subprocess",
            "sqlite",
            "git",
            "network",
            "port",
            "shared_temp",
            "env_mutation",
            "cwd_mutation",
        }, path
        assert all(isinstance(value, bool) for value in resources.values()), path
        assert isinstance(meta["main_contracts"], str) and meta["main_contracts"].strip(), path


def test_smoke_nodeids_are_real_and_small():
    catalog = _load_catalog_module()
    assert 1 <= len(catalog.SMOKE_NODEIDS) <= 8
    assert all(_nodeid_target_exists(nodeid) for nodeid in catalog.SMOKE_NODEIDS)


def test_unknown_test_file_is_fail_closed_by_catalog_lookup():
    catalog = _load_catalog_module()
    with pytest.raises(KeyError, match="unregistered test file"):
        catalog.metadata_for_path("scripts/tests/test_future_unregistered.py")


def test_marker_sets_are_fixed_and_non_overlapping():
    catalog = _load_catalog_module()
    assert catalog.PRIMARY_LAYERS == {"unit", "contract", "integration"}
    assert catalog.ORTHOGONAL_MARKERS == {"smoke", "slow", "serial"}
    assert catalog.DOMAIN_MARKERS == {
        "base",
        "runtime",
        "workflow",
        "cards",
        "knowledge",
        "wiki",
        "autonomy",
        "roles",
        "migration",
        "release",
        "portability",
    }
    assert not (catalog.PRIMARY_LAYERS & catalog.DOMAIN_MARKERS)
    assert not (catalog.PRIMARY_LAYERS & catalog.ORTHOGONAL_MARKERS)


def test_deleted_regressions_have_explicit_live_coverage_mapping():
    catalog = _load_catalog_module()
    expected_deleted = {
        "scripts/tests/test_v524_role_reference_inventory.py::test_removed_role_inventory_is_not_shipped",
        "scripts/tests/test_v510_agent_contracts.py::TestAgentContracts::test_all_skills_version_511",
        "scripts/tests/test_v510_agent_contracts.py::TestAgentContracts::test_no_legacy_template_path_in_skills",
        "scripts/tests/test_v510_agent_contracts.py::TestAgentContracts::test_role_catalog_hashes_match",
        "scripts/tests/test_v510_agent_contracts.py::TestAgentContracts::test_role_catalog_version_511",
        "scripts/tests/test_v510_version_purity.py::TestVersionPurity::test_no_legacy_dirs",
        "scripts/tests/test_v511_agent_contracts.py::TestRoleCatalog::test_catalog_has_expected_roles_and_hashes",
        "scripts/tests/test_v511_agent_contracts.py::TestAgentSkills::test_agent_versions",
        "scripts/tests/test_v511_agent_contracts.py::TestAgentSkills::test_requirement_analysis_is_pretask_and_low_bookkeeping",
        "scripts/tests/test_v511_agent_contracts.py::TestAgentSkills::test_architecture_review_is_risk_triggered_not_default_gate",
        "scripts/tests/test_v511_agent_contracts.py::TestAgentSkills::test_roles_do_business_not_projection_bookkeeping",
        "scripts/tests/test_v511_agent_contracts.py::TestCostTiering::test_l0_l3_are_risk_labels_not_fixed_expensive_flows",
        "scripts/tests/test_v513_record_first.py::TestRecordFirstStaticContracts::test_optional_templates_have_no_stage_handoff",
        "scripts/tests/test_v513_skill_semantics.py::TestRoleCatalogMetadata::test_catalog_metadata_matches_skill_frontmatter",
        "scripts/tests/test_v520_open_source_release.py::test_version_purity_scanner_rejects_previous_minor_after_v520_cutover",
        "scripts/tests/test_v524_delivery_knowledge_handoff.py::test_legacy_task_scoped_knowledge_handoff_is_rejected",
        "scripts/tests/test_v524_release_docs.py::test_readme_exposes_current_entry_and_document_map",
        "scripts/tests/test_v524_release_docs.py::test_getting_started_links_back_to_ai_install_entry_and_current_model",
        "scripts/tests/test_v524_release_docs.py::test_agents_and_skills_is_current_model_not_migration_history",
        "scripts/tests/test_v524_release_docs.py::test_changelog_keeps_release_history_not_process_plan",
        "scripts/tests/test_v524_role_catalog.py::test_subskill_paths_are_real",
        "scripts/tests/test_v527_document_navigation.py::test_document_navigation_checker_exists",
        "scripts/tests/test_v527_document_navigation.py::test_current_document_entrypoints_exist",
        "scripts/tests/test_v527_document_navigation.py::test_generated_agent_topology_blocks_match_catalog",
        "scripts/tests/test_v527_document_navigation.py::test_process_document_release_surface_is_removed",
        "scripts/tests/test_v522_workflow_delivery_hardening.py::V522WorkflowDeliveryCase::test_ready_delivery_without_knowledge_signal_needs_no_knowledge_effect",
        "scripts/tests/test_v522_workflow_delivery_hardening.py::V522WorkflowDeliveryCase::test_new_verification_invalidates_old_delivery_result",
        "scripts/tests/test_v522_workflow_delivery_hardening.py::V522WorkflowDeliveryCase::test_required_knowledge_convergence_blocks_completion_until_result",
    }
    mapping = {row["old_nodeid"]: row for row in catalog.COVERAGE_MAPPINGS}
    assert expected_deleted <= set(mapping)
    for old in expected_deleted:
        replacement = mapping[old]["replacement_nodeid"]
        assert mapping[old]["decision"].startswith("DELETE_"), old
        assert not _nodeid_target_exists(old), old
        assert _nodeid_target_exists(replacement), (old, replacement)


def test_testing_doc_records_original_and_current_baselines():
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "原始 v5.3.0 基线" in text
    assert "87 个测试文件 / 964 个 pytest 用例" in text
    assert "Task 1～3 后" in text
    assert "88 个测试文件 / 978 个 pytest 用例" in text
    assert "89 个行为测试文件 / 991 个 pytest 用例" in text
    assert "Task 8～9 后" in text
    assert "995 个 pytest 用例" in text
    assert "历史回归契约收敛后" in text
    assert "86 个行为测试文件 / 971 个 pytest 用例" in text
    assert "累计删除 25 个冗余 case" in text
    assert "Top 慢测试调用链收敛后" in text
    assert "86 个行为测试文件 / 968 个 pytest 用例" in text
    assert "累计删除 28 个冗余 case" in text
    assert "Knowledge 30.44s → 9.05s" in text
    assert "不以测试数量作为 KPI" in text


def _top_level_function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_v514_make_db_respects_caller_scoped_user_root(tmp_path, monkeypatch):
    from scripts.tests.v514_orchestration_testutil import make_db
    import os

    expected = tmp_path / "scoped-user-root"
    monkeypatch.setenv("TP_SPEC_USER_ROOT", str(expected))
    make_db(tmp_path / "project" / ".tp-spec" / "db" / "test.db")

    assert os.environ["TP_SPEC_USER_ROOT"] == str(expected)


def test_identical_runtime_run_helpers_are_centralized():
    paths = {
        "test_v512_maintenance.py",
        "test_v513_record_first.py",
        "test_v522_workflow_delivery_hardening.py",
        "test_v523_runtime_hardening.py",
        "test_v526_temp_artifacts.py",
        "test_v529_delivery_rework.py",
        "test_v529_knowledge_convergence.py",
    }
    for name in paths:
        path = TESTS_ROOT / name
        assert "run" not in _top_level_function_names(path), name
        assert "runtime_testutil import run" in path.read_text(encoding="utf-8"), name
    helper = (TESTS_ROOT / "runtime_testutil.py").read_text(encoding="utf-8")
    assert "cli_testutil import invoke_main" in helper
    assert "refresh_card: bool = False" in helper

    migrated_direct_main = {
        "test_v512_integrated_upgrade.py",
        "test_v514_orchestration_integration.py",
        "test_v522_context_effectiveness.py",
        "test_v522_context_usage.py",
        "test_v523_autonomy_phase0_contract.py",
    }
    for name in migrated_direct_main:
        text = (TESTS_ROOT / name).read_text(encoding="utf-8")
        assert "climain.main(" not in text, name

    card_text = (TESTS_ROOT / "test_v526_html_cards.py").read_text(encoding="utf-8")
    assert "invoke_main(argv, refresh_card=True)" in card_text


def test_autonomy_shared_run_and_git_helpers_are_centralized():
    run_files = {
        "test_v523_autonomy_batch.py",
        "test_v523_autonomy_cycle_fencing.py",
        "test_v523_autonomy_discovery.py",
        "test_v523_autonomy_envelope.py",
        "test_v523_autonomy_integration.py",
        "test_v523_autonomy_profile.py",
        "test_v523_autonomy_review.py",
        "test_v523_autonomy_workspace.py",
    }
    canonical_git_files = {
        "test_v523_autonomy_batch.py",
        "test_v523_autonomy_discovery.py",
        "test_v523_autonomy_integration.py",
        "test_v523_autonomy_review.py",
    }
    for name in run_files:
        path = TESTS_ROOT / name
        assert "run" not in _top_level_function_names(path), name
        assert "autonomy_testutil import" in path.read_text(encoding="utf-8"), name
    for name in canonical_git_files:
        assert "git_repo" not in _top_level_function_names(TESTS_ROOT / name), name
    helper = (TESTS_ROOT / "autonomy_testutil.py").read_text(encoding="utf-8")
    assert "cli_testutil import invoke_main" in helper
    assert "refresh_card: bool = False" in helper


def test_default_tp_spec_user_root_is_function_scoped(tmp_path):
    import os

    assert os.environ.get("TP_SPEC_USER_ROOT") == str(tmp_path / "tp-spec-user-root")


def test_task6_parallel_audit_resolves_review_candidates_without_serial_guessing():
    catalog = _load_catalog_module()
    assert all(meta["parallel_candidate"] == "YES" for meta in catalog.TEST_FILE_CATALOG.values())
    assert not any(meta["serial"] for meta in catalog.TEST_FILE_CATALOG.values())


def test_task7_slow_markers_follow_measured_high_cost_integration_files():
    catalog = _load_catalog_module()
    expected = {
        "scripts/tests/test_v523_autonomy_integration.py",
        "scripts/tests/test_v529_delivery_rework.py",
        "scripts/tests/test_v529_knowledge_convergence.py",
        "scripts/tests/test_v529_visual_verification.py",
    }
    assert {path for path, meta in catalog.TEST_FILE_CATALOG.items() if meta["slow"]} == expected



def test_task8_xdist_remains_unadopted_without_cross_platform_pilot():
    dev = (BASE / "requirements-dev.txt").read_text(encoding="utf-8")
    testing = DOC_PATH.read_text(encoding="utf-8")
    assert "pytest-xdist" not in dev
    assert "Task 8 决策：不引入 pytest-xdist" in testing
    assert "Linux 与 Windows pilot" in testing
    assert "requirements-dev.txt 保持不变" in testing


def test_ci_separates_pr_feedback_from_push_release_full_regression():
    workflow = (BASE / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "python-fast:" in workflow
    assert "python-integration:" in workflow
    assert "python-release:" in workflow
    assert 'smoke or ((unit or contract) and not slow)' in workflow
    assert 'integration and not slow and not serial' in workflow
    assert 'python -m pytest -q --durations=50' in workflow
    assert "github.event_name == 'push'" in workflow
    assert "windows-pr:" in workflow
    assert "github.event_name == 'pull_request'" in workflow
    assert "Test-TpSpecBase.ps1 -Mode Static" in workflow
    assert "windows-full:" in workflow
    assert "Test-TpSpecBase.ps1 -Mode Full" in workflow


def test_windows_full_does_not_duplicate_config_loader_and_keeps_role_catalog_shell_gate():
    gate = (BASE / "scripts" / "ci" / "Test-TpSpecBase.ps1").read_text(encoding="utf-8-sig")
    static_guard = "if ($Mode -eq 'Static') {\n    Invoke-Check 'static.unit.config_loader'"
    assert static_guard in gate
    assert "full.python.pytest" in gate
    assert "scripts\\tests\\Test-RoleCatalog.ps1" in gate
    assert "suite.role_catalog" in gate


def test_contributing_documents_fast_domain_and_release_gate_boundaries():
    text = (BASE / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert 'smoke or ((unit or contract) and not slow)' in text
    assert 'integration and not slow and not serial' in text
    assert "受影响领域通过" in text
    assert "不能宣称发布回归通过" in text
    assert "--durations=50" in text
    assert "Test-TpSpecBase.ps1 -Mode Full" in text
