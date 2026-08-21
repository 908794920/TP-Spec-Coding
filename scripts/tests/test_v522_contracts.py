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
    binding=build_boundary_binding(task_id='TASK-1',source_stage='verification',source_role='tp-test-engineer',source_event_id=42,source_event_digest='abc',target_stage='development',target_role='tp-development-engineer',execution_mode='DIRECT')
    event={'task_id':'TASK-1','event_type':'WORKFLOW_CONFIRMATION','actor_role':'human_owner','created_at':'2026-08-14T00:00:00Z','workflow_version':'5.2.6','detail_json':json.dumps({'producer':'workflow_confirm','transaction_id':'tx1','schema_version':'5.2.6','task_id':'TASK-1','actor_role':'human_owner','created_at':'2026-08-14T00:00:00Z',**binding})}
    assert workflow_confirmation_matches(event,binding)
    stale=dict(binding); stale['source_event_id']=43
    assert not workflow_confirmation_matches(event,stale)

def test_ordinary_confirmation_cannot_satisfy_material_binding():
    ordinary=build_boundary_binding(task_id='TASK-1',source_stage='architecture',source_role='tp-software-architect',source_event_id=42,source_event_digest='sha256:arch',target_stage='development',target_role='tp-development-engineer',execution_mode='DIRECT',confirmation_kind='ordinary')
    material=build_boundary_binding(task_id='TASK-1',source_stage='architecture',source_role='tp-software-architect',source_event_id=42,source_event_digest='sha256:arch',target_stage='development',target_role='tp-development-engineer',execution_mode='DIRECT',confirmation_kind='material')
    ev=_trusted_event(50,'WORKFLOW_CONFIRMATION','human_owner','workflow_confirm',ordinary)
    assert workflow_confirmation_matches(ev,ordinary)
    assert not workflow_confirmation_matches(ev,material)

def test_wake_prompt_is_short_navigation_pointer():
    prompt=build_wake_prompt(task_id='TASK-1',workspace=r'E:\project\demo',source_stage='architecture',source_role='tp-software-architect',target_stage='development',target_role='tp-development-engineer',execution_mode='DIRECT')
    assert 'TASK-1' in prompt and 'workflow next' in prompt and 'tp-development-engineer' in prompt
    assert 'evidence' not in prompt.lower() and len(prompt)<360

@pytest.mark.parametrize('status',['READY','BLOCKED'])
def test_delivery_status_contract_is_integration_owned(status):
    detail={
        'delivery_status':status,
        'reason':'Verified integration status is recorded with concrete evidence and current subject binding.',
        'verification_event_id':77,
        'verification_subject_digest':'sha256:subject',
    }
    if status == 'BLOCKED':
        detail.update({
            'blocker_kind':'INTEGRATION_CONFLICT',
            'recovery_condition':'resolve the integration conflict and rerun delivery readiness',
            'responsibility':'integration engineer resolves conflict or escalates to human_owner',
        })
    assert validate_delivery_result(detail)==[]
    assert disposition_allows_pipeline_completion(detail) is (status == 'READY')


def test_ready_delivery_requires_concrete_reason_and_verification_binding():
    good={'delivery_status':'READY','reason':'Verified change is ready for integration and no delivery blocker remains.','verification_event_id':77,'verification_subject_digest':'sha256:subject'}
    assert validate_delivery_result(good)==[]
    assert validate_delivery_result({**good,'reason':'ok'})
    assert validate_delivery_result({**good,'verification_event_id':0})
    assert validate_delivery_result({**good,'verification_subject_digest':''})


def test_blocked_delivery_requires_recovery_contract_and_never_completes():
    blocked={'delivery_status':'BLOCKED','reason':'Integration conflict prevents safe delivery of the verified subject.','verification_event_id':77,'verification_subject_digest':'sha256:subject','blocker_kind':'INTEGRATION_CONFLICT','recovery_condition':'resolve conflict and rerun integration readiness','responsibility':'integration engineer or human_owner'}
    assert validate_delivery_result(blocked)==[]
    assert not disposition_allows_pipeline_completion(blocked)
    assert validate_delivery_result({**blocked,'recovery_condition':''})


def test_delivery_result_is_bound_to_latest_verification():
    d={'delivery_status':'READY','reason':'Verified change is ready for integration and no delivery blocker remains.','verification_event_id':77,'verification_subject_digest':'sha256:subject'}
    assert delivery_result_matches_verification(d,77,'sha256:subject')
    assert not delivery_result_matches_verification(d,78,'sha256:subject')
    assert not delivery_result_matches_verification(d,77,'sha256:new')

