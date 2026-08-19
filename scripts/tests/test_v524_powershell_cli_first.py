from pathlib import Path

BASE = Path(__file__).resolve().parents[2]


def test_task_validator_is_thin_cli_first_wrapper_without_role_logic():
    text = (BASE / "scripts/Test-TpSpecTask.ps1").read_text(encoding="utf-8-sig")
    assert "task validate" in text
    assert "python" in text.lower()
    assert "LEGACY_STATE_OWNERS" not in text
    assert "tp-software-lifecycle" not in text  # wrapper should not own routing policy
    assert len(text.splitlines()) < 180


def test_legacy_file_mode_handoff_scripts_are_not_active_scripts():
    assert not (BASE / "scripts/Invoke-TpSpecHandoff.ps1").exists()
    assert not (BASE / "scripts/Invoke-TpSpecHandoffFlush.ps1").exists()
    assert (BASE / "scripts/migration/v5_2_3/Invoke-TpSpecHandoff.ps1").is_file()
    assert (BASE / "scripts/migration/v5_2_3/Invoke-TpSpecHandoffFlush.ps1").is_file()


def test_base_ci_no_longer_runs_v510_file_mode_compatibility_suites():
    text = (BASE / "scripts/ci/Test-TpSpecBase.ps1").read_text(encoding="utf-8-sig")
    assert "Test-V510FileMode.ps1" not in text
    assert "Test-V510DbGuard.ps1" not in text
