from __future__ import annotations

import pytest

from cli.project_surface import MANAGED_START, MANAGED_END, sync_project_surface
from scripts.tests.v532_testutil import make_runtime, run_cli
from scripts.tests.test_v529_migration_release import B09_SOURCE


def test_base_sync_preserves_owned_bytes_bom_crlf_and_trailing_whitespace(tmp_path, monkeypatch):
    project, _, _, _ = make_runtime(tmp_path, monkeypatch)
    path = project / 'AGENTS.md'
    left = '\ufeff# 项目自己的规则\r\n\r\n保留空格  \r\n\r\n'.encode('utf-8')
    right = '\r\n\r\n## 自有区\r\n- 已确认业务限制  \r\n\r\n\r\n'.encode('utf-8')
    before = left + (MANAGED_START + '\r\nobsolete template\r\n' + MANAGED_END).encode() + right
    path.write_bytes(before)
    rc, out, err = run_cli(['base', 'sync-project', '--workspace-root', str(project), '--apply'])
    assert rc == 0, (out, err)
    after = path.read_bytes()
    assert after.split(MANAGED_START.encode())[0] == left
    assert after.split(MANAGED_END.encode())[1] == right
    assert b'obsolete template' not in after
    sync_project_surface(project, apply=True)
    assert path.read_bytes() == after


def test_append_managed_block_does_not_rewrite_existing_owned_content(tmp_path):
    path = tmp_path / 'AGENTS.md'
    owned = b'\xef\xbb\xbf# Own rules\r\n\r\nTrailing whitespace  \r\n\r\n'
    path.write_bytes(owned)
    result = sync_project_surface(tmp_path, project_id='fixture', apply=True)
    assert result['status'] == 'CURRENT'
    assert path.read_bytes().startswith(owned)


def test_reversed_markers_block_sync_without_rewriting_other_files(tmp_path):
    path = tmp_path / 'AGENTS.md'
    before = (MANAGED_END + '\nowned text\n' + MANAGED_START).encode()
    path.write_bytes(before)
    result = sync_project_surface(tmp_path, project_id='fixture', apply=True)
    assert result['status'] == 'BLOCKED'
    assert path.read_bytes() == before
    assert not (tmp_path / 'README.md').exists()


def test_owned_agent_symlink_is_not_followed_for_writes(tmp_path):
    import pytest
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    outside = tmp_path / 'outside.md'
    outside.write_text('# Another project', encoding='utf-8')
    try:
        (workspace / 'AGENTS.md').symlink_to(outside)
    except OSError:
        pytest.skip('Symlink creation unavailable')
    result = sync_project_surface(workspace, project_id='fixture', apply=True)
    assert result['status'] == 'BLOCKED'
    assert outside.read_text(encoding='utf-8') == '# Another project'


# B09: optional configuration is project-owned, including empty/false overrides.
def test_b09_portability_preserves_explicit_empty_and_default_overrides(tmp_path):
    import yaml
    from cli.content_systems import load_content_systems
    from cli.project_portability import normalize_project_portability
    p = tmp_path / '.tp-spec/config/content-systems.yaml'
    p.parent.mkdir(parents=True)
    raw = ('schema: tp-spec.content-systems/v1\nsystems:\n  wiki:\n'
           '    enabled: true\n    coverage:\n      no_doc_globs: []\n'
           '  knowledge:\n    retrieval:\n      include_shared: false\n').encode()
    p.write_bytes(raw)
    before = p.stat().st_mtime_ns
    result = normalize_project_portability(tmp_path, apply=True)
    assert result['status'] == 'CURRENT', result
    assert p.read_bytes() == raw and p.stat().st_mtime_ns == before
    cfg = load_content_systems(tmp_path)
    assert cfg.data['systems']['wiki']['coverage']['no_doc_globs'] == []