from cli.workflow_records import build_confirmation_detail, build_delivery_detail


def test_confirmation_detail_keeps_binding_and_trusted_identity_fields():
    binding=build_boundary_binding(task_id='TASK-1',source_stage='requirement',source_role='tp-product-manager',source_event_id=9,source_event_digest='sha256:event',target_stage='architecture',target_role='tp-software-architect',execution_mode='DIRECT')
    detail=build_confirmation_detail(task_id='TASK-1',binding=binding,transaction_id='tx-1',flush_id='CONFIRM-1',created_at='2026-08-14T00:00:00Z',schema_version='5.2.6')
    assert detail['producer']=='workflow_confirm' and detail['actor_role']=='human_owner'
    assert detail['transaction_id']=='tx-1' and detail['task_id']=='TASK-1'
    assert all(detail[k]==v for k,v in binding.items())


def test_delivery_detail_binds_verification_and_readiness_fields():
    detail=build_delivery_detail(
        task_id='TASK-1', transaction_id='tx-2', flush_id='DELIVERY-1',
        created_at='2026-08-14T00:00:00Z', schema_version='5.2.6',
        verification_event_id=77, verification_subject_digest='sha256:subject',
        delivery_status='READY', reason='Verified change is ready for integration and no delivery blocker remains.',
        repo_snapshot={'before_head':'a','after_head':'b','merge_commit':'m'},
        knowledge_handoff={'task_id':'TASK-1','verification_event_id':77},
    )
    assert detail['producer']=='delivery_converge' and detail['actor_role']=='tp-integration-engineer'
    assert detail['verification_event_id']==77 and detail['verification_subject_digest']=='sha256:subject'
    assert detail['delivery_status']=='READY'
    assert detail['repo_snapshot']['before_head']=='a'
    assert detail['knowledge_handoff']['task_id']=='TASK-1'
    assert 'knowledge_disposition' not in detail

from cli.workflow_controls import trusted_event_detail, find_matching_confirmation, event_digest
from cli.delivery_contract import find_delivery_completion_event


def _trusted_event(event_id, event_type, actor, producer, detail_extra=None):
    detail={'transaction_id':f'tx-{event_id}','producer':producer,'schema_version':'5.2.6','task_id':'TASK-1','actor_role':actor,'created_at':'2026-08-14T00:00:00Z'}
    detail.update(detail_extra or {})
    return {'id':event_id,'task_id':'TASK-1','event_type':event_type,'actor_role':actor,'to_stage':'','summary':'','detail_json':json.dumps(detail,ensure_ascii=False),'workflow_version':'5.2.6','created_at':'2026-08-14T00:00:00Z'}


def test_trusted_event_detail_requires_identity_chain():
    ev=_trusted_event(1,'WORKFLOW_CONFIRMATION','human_owner','workflow_confirm')
    assert trusted_event_detail(ev,event_type='WORKFLOW_CONFIRMATION',producer='workflow_confirm',actor='human_owner')
    bad=dict(ev); d=json.loads(bad['detail_json']); d.pop('transaction_id'); bad['detail_json']=json.dumps(d)
    assert trusted_event_detail(bad,event_type='WORKFLOW_CONFIRMATION',producer='workflow_confirm',actor='human_owner') is None


def test_matching_confirmation_ignores_stale_source_binding():
    binding=build_boundary_binding(task_id='TASK-1',source_stage='requirement',source_role='tp-product-manager',source_event_id=10,source_event_digest='sha256:old',target_stage='architecture',target_role='tp-software-architect',execution_mode='DIRECT')
    ev=_trusted_event(11,'WORKFLOW_CONFIRMATION','human_owner','workflow_confirm',binding)
    assert find_matching_confirmation([ev],binding) is ev
    new_binding=dict(binding); new_binding['source_event_id']=12; new_binding['source_event_digest']='sha256:new'
    assert find_matching_confirmation([ev],new_binding) is None


def test_plain_delivery_checkpoint_does_not_count_as_delivery_completion():
    verify=_trusted_event(20,'VERIFICATION_COMPLETED','tp-test-engineer','record-first',{'decision':'PASS','subject_digest':'sha256:s'})
    checkpoint=_trusted_event(21,'FACT','tp-integration-engineer','record-first',{'operation':'CHECKPOINT','phase':'delivery'})
    assert find_delivery_completion_event([verify,checkpoint],verification_event=verify,current_subject_digest='sha256:s') is None


