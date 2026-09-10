from __future__ import annotations

import pytest

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
    assert "目标未知" in index and "已知目标" in index
    assert "不要预加载" in index
    for heading in ("Runtime", "Structure", "Constraints", "Verification", "Navigation"):
        assert f"## {heading}" in project
    assert len(index.encode("utf-8")) < 4096
    assert len(project.encode("utf-8")) < 4096


def test_memory_capture_is_internal_thin_and_evidence_gated():
    text = (BASE / "skills" / "capabilities" / "tp-memory-capture" / "SKILL.md").read_text(encoding="utf-8")
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


def test_all_formal_workflow_roles_can_opportunistically_discover_memory_capture():
    roles = (
        "tp-product-manager", "tp-software-architect", "tp-tech-lead",
        "tp-security-engineer", "tp-development-engineer", "tp-database-engineer",
        "tp-test-engineer", "tp-code-reviewer", "tp-integration-engineer",
    )
    for role in roles:
        text = (BASE / "skills" / "roles" / role / "SKILL.md").read_text(encoding="utf-8")
        assert "tp-memory-capture" in text, role
        assert "未触碰 Memory：0 动作" in text, role
        # 细则移到单一维护位置后，必须同时验证触发入口和实际目标内容。
        from scripts.check_document_navigation import iter_markdown_links, resolve_document_link
        source = BASE / "skills/roles" / role / "SKILL.md"
        targets = [resolve_document_link(source, target, base=BASE)
                   for _, target in iter_markdown_links(source)]
        primary = BASE / "skills/capabilities/tp-memory-capture/SKILL.md"
        assert primary in targets, role
        details = primary.read_text(encoding="utf-8")
        assert "只读相关段及来源" in details
        assert "不预加载 PROJECT、全部 Skills 或 Task 历史" in details
        assert "无关 Memory 不读" in text, role


def test_project_entry_makes_memory_opportunistic_not_critical_path():
    root = (BASE / "project-entry" / "root-managed-block.md").read_text(encoding="utf-8")
    runtime = (BASE / "project-entry" / "tp-spec-readme.md").read_text(encoding="utf-8")
    for text in (root, runtime):
        assert "tp-memory-capture" in text
        assert "不得" in text
    assert "tp-learn" not in root
    assert "tp-learn" not in runtime


def test_stable_rules_target_project_root_owned_area_not_memory_or_base():
    text = (BASE / 'skills/capabilities/tp-memory-capture/SKILL.md').read_text(encoding='utf-8')
    assert '项目根目录 `AGENTS.md` 自有区' in text
    assert '用户全局' in text and 'TP-Spec 公共模板' in text
    assert '临时事实' in text and 'Task' in text
    assert '不整体搬迁 Memory' in text
    for name in ('root-managed-block.md', 'tp-spec-readme.md'):
        entry = (BASE / 'project-entry' / name).read_text(encoding='utf-8')
        assert 'AGENTS.md' in entry and '自有区' in entry


# These are supplied-instruction contracts, not claims about a real host/Agent.


@pytest.mark.parametrize('role', [
    'tp-product-manager', 'tp-software-architect', 'tp-tech-lead',
    'tp-security-engineer', 'tp-development-engineer', 'tp-database-engineer',
    'tp-test-engineer', 'tp-code-reviewer', 'tp-integration-engineer',
])
def test_b10_independent_role_keeps_rule_trigger_and_failure_boundary_visible(role):
    text = (BASE / 'skills/roles' / role / 'SKILL.md').read_text(encoding='utf-8')
    section = text.split('## Project Memory（按需）', 1)[1].split('\n## ', 1)[0]
    assert 'AGENTS.md' in section and '自有' in section
    assert 'Rule' in section and '重发现成本限制' in section
    assert '未持久化' in section
    assert 'Task' in section and 'tp-memory-capture' in section
    assert '只有工作自然出现 Evidence-backed' not in section


@pytest.mark.parametrize('name', ['root-managed-block.md', 'tp-spec-readme.md'])
def test_b10_project_entry_allows_known_target_direct_access_and_no_optional_read(name):
    text = (BASE / 'project-entry' / name).read_text(encoding='utf-8')
    assert '已知目标' in text and '直达' in text
    assert '目标未知' in text and 'INDEX.md' in text
    assert '无关' in text and '不读' in text
    assert '进入项目先读' not in text
    assert 'Rule' in text and '重发现成本' in text
    assert '未持久化' in text


def test_b10_capture_instructions_require_verified_destination_before_source_dedup():
    text = (BASE / 'skills/capabilities/tp-memory-capture/SKILL.md').read_text(encoding='utf-8')
    assert '读回' in text and '确认目标已正确保存后' in text
    assert '保留原规则' in text and '未持久化' in text
    assert '不适用' in text and '候选' in text and '不自动升级' in text
    assert '双向同步' in text and 'PROJECT.md' in text
    assert 'SKIP' in text and '当前会话' in text
    assert '缺失、损坏、冲突或写入失败都必须 SKIP' not in text


def test_b10_capture_keeps_procedure_scale_and_sensitive_data_out_of_rules():
    text = (BASE / 'skills/capabilities/tp-memory-capture/SKILL.md').read_text(encoding='utf-8')
    assert '历史验收规模' in text and '不构成' in text and '授权' in text
    assert '持久回归' in text and '临时' in text
    assert 'Cookie' in text and 'AGENTS' in text and 'Skill' in text
    assert '不得自动删除' in text and '.agents/skills' in text


