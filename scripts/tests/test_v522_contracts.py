from pathlib import Path
import json
import pytest
from cli.workflow_controls import PreferenceError, resolve_confirmation_policy, build_boundary_binding, workflow_confirmation_matches, build_wake_prompt
from cli.delivery_contract import validate_delivery_result, delivery_result_matches_verification, disposition_allows_pipeline_completion

SEARCH_RECEIPT={'schema':'tp-spec.knowledge-search/v1','status':'PASS','scope':'project','query':'targeted durable rule','query_hash':'8340de87c4fa84012802a84be1cb845511b7a385b9c09b0aa606f6df20b2f27c','count':0,'results':[]}
LINT_RECEIPT={'schema':'tp-spec.knowledge-lint/v1','status':'PASS','errors':0}
INDEX_RECEIPT={'status':'PASS','fresh':True}



def test_missing_user_preferences_falls_back_to_material(tmp_path: Path):
    assert resolve_confirmation_policy(None, tmp_path / 'missing.yaml', 'material') == 'material'

def test_preferences_file_without_workflow_setting_still_uses_base_default(tmp_path: Path):
    p=tmp_path/'preferences.yaml'; p.write_text('schema: tp-spec.preferences/v1\nappearance:\n  compact: true\n',encoding='utf-8')
    assert resolve_confirmation_policy(None,p,'material')=='material'

def test_user_each_stage_overrides_base_default(tmp_path: Path):
    p=tmp_path/'preferences.yaml'; p.write_text('schema: tp-spec.preferences/v1\nworkflow:\n  confirmation_policy: each_stage\n',encoding='utf-8')
    assert resolve_confirmation_policy(None,p,'material')=='each_stage'

def test_cli_policy_overrides_user_preference(tmp_path: Path):
    p=tmp_path/'preferences.yaml'; p.write_text('schema: tp-spec.preferences/v1\nworkflow:\n  confirmation_policy: each_stage\n',encoding='utf-8')
    assert resolve_confirmation_policy('material',p,'material')=='material'

def test_invalid_user_policy_fails_closed(tmp_path: Path):
    p=tmp_path/'preferences.yaml'; p.write_text('schema: tp-spec.preferences/v1\nworkflow:\n  confirmation_policy: always\n',encoding='utf-8')
    with pytest.raises(PreferenceError): resolve_confirmation_policy(None,p,'material')

def test_boundary_confirmation_is_bound_to_source_fact_and_target():
    binding=build_boundary_binding(task_id='TASK-1',source_stage='verification',source_role='tp-verification-engineering',source_event_id=42,source_event_digest='abc',target_stage='development',target_role='tp-development-engineering',execution_mode='DIRECT')
    event={'task_id':'TASK-1','event_type':'WORKFLOW_CONFIRMATION','actor_role':'human_owner','created_at':'2026-08-14T00:00:00Z','workflow_version':'5.2.3','detail_json':json.dumps({'producer':'workflow_confirm','transaction_id':'tx1','schema_version':'5.2.3','task_id':'TASK-1','actor_role':'human_owner','created_at':'2026-08-14T00:00:00Z',**binding})}
    assert workflow_confirmation_matches(event,binding)
    stale=dict(binding); stale['source_event_id']=43
    assert not workflow_confirmation_matches(event,stale)

def test_ordinary_confirmation_cannot_satisfy_material_binding():
    ordinary=build_boundary_binding(task_id='TASK-1',source_stage='architecture',source_role='tp-architecture-design',source_event_id=42,source_event_digest='sha256:arch',target_stage='development',target_role='tp-development-engineering',execution_mode='DIRECT',confirmation_kind='ordinary')
    material=build_boundary_binding(task_id='TASK-1',source_stage='architecture',source_role='tp-architecture-design',source_event_id=42,source_event_digest='sha256:arch',target_stage='development',target_role='tp-development-engineering',execution_mode='DIRECT',confirmation_kind='material')
    ev=_trusted_event(50,'WORKFLOW_CONFIRMATION','human_owner','workflow_confirm',ordinary)
    assert workflow_confirmation_matches(ev,ordinary)
    assert not workflow_confirmation_matches(ev,material)