def test_ready_delivery_result_completes_and_new_verification_invalidates_it():
    verify=_trusted_event(20,'VERIFICATION_COMPLETED','tp-test-engineer','record-first',{'decision':'PASS','subject_digest':'sha256:s'})
    detail={'verification_event_id':20,'verification_subject_digest':'sha256:s','delivery_status':'READY','reason':'Verified change is ready for integration and no blocker remains.'}
    delivery=_trusted_event(21,'DELIVERY_RESULT','tp-integration-engineer','delivery_converge',detail)
    assert find_delivery_completion_event([verify,delivery],verification_event=verify,current_subject_digest='sha256:s') is delivery
    verify2=_trusted_event(22,'VERIFICATION_COMPLETED','tp-test-engineer','record-first',{'decision':'PASS','subject_digest':'sha256:s2'})
    assert find_delivery_completion_event([verify,delivery,verify2],verification_event=verify2,current_subject_digest='sha256:s2') is None


def test_newer_blocked_delivery_overrides_older_ready_result_for_same_verification():
    verify=_trusted_event(20,'VERIFICATION_COMPLETED','tp-test-engineer','record-first',{'decision':'PASS','subject_digest':'sha256:s'})
    ready=_trusted_event(21,'DELIVERY_RESULT','tp-integration-engineer','delivery_converge',{'verification_event_id':20,'verification_subject_digest':'sha256:s','delivery_status':'READY','reason':'Verified change is ready for integration and no blocker remains.'})
    blocked=_trusted_event(22,'DELIVERY_RESULT','tp-integration-engineer','delivery_converge',{'verification_event_id':20,'verification_subject_digest':'sha256:s','delivery_status':'BLOCKED','reason':'Integration conflict prevents safe delivery of the verified subject.','blocker_kind':'INTEGRATION_CONFLICT','recovery_condition':'resolve the conflict and rerun readiness','responsibility':'integration engineer'})
    assert find_delivery_completion_event([verify,ready,blocked],verification_event=verify,current_subject_digest='sha256:s') is None


def test_delivery_completion_rejects_removed_legacy_commit_producer():
    verify=_trusted_event(30,'VERIFICATION_COMPLETED','tp-test-engineer','commit',{'decision':'PASS','subject_digest':'sha256:s'})
    delivery=_trusted_event(31,'DELIVERY_RESULT','tp-integration-engineer','delivery_converge',{'verification_event_id':30,'verification_subject_digest':'sha256:s','delivery_status':'READY','reason':'Verified change is ready for integration and no blocker remains.'})
    assert find_delivery_completion_event([verify,delivery],verification_event=verify,current_subject_digest='sha256:s') is None


def test_knowledge_handoff_is_not_part_of_delivery_completion_decision():
    verify=_trusted_event(40,'VERIFICATION_COMPLETED','tp-test-engineer','record-first',{'decision':'PASS','subject_digest':'sha256:s'})
    delivery=_trusted_event(41,'DELIVERY_RESULT','tp-integration-engineer','delivery_converge',{'verification_event_id':40,'verification_subject_digest':'sha256:s','delivery_status':'READY','reason':'Verified change is ready for integration and no blocker remains.','knowledge_handoff':{'task_id':'TASK-1','verified_facts':['durable fact']}})
    assert find_delivery_completion_event([verify,delivery],verification_event=verify,current_subject_digest='sha256:s') is delivery

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


def test_task_scoped_knowledge_convergence_does_not_call_full_vault_scanners():
    import inspect
    from cli.knowledge import state as knowledge_state
    source = inspect.getsource(knowledge_state.task_scoped_convergence)
    for forbidden in ('collect_notes', 'lint_knowledge', 'update_projection', 'build_projection', 'projection.search'):
        assert forbidden not in source


def test_task_scoped_knowledge_no_change_is_nonblocking_fast_path():
    from cli.knowledge import state as knowledge_state
    result=knowledge_state.task_scoped_convergence({'task_id':'TASK-1','verified_facts':[],'reusable_findings':[]})
    assert result['status']=='NO_CHANGE'
    assert result['blocks_delivery'] is False


def test_task_scoped_knowledge_reusable_fact_is_deferred_without_blocking_delivery():
    from cli.knowledge import state as knowledge_state
    result=knowledge_state.task_scoped_convergence({'task_id':'TASK-1','verified_facts':['reusable rule'],'reusable_findings':[]})
    assert result['status']=='DEFERRED'
    assert result['blocks_delivery'] is False