def test_b09_config_change_between_plan_and_apply_is_not_overwritten(tmp_path, monkeypatch):
    import yaml
    from pathlib import Path
    from cli import project_portability as pp
    base = Path(__file__).resolve().parents[2]
    install = tmp_path / 'installation.yaml'
    wiki = tmp_path / 'wiki'; wiki.mkdir()
    knowledge = tmp_path / 'knowledge'; knowledge.mkdir()
    install.write_text(yaml.safe_dump({'schema':'tp-spec.installation/v1', 'base':{'root':str(base)},
                                    'systems':{'wiki':{'root':str(wiki)},'knowledge':{'root':str(knowledge)}}}))
    p = tmp_path / '.tp-spec/config/content-systems.yaml'; p.parent.mkdir(parents=True)
    p.write_text(yaml.safe_dump({'schema':'tp-spec.content-systems/v1','systems':{'wiki':{'root':str(wiki)}}}))
    original = pp.project_portability_plan
    changed = b'schema: tp-spec.content-systems/v1\nsystems:\n  wiki:\n    enabled: false\n'
    def edit_after_plan(*args, **kwargs):
        plan = original(*args, **kwargs)
        p.write_bytes(changed)
        return plan
    monkeypatch.setattr(pp,'project_portability_plan',edit_after_plan)
    result = pp.normalize_project_portability(tmp_path,installation_config=install,apply=True)
    assert result['status'] == 'BLOCKED' and 'CHANGED' in str(result)
    assert p.read_bytes() == changed


def test_b09_surface_skills_link_cannot_create_directories_outside_workspace(tmp_path):
    import pytest
    workspace = tmp_path / 'workspace'; workspace.mkdir()
    external = tmp_path / 'external'; external.mkdir()
    sync_project_surface(workspace, project_id='fixture', apply=True)
    skills = workspace / '.tp-spec/memory/skills'
    skills.rmdir()
    try:
        skills.symlink_to(external / 'must-not-create', target_is_directory=True)
    except OSError:
        pytest.skip('symlink creation unavailable')
    result = sync_project_surface(workspace, project_id='fixture', apply=True)
    assert result['status'] == 'BLOCKED'
    assert not (external / 'must-not-create').exists()


def test_b09_binding_update_preserves_overrides_and_noop_bytes(tmp_path):
    import yaml
    from cli.environment import write_project_binding
    from cli.version import active_version
    path = tmp_path / '.tp-spec/config/project-binding.yaml'; path.parent.mkdir(parents=True)
    raw = ('# owned comment\r\nschema: tp-spec.project-binding/v1\r\nproject:\r\n'
           '  id: fixture\r\n  wiki_id: knowledge-id\r\nbase:\r\n  root: ${MY_APPROVED_BASE}\r\n'
           'base_version: ' + active_version() + '\r\n').encode()
    path.write_bytes(raw)
    before = path.stat().st_mtime_ns
    write_project_binding(tmp_path, project_id='fixture', base_version=active_version())
    assert path.read_bytes() == raw and path.stat().st_mtime_ns == before
    path.write_bytes(raw.replace(active_version().encode(), B09_SOURCE.encode()))
    write_project_binding(tmp_path, project_id='fixture', base_version=active_version())
    data = yaml.safe_load(path.read_bytes())
    assert data['base'] == {'root':'${MY_APPROVED_BASE}'}
    assert data['project']['wiki_id'] == 'knowledge-id'


def test_b09_resolver_reports_executing_version_and_source_without_migrating(tmp_path, monkeypatch):
    import json
    from cli.version import active_version
    from scripts.tests.test_v529_migration_release import _b09_legacy_case, _b09_rows
    project, db, tdir, tid = _b09_legacy_case(tmp_path, monkeypatch)
    monkeypatch.setenv('TP_SPEC_BASE_ROOT', str(__import__('pathlib').Path(__file__).resolve().parents[2]))
    before = _b09_rows(db)
    rc, out, err = run_cli(['base','resolve','--workspace-root',str(project)])
    assert rc == 0, (out, err)
    report = json.loads(out)
    assert report['base']['source'] == 'environment:TP_SPEC_BASE_ROOT'
    assert report['executing_base']['version'] == active_version()
    assert report['runtime_contract']['source_contract'] == B09_SOURCE
    assert report['runtime_contract']['runtime_compatible'] is False
    assert _b09_rows(db) == before