def test_wake_prompt_is_short_navigation_pointer():
    prompt=build_wake_prompt(task_id='TASK-1',workspace=r'E:\project\demo',source_stage='architecture',source_role='tp-architecture-design',target_stage='development',target_role='tp-development-engineering',execution_mode='DIRECT')
    assert 'TASK-1' in prompt and 'workflow next' in prompt and 'tp-development-engineering' in prompt
    assert 'evidence' not in prompt.lower() and len(prompt)<360

@pytest.mark.parametrize('disposition',['CREATED','UPDATED'])
def test_created_updated_require_refs_receipts_evidence_and_source_refs(disposition):
    detail={'knowledge_disposition':disposition,'knowledge_refs':['K-1'],'search_receipts':[SEARCH_RECEIPT],'lint_receipts':[LINT_RECEIPT],'index_receipts':[INDEX_RECEIPT],'evidence':['evidence/verify.log'],'source_refs':['src/app.py:10'],'reason':'reusable rule updated'}
    assert validate_delivery_result(detail)==[]
    for key in ('knowledge_refs','search_receipts','lint_receipts','index_receipts','evidence','source_refs'):
        broken=dict(detail); broken[key]=[]; assert validate_delivery_result(broken),key

def test_no_change_requires_targeted_search_and_concrete_reason():
    good={'knowledge_disposition':'NO_CHANGE','search_receipts':[SEARCH_RECEIPT],'reason':'Targeted project+shared search found existing canonical already covers the verified rule; no durable delta.'}
    assert validate_delivery_result(good)==[] and disposition_allows_pipeline_completion(good)
    assert validate_delivery_result({**good,'search_receipts':[]})
    assert validate_delivery_result({**good,'reason':'无需更新'})

def test_deferred_requires_owner_acceptance_to_complete():
    d={'knowledge_disposition':'DEFERRED','reason':'Knowledge resolver unavailable','recovery_condition':'resolver doctor passes','blocker_kind':'RESOLVER_UNAVAILABLE','responsibility':'restore Knowledge Resolver then rerun delivery'}
    assert validate_delivery_result(d)==[]
    assert not disposition_allows_pipeline_completion(d,deferred_accepted=False)
    assert disposition_allows_pipeline_completion(d,deferred_accepted=True)

def test_blocked_never_completes():
    b={'knowledge_disposition':'BLOCKED','reason':'canonical ownership conflict'}
    assert validate_delivery_result(b)==[] and not disposition_allows_pipeline_completion(b)

def test_delivery_result_is_bound_to_latest_verification():
    d={'knowledge_disposition':'NO_CHANGE','search_receipts':[SEARCH_RECEIPT],'reason':'Targeted search found no durable knowledge delta after verification.','verification_event_id':77,'verification_subject_digest':'sha256:subject'}
    assert delivery_result_matches_verification(d,77,'sha256:subject')
    assert not delivery_result_matches_verification(d,78,'sha256:subject')
    assert not delivery_result_matches_verification(d,77,'sha256:new')

from cli.workflow_records import build_confirmation_detail, build_delivery_detail


def test_confirmation_detail_keeps_binding_and_trusted_identity_fields():
    binding=build_boundary_binding(task_id='TASK-1',source_stage='requirement',source_role='tp-requirement-analysis',source_event_id=9,source_event_digest='sha256:event',target_stage='architecture',target_role='tp-architecture-design',execution_mode='DIRECT')
    detail=build_confirmation_detail(task_id='TASK-1',binding=binding,transaction_id='tx-1',flush_id='CONFIRM-1',created_at='2026-08-14T00:00:00Z',schema_version='5.2.3')
    assert detail['producer']=='workflow_confirm' and detail['actor_role']=='human_owner'
    assert detail['transaction_id']=='tx-1' and detail['task_id']=='TASK-1'
    assert all(detail[k]==v for k,v in binding.items())


