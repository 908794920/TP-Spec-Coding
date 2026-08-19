from pathlib import Path

from cli import task_cmd


def test_requirement_ready_intake_can_be_only_requirement_md(tmp_path):
    intake = tmp_path / "intake"; intake.mkdir()
    (intake / "requirement.md").write_text("目标：允许用户导出当前查询结果。\n验收：导出内容与当前过滤结果一致。\n", encoding="utf-8")
    scaffold = tmp_path / "task"; scaffold.mkdir()
    adopted = task_cmd._adopt_intake_artifacts(scaffold, intake, "TASK-1", "2026-08-18T00:00:00+00:00")
    assert adopted == ["requirement.md"]
    text = (scaffold / "requirement.md").read_text(encoding="utf-8")
    assert 'task_id: "TASK-1"' in text
    assert "intake_provenance:" in text
    assert "允许用户导出" in text


def test_legacy_requirement_knowledge_is_normalized_to_canonical_requirement(tmp_path):
    intake = tmp_path / "intake"; intake.mkdir()
    (intake / "requirement-knowledge.md").write_text("旧版已确认需求事实\n", encoding="utf-8")
    scaffold = tmp_path / "task"; scaffold.mkdir()
    adopted = task_cmd._adopt_intake_artifacts(scaffold, intake, "TASK-2", "2026-08-18T00:00:00+00:00")
    assert adopted == ["requirement.md"]
    assert not (scaffold / "requirement-knowledge.md").exists()
    assert "旧版已确认需求事实" in (scaffold / "requirement.md").read_text(encoding="utf-8")


def test_no_empty_clarification_or_decision_file_is_required(tmp_path):
    intake = tmp_path / "intake"; intake.mkdir()
    (intake / "requirement.md").write_text("Goal: fix a null pointer. Acceptance: regression test passes.", encoding="utf-8")
    scaffold = tmp_path / "task"; scaffold.mkdir()
    task_cmd._adopt_intake_artifacts(scaffold, intake, "TASK-3", "2026-08-18T00:00:00+00:00")
    assert not (scaffold / "requirement-clarifications.md").exists()
    assert not (scaffold / "requirement-decisions.md").exists()
