from pathlib import Path
import yaml
from cli.version import active_version
BASE=Path(__file__).resolve().parents[2]

def test_active_contract_cutover_is_complete():
    assert active_version()=='5.2.2'
    assert (BASE/'templates/5.2.2/status.yaml').is_file()
    assert not (BASE/'templates'/('5.1.' + '3')).exists()
    status=yaml.safe_load((BASE/'templates/5.2.2/status.yaml').read_text(encoding='utf-8'))
    assert status['artifact_contract']['version']=='5.2.2'
    assert status['base_version']=='5.2.2'

def test_compat_matrix_has_only_active_contract():
    c=yaml.safe_load((BASE/'governance/compat-matrix.yaml').read_text(encoding='utf-8'))
    assert set(c['contracts'])=={'5.2.2'}
    assert c['contracts']['5.2.2']['status_contract']=='5.2.2'
    assert c['contracts']['5.2.2']['governance_ranges']['orchestration']=='[5.2.2, 5.3.0)'

def test_database_schema_unchanged_for_orchestration():
    sql=(BASE/'db/schema.sql').read_text(encoding='utf-8')
    lowered=sql.lower()
    assert 'workflow_task' not in lowered
    assert 'workflow_event' not in lowered
    assert 'workflow_route' not in lowered