def test_delivery_detail_binds_verification_and_disposition_fields():
    detail=build_delivery_detail(task_id='TASK-1',transaction_id='tx-2',flush_id='DELIVERY-1',created_at='2026-08-14T00:00:00Z',schema_version='5.2.3',verification_event_id=77,verification_subject_digest='sha256:subject',knowledge_disposition='NO_CHANGE',reason='Targeted project+shared search found no durable delta after verification.',search_receipts=[SEARCH_RECEIPT])
    assert detail['producer']=='delivery_converge' and detail['actor_role']=='tp-delivery-convergence'
    assert detail['verification_event_id']==77 and detail['verification_subject_digest']=='sha256:subject'
    assert detail['knowledge_disposition']=='NO_CHANGE' and detail['search_receipts']==[SEARCH_RECEIPT]

from cli.workflow_controls import trusted_event_detail, find_matching_confirmation, event_digest
from cli.delivery_contract import find_delivery_completion_event


def _trusted_event(event_id, event_type, actor, producer, detail_extra=None):
    detail={'transaction_id':f'tx-{event_id}','producer':producer,'schema_version':'5.2.3','task_id':'TASK-1','actor_role':actor,'created_at':'2026-08-14T00:00:00Z'}
    detail.update(detail_extra or {})
    return {'id':event_id,'task_id':'TASK-1','event_type':event_type,'actor_role':actor,'to_stage':'','summary':'','detail_json':json.dumps(detail,ensure_ascii=False),'workflow_version':'5.2.3','created_at':'2026-08-14T00:00:00Z'}


def test_trusted_event_detail_requires_identity_chain():
    ev=_trusted_event(1,'WORKFLOW_CONFIRMATION','human_owner','workflow_confirm')
    assert trusted_event_detail(ev,event_type='WORKFLOW_CONFIRMATION',producer='workflow_confirm',actor='human_owner')
    bad=dict(ev); d=json.loads(bad['detail_json']); d.pop('transaction_id'); bad['detail_json']=json.dumps(d)
    assert trusted_event_detail(bad,event_type='WORKFLOW_CONFIRMATION',producer='workflow_confirm',actor='human_owner') is None


def test_matching_confirmation_ignores_stale_source_binding():
    binding=build_boundary_binding(task_id='TASK-1',source_stage='requirement',source_role='tp-requirement-analysis',source_event_id=10,source_event_digest='sha256:old',target_stage='architecture',target_role='tp-architecture-design',execution_mode='DIRECT')
    ev=_trusted_event(11,'WORKFLOW_CONFIRMATION','human_owner','workflow_confirm',binding)
    assert find_matching_confirmation([ev],binding) is ev
    new_binding=dict(binding); new_binding['source_event_id']=12; new_binding['source_event_digest']='sha256:new'
    assert find_matching_confirmation([ev],new_binding) is None


def test_plain_delivery_checkpoint_does_not_count_as_delivery_completion():
    verify=_trusted_event(20,'VERIFICATION_COMPLETED','tp-verification-engineering','record-first',{'decision':'PASS','subject_digest':'sha256:s'})
    checkpoint=_trusted_event(21,'FACT','tp-delivery-convergence','record-first',{'operation':'CHECKPOINT','phase':'delivery'})
    assert find_delivery_completion_event([verify,checkpoint],verification_event=verify,current_subject_digest='sha256:s') is None


def test_valid_no_change_delivery_result_completes_and_new_verification_invalidates_it():
    verify=_trusted_event(20,'VERIFICATION_COMPLETED','tp-verification-engineering','record-first',{'decision':'PASS','subject_digest':'sha256:s'})
    detail={'verification_event_id':20,'verification_subject_digest':'sha256:s','knowledge_disposition':'NO_CHANGE','search_receipts':[SEARCH_RECEIPT],'reason':'Targeted project+shared search found no durable delta after verification.'}
    delivery=_trusted_event(21,'DELIVERY_RESULT','tp-delivery-convergence','delivery_converge',detail)
    assert find_delivery_completion_event([verify,delivery],verification_event=verify,current_subject_digest='sha256:s') is delivery
    verify2=_trusted_event(22,'VERIFICATION_COMPLETED','tp-verification-engineering','record-first',{'decision':'PASS','subject_digest':'sha256:s2'})
    assert find_delivery_completion_event([verify,delivery,verify2],verification_event=verify2,current_subject_digest='sha256:s2') is None


