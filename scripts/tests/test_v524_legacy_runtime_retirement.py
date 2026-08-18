from pathlib import Path

from cli import config_loader, workflow_loader

BASE = Path(__file__).resolve().parents[2]


def test_active_config_loader_does_not_resolve_legacy_state_owner():
    assert config_loader.get_state_owner("RISK_ANALYZING") is None


def test_active_workflow_loader_does_not_merge_legacy_microstates():
    workflow_loader._WORKFLOW_CACHE.clear()
    wf = workflow_loader.load_workflow()
    assert set(wf.states) == {"NEW", "ACTIVE", "BLOCKED", "COMPLETED", "CANCELLED"}
    assert "RISK_ANALYZING" not in wf.transitions


def test_migration_namespace_retains_frozen_v523_maps():
    from cli.migrations.v5_2_3.legacy_workflow import LEGACY_STATE_OWNERS, LEGACY_TRANSITIONS
    from cli.migrations.v5_2_3.role_map import ROLE_MAP
    old_verify_actor = next(k for k, v in ROLE_MAP.items() if v == "tp-test-engineer")
    assert LEGACY_STATE_OWNERS["VERIFYING"] == old_verify_actor
    assert "DEVELOPING" in LEGACY_TRANSITIONS["VERIFYING"]


def test_active_loaders_do_not_import_legacy_workflow():
    for rel in ("cli/config_loader.py", "cli/workflow_loader.py"):
        text = Path(rel).read_text(encoding="utf-8")
        assert "from .legacy_workflow" not in text
        assert "LEGACY_STATE_OWNERS" not in text
        assert "LEGACY_TRANSITIONS" not in text


def test_current_review_and_validator_do_not_import_transition_service():
    for rel in ("cli/review_cmd.py", "cli/validator.py"):
        text = Path(rel).read_text(encoding="utf-8")
        assert "transition_service" not in text


def test_current_runtime_uses_neutral_transaction_commit_not_legacy_commit_module():
    transaction = BASE / "cli/transaction_commit.py"
    assert transaction.is_file()
    for rel in ["cli/record_first.py", "cli/reconcile_cmd.py", "cli/review_cmd.py", "cli/task_cmd.py"]:
        text = (BASE / rel).read_text(encoding="utf-8")
        assert "commit_cmd" not in text, rel
        assert "transaction_commit" in text, rel


def test_current_event_recovery_does_not_import_migration_transition_service():
    text = (BASE / "cli/event_cmd.py").read_text(encoding="utf-8")
    assert "migrations.v5_2_3.transition_service" not in text
    assert "transition_task(" not in text