def test_b10_memory_bootstrap_distinguishes_rule_task_fact_procedure():
    index = (BASE / 'project-entry/memory-index.md').read_text(encoding='utf-8')
    project = (BASE / 'project-entry/memory-project.md').read_text(encoding='utf-8')
    for text in (index, project):
        assert 'AGENTS.md' in text and 'Task' in text
    assert '已知目标' in index and '目标未知' in index
    assert '默认只读本文件' not in index
    assert '候选' in project and '不自动' in project


def test_b10_sync_does_not_read_optional_memory_or_promote_candidate_content(tmp_path, monkeypatch):
    workspace = tmp_path / 'business'; workspace.mkdir()
    root = workspace / 'AGENTS.md'
    root.write_bytes(b'# Project-specific invariant\r\nOnly legacy jobs use the switch.\r\n')
    protected = {}
    for rel, data in {
        '.tp-spec/memory/INDEX.md': b'\xff invalid optional cache',
        '.tp-spec/memory/PROJECT.md': b'# Unverified JDK clue\nDo not promote to rule.\n',
        '.tp-spec/memory/skills/photo/SKILL.md': b'---\nstatus: candidate\n---\nHistorical large sample, no current authorization.\n',
        '.tp-spec/tasks/TASK-LOCAL/task.md': b'# Temporary baseline and waiting\n',
        'tests/browser/kept.spec.ts': b'// approved durable regression\n',
        'module/AGENTS.md': b'# Existing module rules\n',
    }.items():
        p = workspace / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
        protected[p] = (data, p.stat().st_mtime_ns)
    original = Path.read_bytes
    original_text = Path.read_text
    def deny_optional_bytes(self):
        if self in protected:
            raise AssertionError(f'Unrequested project-owned body read: {self}')
        return original(self)
    def deny_optional_text(self, *args, **kwargs):
        if self in protected:
            raise AssertionError(f'Unrequested project-owned body read: {self}')
        return original_text(self, *args, **kwargs)
    with monkeypatch.context() as context:
        context.setattr(Path, 'read_bytes', deny_optional_bytes)
        context.setattr(Path, 'read_text', deny_optional_text)
        result = sync_project_surface(workspace, project_id='business', apply=True)
    assert result['status'] == 'CURRENT', result
    for p, before in protected.items():
        assert (p.read_bytes(), p.stat().st_mtime_ns) == before
    after = root.read_bytes()
    assert after.startswith(b'# Project-specific invariant\r\nOnly legacy jobs use the switch.\r\n')
    assert b'Unverified JDK' not in after and b'Historical large sample' not in after
    stamps = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in workspace.rglob('*') if p.is_file()}
    assert sync_project_surface(workspace, project_id='business', apply=True)['changes'] == []
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in stamps} == stamps
    other = tmp_path / 'other'; other.mkdir()
    assert sync_project_surface(other, project_id='other', apply=True)['status'] == 'CURRENT'
    assert b'Only legacy jobs' not in (other / 'AGENTS.md').read_bytes()
    assert not (workspace / '.agents').exists()


def test_b10_failed_root_update_keeps_original_memory_source(tmp_path, monkeypatch):
    from cli import project_surface as surface
    root = tmp_path / 'AGENTS.md'; root.write_bytes(b'# Existing rules\r\n')
    source = tmp_path / '.tp-spec/memory/PROJECT.md'
    source.parent.mkdir(parents=True); source.write_bytes(b'# Only copy of rule and independent procedure\n')
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (root, source)}
    replace = surface.os.replace
    def fail_rule_write(src, dst):
        if Path(dst) == root:
            raise PermissionError('injected rule destination failure')
        return replace(src, dst)
    monkeypatch.setattr(surface.os, 'replace', fail_rule_write)
    result = surface.sync_project_surface(tmp_path, project_id='business', apply=True)
    assert result['status'] == 'BLOCKED' and result['changes'] == []
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before} == before
    assert not list(tmp_path.glob('.tp-spec-surface-*'))


@pytest.mark.parametrize('role', [
    'tp-product-manager', 'tp-software-architect', 'tp-tech-lead',
    'tp-security-engineer', 'tp-development-engineer', 'tp-database-engineer',
    'tp-test-engineer', 'tp-code-reviewer', 'tp-integration-engineer',
])
def test_b14_independent_role_links_to_single_memory_rule_source(role):
    import re
    from cli import orchestration
    path = BASE / 'skills/roles' / role / 'SKILL.md'
    section = path.read_text(encoding='utf-8').split('## Project Memory（按需）', 1)[1].split('\n## ', 1)[0]
    link = re.search(r'\[tp-memory-capture\]\(([^)]+)\)', section)
    assert link, 'Independent/emergency role needs an actionable source, not only an ID'
    target = (path.parent / link.group(1)).resolve()
    assert target == BASE / 'skills/capabilities/tp-memory-capture/SKILL.md'
    source = target.read_text(encoding='utf-8')
    assert '确认目标已正确保存后' in source and 'Costly to rediscover' in source
    assert '沉淀' in section and '先读' in section
    # 目录仍将其声明为条件能力；这不代表宿主实际加载过正文。
    topology = orchestration.load_role_topology(BASE)
    assert any(e['from'] == role and e['to'] == 'tp-memory-capture'
               and e.get('mode') == 'conditional' for e in topology['edges'])