def test_blocked_delivery_overrides_older_good_result_for_same_verification():
    verify=_trusted_event(20,'VERIFICATION_COMPLETED','tp-verification-engineering','record-first',{'decision':'PASS','subject_digest':'sha256:s'})
    good=_trusted_event(21,'DELIVERY_RESULT','tp-delivery-convergence','delivery_converge',{'verification_event_id':20,'verification_subject_digest':'sha256:s','knowledge_disposition':'NO_CHANGE','search_receipts':[SEARCH_RECEIPT],'reason':'Targeted project+shared search found no durable delta after verification.'})
    blocked=_trusted_event(22,'DELIVERY_RESULT','tp-delivery-convergence','delivery_converge',{'verification_event_id':20,'verification_subject_digest':'sha256:s','knowledge_disposition':'BLOCKED','reason':'Canonical ownership conflict blocks safe convergence.'})
    assert find_delivery_completion_event([verify,good,blocked],verification_event=verify,current_subject_digest='sha256:s') is None


def test_deferred_delivery_completes_only_after_matching_human_acceptance():
    verify=_trusted_event(20,'VERIFICATION_COMPLETED','tp-verification-engineering','record-first',{'decision':'PASS','subject_digest':'sha256:s'})
    deferred=_trusted_event(21,'DELIVERY_RESULT','tp-delivery-convergence','delivery_converge',{'verification_event_id':20,'verification_subject_digest':'sha256:s','knowledge_disposition':'DEFERRED','reason':'Knowledge resolver infrastructure is unavailable for the required targeted search.','recovery_condition':'knowledge doctor passes','blocker_kind':'RESOLVER_UNAVAILABLE','responsibility':'restore Knowledge Resolver and rerun delivery'})
    assert find_delivery_completion_event([verify,deferred],verification_event=verify,current_subject_digest='sha256:s') is None
    accept=_trusted_event(22,'DELIVERY_DEFERRED_ACCEPTED','human_owner','delivery_deferred_accept',{'delivery_event_id':21,'delivery_event_digest':event_digest(deferred),'reason':'Accept temporary deferral until resolver is restored.'})
    assert find_delivery_completion_event([verify,deferred,accept],verification_event=verify,current_subject_digest='sha256:s') is deferred


def test_delivery_completion_accepts_existing_trusted_commit_verification_producer():
    verify=_trusted_event(30,'VERIFICATION_COMPLETED','tp-verification-engineering','commit',{'decision':'PASS','subject_digest':'sha256:s'})
    delivery=_trusted_event(31,'DELIVERY_RESULT','tp-delivery-convergence','delivery_converge',{'verification_event_id':30,'verification_subject_digest':'sha256:s','knowledge_disposition':'NO_CHANGE','search_receipts':[SEARCH_RECEIPT],'reason':'Targeted project+shared search found no durable delta after verification.'})
    assert find_delivery_completion_event([verify,delivery],verification_event=verify,current_subject_digest='sha256:s') is delivery


def test_project_memory_reference_cannot_substitute_for_canonical_knowledge_ref():
    detail={'knowledge_disposition':'UPDATED','knowledge_refs':['.tp-spec/memory/PROJECT.md'],'search_receipts':[SEARCH_RECEIPT],'lint_receipts':[LINT_RECEIPT],'index_receipts':[INDEX_RECEIPT],'evidence':['evidence/verify.log'],'source_refs':['src/app.py:10'],'reason':'Reusable project rule updated in durable knowledge.'}
    assert any('Project Memory' in e for e in validate_delivery_result(detail))

from cli.delivery_contract import validate_receipt_payload


def test_search_receipt_must_be_pass_and_project_scoped():
    good=SEARCH_RECEIPT
    assert validate_receipt_payload('search',good)==[]
    assert validate_receipt_payload('search',{**good,'scope':'global'})
    assert validate_receipt_payload('search',{**good,'status':'FAIL'})


def test_search_receipt_rejects_missing_or_mismatched_query_identity():
    from cli.delivery_contract import validate_receipt_payload
    assert validate_receipt_payload('search',{**SEARCH_RECEIPT,'query':''})
    assert validate_receipt_payload('search',{**SEARCH_RECEIPT,'query_hash':'0'*64})
    assert validate_receipt_payload('search',{**SEARCH_RECEIPT,'count':1})