def test_b09_safe_surface_sync_does_not_claim_legacy_task_is_compatible(tmp_path, monkeypatch):
    import json
    from scripts.tests.test_v529_migration_release import _b09_legacy_case, _b09_rows
    project, db, tdir, tid = _b09_legacy_case(tmp_path, monkeypatch)
    before = _b09_rows(db)
    for rel in ('.tp-spec/memory/PROJECT.md', '.tp-spec/memory/skills/owned/SKILL.md',
                'tests/browser/approved-baseline.png', '.tp-spec/config/owned.yaml'):
        path = project / rel; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'project-owned stable asset\r\n')
    protected = {rel: ((project/rel).read_bytes(), (project/rel).stat().st_mtime_ns)
                 for rel in ('.tp-spec/memory/PROJECT.md','.tp-spec/memory/skills/owned/SKILL.md',
                             'tests/browser/approved-baseline.png','.tp-spec/config/owned.yaml')}
    args = ['base','sync-project','--workspace-root',str(project),'--apply']
    rc, out, err = run_cli(args)
    assert rc == 0, (out, err)
    result = json.loads(out)
    assert result['status'] == 'SYNC_REQUIRED'
    assert result['results'][0]['runtime_contract']['runtime_compatible'] is False
    assert _b09_rows(db) == before
    files = {str(p.relative_to(project)): (p.read_bytes(), p.stat().st_mtime_ns)
             for p in (project / '.tp-spec').rglob('*') if p.is_file() and not p.name.endswith(('-wal','-shm'))}
    assert run_cli(args)[0] == 0
    assert {str(p.relative_to(project)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in (project / '.tp-spec').rglob('*') if p.is_file() and not p.name.endswith(('-wal','-shm'))} == files
    assert {rel: ((project/rel).read_bytes(),(project/rel).stat().st_mtime_ns) for rel in protected} == protected


# B10: root rules have one exact filename; sync must not select or rename aliases.


@pytest.mark.parametrize('alias', ['Agents.md', 'agents.md'])
@pytest.mark.parametrize('canonical_exists', [False, True])
def test_b10_root_rule_filename_ambiguity_blocks_without_writes(tmp_path, alias, canonical_exists):
    wrong = tmp_path / alias
    wrong.write_bytes(b'# Existing project rules\r\nDo not publish.\r\n')
    canonical = tmp_path / 'AGENTS.md'
    if canonical_exists:
        if canonical.exists():
            pytest.skip('Filesystem cannot hold both case variants')
        canonical.write_bytes(b'# Another existing rule source\n')
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    result = sync_project_surface(tmp_path, project_id='fixture', apply=True)
    assert result['status'] == 'BLOCKED', result
    assert 'AGENTS.md' in str(result['blockers']) and alias in str(result['blockers'])
    assert result['changes'] == []
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()} == before


def test_b10_alias_created_after_plan_is_not_silently_bypassed(tmp_path, monkeypatch):
    from cli import project_surface as surface
    original = surface.project_surface_plan
    wrong = tmp_path / 'Agents.md'
    def add_alias_after_plan(*args, **kwargs):
        plan = original(*args, **kwargs)
        wrong.write_bytes(b'# Concurrent project rule\n')
        return plan
    monkeypatch.setattr(surface, 'project_surface_plan', add_alias_after_plan)
    result = surface.sync_project_surface(tmp_path, project_id='fixture', apply=True)
    assert result['status'] == 'BLOCKED', result
    assert 'Agents.md' in str(result['blockers'])
    assert wrong.read_bytes() == b'# Concurrent project rule\n'
    assert result['changes'] == []
    assert {p.name for p in tmp_path.iterdir()} == {'Agents.md'}


@pytest.mark.parametrize('failure', ['encoding', 'permission'])
def test_b10_unreadable_root_rules_return_explicit_blocked_without_rewriting(tmp_path, monkeypatch, failure):
    from pathlib import Path
    path = tmp_path / 'AGENTS.md'
    raw = b'# Project-owned\n\xff' if failure == 'encoding' else b'# Project-owned\n'
    path.write_bytes(raw)
    original = Path.read_bytes
    def fail_target_read(self):
        if self == path:
            raise PermissionError('injected rule read failure')
        return original(self)
    with monkeypatch.context() as context:
        if failure == 'permission':
            context.setattr(Path, 'read_bytes', fail_target_read)
        try:
            result = sync_project_surface(tmp_path, project_id='fixture', apply=True)
        except (UnicodeError, OSError) as exc:
            pytest.fail(f'Rule-source failure escaped structured sync result: {exc}')
    assert result['status'] == 'BLOCKED', result
    assert 'AGENTS.md' in str(result['blockers'])
    assert result['changes'] == []
    assert path.read_bytes() == raw
    assert {p.name for p in tmp_path.iterdir()} == {'AGENTS.md'}
