from __future__ import annotations

import tempfile
from pathlib import Path

from cli.project_surface import project_surface_plan, sync_project_surface

BASE = Path(__file__).resolve().parents[2]


def test_project_memory_bootstrap_is_create_once_and_project_owned():
    with tempfile.TemporaryDirectory() as td:
        workspace = Path(td) / "demo"
        workspace.mkdir()

        plan = project_surface_plan(workspace, project_id="demo")
        memory_rows = [r for r in plan["files"] if "/memory/" in str(r["path"]).replace("\\", "/")]
        assert len(memory_rows) == 2
        assert all(r["changed"] for r in memory_rows)

        result = sync_project_surface(workspace, project_id="demo", apply=True)
        assert result["status"] == "CURRENT"
        index = workspace / ".tp-spec" / "memory" / "INDEX.md"
        project = workspace / ".tp-spec" / "memory" / "PROJECT.md"
        skills = workspace / ".tp-spec" / "memory" / "skills"
        assert index.is_file() and project.is_file() and skills.is_dir()

        project.write_text("# project-owned\n", encoding="utf-8", newline="\n")
        index.write_text("# project-index\n", encoding="utf-8", newline="\n")
        sync_project_surface(workspace, project_id="demo", apply=True)
        assert project.read_text(encoding="utf-8") == "# project-owned\n"
        assert index.read_text(encoding="utf-8") == "# project-index\n"


def test_memory_templates_are_progressive_and_small():
    index = (BASE / "project-entry" / "memory-index.md").read_text(encoding="utf-8")
    project = (BASE / "project-entry" / "memory-project.md").read_text(encoding="utf-8")
    assert "默认只读本文件" in index
    assert "不要预加载" in index
    for heading in ("Runtime", "Structure", "Constraints", "Verification", "Navigation"):
        assert f"## {heading}" in project
    assert len(index.encode("utf-8")) < 4096
    assert len(project.encode("utf-8")) < 4096


def test_memory_capture_is_internal_thin_and_evidence_gated():
    text = (BASE / "skills" / "tp-memory-capture" / "SKILL.md").read_text(encoding="utf-8")
    assert "内部薄能力" in text
    assert "不对用户暴露" in text
    assert "No Evidence, No Memory" in text
    for gate in ("Evidence-backed", "Non-volatile", "Reusable", "Costly to rediscover"):
        assert gate in text
    assert "UPDATE existing > CREATE new" in text
    assert "patch > rewrite" in text
    assert "status: candidate" in text
    assert "不得阻塞研发" in text
    assert len(text.encode("utf-8")) < 5000


def test_all_seven_workflow_roles_can_opportunistically_discover_memory_capture():
    roles = (
        "tp-requirement-analysis",
        "tp-product-design",
        "tp-architecture-design",
        "tp-architecture-review",
        "tp-development-engineering",
        "tp-verification-engineering",
        "tp-delivery-convergence",
    )
    for role in roles:
        text = (BASE / "skills" / role / "SKILL.md").read_text(encoding="utf-8")
        assert "tp-memory-capture" in text, role
    delivery = (BASE / "skills" / "tp-delivery-convergence" / "SKILL.md").read_text(encoding="utf-8")
    assert "未触碰 Memory：0 动作" in delivery
    assert "只检查 touched fragment" in delivery
    assert "禁止扫描整个 PROJECT、全部 Skills 或历史任务" in delivery


def test_project_entry_makes_memory_opportunistic_not_critical_path():
    root = (BASE / "project-entry" / "root-managed-block.md").read_text(encoding="utf-8")
    runtime = (BASE / "project-entry" / "tp-spec-readme.md").read_text(encoding="utf-8")
    for text in (root, runtime):
        assert "tp-memory-capture" in text
        assert "不得" in text
    assert "tp-learn" not in root
    assert "tp-learn" not in runtime