def test_lint_and_index_receipts_must_prove_success_and_fresh_projection():
    assert validate_receipt_payload('lint',{'schema':'tp-spec.knowledge-lint/v1','status':'PASS'})==[]
    assert validate_receipt_payload('lint',{'schema':'tp-spec.knowledge-lint/v1','status':'FAIL'})
    assert validate_receipt_payload('index',{'status':'PASS','fresh':True})==[]
    assert validate_receipt_payload('index',{'status':'WARN','fresh':True})
    assert validate_receipt_payload('index',{'status':'PASS','fresh':False})

from cli.workflow_controls import write_user_confirmation_policy


def test_writing_confirmation_preference_preserves_other_user_preferences(tmp_path: Path):
    p=tmp_path/'preferences.yaml'
    p.write_text('schema: tp-spec.preferences/v1\nappearance:\n  compact: true\nworkflow:\n  other: keep\n  confirmation_policy: material\n',encoding='utf-8')
    write_user_confirmation_policy(p,'each_stage')
    data=__import__('yaml').safe_load(p.read_text(encoding='utf-8'))
    assert data['appearance']['compact'] is True and data['workflow']['other']=='keep'
    assert data['workflow']['confirmation_policy']=='each_stage'


def test_canonical_binding_requires_task_evidence_locator_and_source_refs():
    from cli.delivery_contract import validate_canonical_binding
    good = {
        'canonical': True,
        'source_refs': [],
        'evidence_refs': [
            {'type': 'task', 'ref': 'TASK-1', 'locator': 'evidence/test.txt'},
            {'type': 'code', 'ref': 'repo/path:42'},
        ],
    }
    assert validate_canonical_binding(good, task_id='TASK-1', evidence_paths=['evidence/test.txt'], source_refs=['repo/path:42']) == []
    bad = {'canonical': True, 'source_refs': [], 'evidence_refs': [{'type': 'task', 'ref': 'TASK-X', 'locator': 'evidence/other.txt'}]}
    errors = validate_canonical_binding(bad, task_id='TASK-1', evidence_paths=['evidence/test.txt'], source_refs=['repo/path:42'])
    assert any('TASK-1' in e for e in errors)
    assert any('source/code ref' in e for e in errors)


def test_delivery_targeted_quality_does_not_call_full_vault_scanners():
    import inspect
    from cli import workflow_records
    source = inspect.getsource(workflow_records._run_targeted_knowledge_quality)
    assert 'collect_notes' not in source
    assert 'lint_knowledge' not in source
    assert 'update_projection' not in source
    assert 'build_projection' not in source


def test_targeted_quality_updates_only_exact_canonical_index(tmp_path, monkeypatch):
    import sqlite3, sys, types
    from types import SimpleNamespace
    from cli import workflow_records

    root = tmp_path / 'knowledge'
    rel = '10-projects/demo/30-features/DEMO-FEAT-001-rule.md'
    path = root / rel
    path.parent.mkdir(parents=True)
    path.write_text('---\nid: DEMO-FEAT-001\ncanonical: true\n---\nbody\n', encoding='utf-8')
    db = tmp_path / 'knowledge.db'
    conn = sqlite3.connect(db)
    conn.executescript('''
        CREATE TABLE documents(id INTEGER PRIMARY KEY AUTOINCREMENT, rel_path TEXT UNIQUE, canonical_id TEXT, sha256 TEXT, scope TEXT);
        CREATE TABLE chunks(id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER);
        CREATE TABLE fts_chunks(rowid INTEGER PRIMARY KEY);
        CREATE TABLE doc_links(doc_id INTEGER);
        CREATE TABLE graph_nodes(canonical_id TEXT PRIMARY KEY, kind TEXT, title TEXT, project TEXT, status TEXT, layer TEXT, rel_path TEXT, source_refs TEXT, confidence REAL, last_verified TEXT);
        CREATE TABLE graph_edges(id INTEGER PRIMARY KEY AUTOINCREMENT, edge_id TEXT UNIQUE, source_canonical_id TEXT, target_id TEXT, relation_type TEXT, evidence_source_ids TEXT, origin TEXT, reason TEXT DEFAULT '');
        CREATE TABLE build_meta(key TEXT PRIMARY KEY, value TEXT);
    ''')
    conn.commit(); conn.close()

    pkg = types.ModuleType('cli.knowledge'); pkg.__path__ = []
    common = types.ModuleType('cli.knowledge.common')
    common.load_source_registry = lambda cfg: {}
    common.now_iso = lambda: '2026-08-14T00:00:00Z'
    common.parse_frontmatter = lambda text: ({'id':'DEMO-FEAT-001','canonical':True,'kind':'feature','title':'Rule','project':'demo','status':'active','confidence':0.9,'last_verified':'2026-08-14','source_refs':[],'relations':[]}, 'body', None, 5)
    common.read_note = lambda p, *, root, scope: {'frontmatter': {'id':'DEMO-FEAT-001','canonical':True,'kind':'feature','title':'Rule','project':'demo','status':'active','confidence':0.9,'last_verified':'2026-08-14','source_refs':[],'relations':[]}, 'id':'DEMO-FEAT-001','kind':'feature','title':'Rule','project':'demo','source_refs':[],'sha256':'abc123','scope':'canonical','rel_path':rel}
    lint = types.ModuleType('cli.knowledge.lint'); lint._schema_errors = lambda fm: []
    projection = types.ModuleType('cli.knowledge.projection')
    projection._connect = lambda p: sqlite3.connect(p)
    def _insert_doc(c, note, registry):
        c.execute('INSERT INTO documents(rel_path,canonical_id,sha256,scope) VALUES(?,?,?,?)', (note['rel_path'], note['id'], note['sha256'], 'canonical'))
    projection._insert_doc = _insert_doc
    monkeypatch.setitem(sys.modules, 'cli.knowledge', pkg)
    monkeypatch.setitem(sys.modules, 'cli.knowledge.common', common)
    monkeypatch.setitem(sys.modules, 'cli.knowledge.lint', lint)
    monkeypatch.setitem(sys.modules, 'cli.knowledge.projection', projection)

    cfg = SimpleNamespace(
        paths=SimpleNamespace(knowledge_physical_root=root, knowledge_projection_db=db),
        knowledge_projection={'graph_mode':'optional'},
    )
    lint_receipts, index_receipts = workflow_records._run_targeted_knowledge_quality(cfg, [{'path':rel,'id':'DEMO-FEAT-001'}])
    assert lint_receipts[0]['status'] == 'PASS'
    assert index_receipts[0]['fresh'] is True
    assert index_receipts[0]['scope'] == 'exact-canonical'
    assert index_receipts[0]['global_projection_scan_performed'] is False
    conn = sqlite3.connect(db)
    try:
        assert conn.execute('SELECT canonical_id,sha256 FROM documents WHERE rel_path=?', (rel,)).fetchone() == ('DEMO-FEAT-001','abc123')
    finally:
        conn.close()


def test_targeted_search_forces_project_scope_and_disables_global_fallback(monkeypatch):
    import sys, types
    from types import SimpleNamespace
    from cli import workflow_records

    calls = []
    pkg = types.ModuleType('cli.knowledge'); pkg.__path__ = []
    projection = types.ModuleType('cli.knowledge.projection')
    def search(cfg, query, *, scope, limit, record_telemetry):
        calls.append((query, scope, limit, record_telemetry, cfg.knowledge_retrieval.get('global_fallback')))
        return [{'id':'DEMO-FEAT-001','path':'10-projects/demo/30-features/DEMO-FEAT-001-rule.md','project':'demo','kind':'feature','layer':'canonical'}]
    projection.search = search
    monkeypatch.setitem(sys.modules, 'cli.knowledge', pkg)
    monkeypatch.setitem(sys.modules, 'cli.knowledge.projection', projection)
    cfg = SimpleNamespace(knowledge_retrieval={'global_fallback':True})
    receipts = workflow_records._run_targeted_search(cfg, ['delivery rule'])
    assert calls == [('delivery rule','project',5,True,False)]
    assert cfg.knowledge_retrieval['global_fallback'] is True
    assert receipts[0]['scope'] == 'project' and receipts[0]['count'] == 1
    assert receipts[0]['results'][0]['id'] == 'DEMO-FEAT-001'
