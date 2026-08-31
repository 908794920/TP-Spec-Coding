# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.tests.runtime_testutil import run
from cli import db as dbmod
from cli import orchestration
from cli import event_policies


class V522WorkflowDeliveryCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='v522-workflow-delivery-'))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.project = self.root / 'project'
        self.registry = self.root / 'registry.json'
        self.registry.write_text('{"projects": []}\n', encoding='utf-8')
        self.user_root = self.root / 'user-tp-spec'
        self.env = patch.dict(os.environ, {'TP_SPEC_USER_ROOT': str(self.user_root)}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        rc, out, err = run([
            'project', 'bootstrap', '--id', 'demo', '--root', str(self.project),
            '--registry', str(self.registry),
        ])
        self.assertEqual(rc, 0, (out, err))
        self.db = self.project / '.tp-spec' / 'db' / 'demo.db'
        subprocess.run(['git', 'init', '-q'], cwd=self.project, check=True)
        subprocess.run(['git', 'config', 'user.name', 'test'], cwd=self.project, check=True)
        subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=self.project, check=True)
        (self.project / 'README.md').write_text('demo\n', encoding='utf-8')
        subprocess.run(['git', 'add', 'README.md'], cwd=self.project, check=True)
        subprocess.run(['git', 'commit', '-qm', 'baseline'], cwd=self.project, check=True)
        self.wiki_root = self.root / 'wiki'
        self.knowledge_root = self.root / 'knowledge'
        self.wiki_root.mkdir(parents=True, exist_ok=True)
        (self.knowledge_root / '00-system').mkdir(parents=True, exist_ok=True)
        base_root = Path(__file__).resolve().parents[2]
        self.user_root.mkdir(parents=True, exist_ok=True)
        (self.user_root / 'installation.yaml').write_text(
            'schema: tp-spec.installation/v1\n'
            f'base:\n  root: {json.dumps(str(base_root))}\n'
            f'systems:\n  wiki:\n    root: {json.dumps(str(self.wiki_root))}\n  knowledge:\n    root: {json.dumps(str(self.knowledge_root))}\n',
            encoding='utf-8',
        )
        (self.knowledge_root / '00-system' / 'project-registry.yaml').write_text(
            'registry_version: "1"\nprojects:\n'
            f'  - id: demo\n    display_name: Demo\n    status: active\n    workspace_roots:\n      - {json.dumps(str(self.project))}\n'
            'shared_scopes: []\n',
            encoding='utf-8',
        )
        rc, out, err = run(['knowledge', 'index', 'build', '--workspace-root', str(self.project)])
        self.assertEqual(rc, 0, (out, err))

    def create_task(self, task_id: str, level: str = 'L2') -> Path:
        task_dir = self.project / '.tp-spec' / 'tasks' / task_id
        rc, out, err = run([
            'task', 'create', '--id', task_id, '--project', 'demo', '--risk', level, '--flow', level,
            '--db', str(self.db), '--scaffold', '--task-dir', str(task_dir),
        ])
        self.assertEqual(rc, 0, (out, err))
        (task_dir / 'acceptance.md').write_text(
            '# 验收条件与证据矩阵\n\n'
            '```yaml\n'
            'no_acceptance_required:\n'
            '  declared: true\n'
            '  reason: Delivery 流程测试不包含业务验收项\n'
            'deferred_acceptance: []\n'
            'owner_waivers: []\n'
            'database_operations: []\n'
            '```\n',
            encoding='utf-8',
            newline='\n',
        )
        return task_dir

    def call(self, *args, refresh_card: bool = False):
        return run(list(args) + ['--db', str(self.db)], refresh_card=refresh_card)

    def checkpoint(self, task_id: str, task_dir: Path, actor: str, phase: str, summary: str = 'done'):
        rc, out, err = self.call(
            'task', 'checkpoint', '--task', task_id, '--task-dir', str(task_dir),
            '--actor', actor, '--phase', phase, '--summary', summary,
        )
        self.assertEqual(rc, 0, (out, err))

    def verify(self, task_id: str, task_dir: Path, decision: str = 'PASS', knowledge_signal: dict | None = None):
        args = [
            'task', 'verify', '--task', task_id, '--task-dir', str(task_dir),
            '--actor', 'tp-test-engineer', '--decision', decision,
            '--summary', f'verification {decision}',
        ]
        if decision == 'PASS':
            evidence = task_dir / 'evidence' / f'verify-{len(self.events(task_id))}.txt'
            evidence.parent.mkdir(exist_ok=True)
            evidence.write_text('verified\n', encoding='utf-8')
            args += ['--evidence', str(evidence.relative_to(task_dir)).replace('\\', '/')]
        if knowledge_signal is not None:
            args += ['--knowledge-signal-json', json.dumps(knowledge_signal, ensure_ascii=False)]
        rc, out, err = self.call(*args)
        self.assertEqual(rc, 0, (out, err))

    def code_review(self, task_id: str, task_dir: Path, decision: str = 'PASS'):
        rc, out, err = self.call(
            'review', 'record', '--task', task_id, '--task-dir', str(task_dir),
            '--actor', 'tp-code-reviewer', '--kind', 'CODE', '--decision', decision,
            '--summary', f'code review {decision}',
        )
        self.assertEqual(rc, 0, (out, err))

    def events(self, task_id: str):
        conn = dbmod.connect(str(self.db))
        try:
            return conn.execute('SELECT * FROM task_event WHERE task_id=? ORDER BY id', (task_id,)).fetchall()
        finally:
            conn.close()

    def add_legacy_material_decision_marker(self, task_id: str):
        conn = dbmod.connect(str(self.db))
        try:
            now = dbmod.now_iso()
            with dbmod.transactional(conn):
                conn.execute(
                    'INSERT INTO task_event(task_id,event_type,actor_role,summary,created_at) VALUES(?,?,?,?,?)',
                    (task_id, 'DECISION', 'human_owner', 'workflow:material-confirmed:architecture->development', now),
                )
        finally:
            conn.close()

    def confirm_each_stage(self, task_id: str, task_dir: Path):
        rc, out, err = self.call(
            'workflow', 'confirm', '--task', task_id, '--task-dir', str(task_dir),
            '--confirmation-policy', 'each_stage', '--json',
        )
        self.assertEqual(rc, 0, (out, err))
        return json.loads(out)

    def prepare_l2_to_verification_pass(self, task_id: str, task_dir: Path, knowledge_signal: dict | None = None):
        self.checkpoint(task_id, task_dir, 'tp-product-manager', 'requirement')
        self.checkpoint(task_id, task_dir, 'tp-software-architect', 'architecture')
        self.checkpoint(task_id, task_dir, 'tp-tech-lead', 'planning')
        rc, out, err = self.call(
            'workflow', 'confirm', '--task', task_id, '--task-dir', str(task_dir), '--json',
        )
        self.assertEqual(rc, 0, (out, err))
        self.checkpoint(task_id, task_dir, 'tp-development-engineer', 'development')
        self.verify(task_id, task_dir, 'PASS', knowledge_signal=knowledge_signal)


    def test_new_gate_events_are_trusted_only_from_official_producers(self):
        self.assertTrue(event_policies.event_allowed_for_producer('WORKFLOW_CONFIRMATION', 'workflow_confirm'))
        self.assertTrue(event_policies.event_allowed_for_producer('DELIVERY_RESULT', 'delivery_converge'))
        self.assertNotIn('DELIVERY_DEFERRED_ACCEPTED', event_policies.EVENT_POLICIES)
        self.assertFalse(event_policies.event_allowed_for_producer('WORKFLOW_CONFIRMATION', 'event_add'))
        self.assertFalse(event_policies.event_allowed_for_producer('DELIVERY_RESULT', 'event_add'))

    def test_user_each_stage_preference_gates_boundary_and_emits_short_wake_prompt(self):
        task_id = 'TASK-V522-PREF'
        task_dir = self.create_task(task_id, 'L1')
        rc, out, err = run(['workflow', 'preference', '--set', 'each_stage', '--json'])
        self.assertEqual(rc, 0, (out, err))
        pref = self.user_root / 'preferences.yaml'
        self.assertTrue(pref.is_file())

        first = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(first['next_stage'], 'requirement')
        self.assertEqual(first['recommended_action'], 'dispatch_role')
        self.checkpoint(task_id, task_dir, 'tp-product-manager', 'requirement')

        pending = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(pending['recommended_action'], 'await_confirmation')
        self.assertIsNone(pending['skill_path'])
        self.assertEqual(pending['confirmation_reason'], 'EACH_STAGE_POLICY')
        self.assertTrue(pending['confirmation_binding']['route_digest'])

        dispatched = self.confirm_each_stage(task_id, task_dir)
        self.assertEqual(dispatched['recommended_action'], 'dispatch_role')
        self.assertEqual(dispatched['role_id'], 'tp-software-architect')
        self.assertIn(task_id, dispatched['wake_prompt'])
        self.assertIn('workflow next', dispatched['wake_prompt'])
        self.assertLess(len(dispatched['wake_prompt']), 500)

        self.checkpoint(task_id, task_dir, 'tp-software-architect', 'architecture', 'architecture v1')
        self.assertEqual(orchestration.resolve_route(task_id, db_path=str(self.db))['recommended_action'], 'await_confirmation')
        self.confirm_each_stage(task_id, task_dir)
        # A new source fact creates a new binding; the old confirmation cannot be reused.
        self.checkpoint(task_id, task_dir, 'tp-software-architect', 'architecture', 'architecture v2')
        stale = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(stale['recommended_action'], 'await_confirmation')
        self.assertIsNone(stale['skill_path'])

    def test_material_gate_remains_stronger_than_each_stage_confirmation(self):
        task_id = 'TASK-V522-MATERIAL'
        task_dir = self.create_task(task_id, 'L2')
        self.checkpoint(task_id, task_dir, 'tp-product-manager', 'requirement')
        self.checkpoint(task_id, task_dir, 'tp-software-architect', 'architecture')
        # each-stage ordinary confirmation is needed before planning; satisfy it first.
        self.confirm_each_stage(task_id, task_dir)
        self.checkpoint(task_id, task_dir, 'tp-tech-lead', 'planning')
        pending = orchestration.resolve_route(task_id, db_path=str(self.db), confirmation_policy='each_stage')
        self.assertEqual(pending['confirmation_reason'], 'MATERIAL_ARCHITECTURE_TO_IMPLEMENTATION')
        self.assertEqual(pending['recommended_action'], 'await_confirmation')
        self.assertIsNone(pending['skill_path'])
        # Legacy public DECISION marker must no longer satisfy the material gate.
        self.add_legacy_material_decision_marker(task_id)
        still_pending = orchestration.resolve_route(task_id, db_path=str(self.db), confirmation_policy='each_stage')
        self.assertEqual(still_pending['confirmation_reason'], 'MATERIAL_ARCHITECTURE_TO_IMPLEMENTATION')
        self.assertIsNone(still_pending['skill_path'])
        rc, out, err = self.call(
            'workflow', 'confirm', '--task', task_id, '--task-dir', str(task_dir),
            '--confirmation-policy', 'each_stage', '--json',
        )
        self.assertEqual(rc, 0, (out, err))
        dispatched = json.loads(out)
        self.assertEqual(dispatched['recommended_action'], 'dispatch_role')
        self.assertEqual(dispatched['role_id'], 'tp-development-engineer')
        self.assertIn('wake_prompt', dispatched)
        material_events = [dict(x) for x in self.events(task_id) if x['event_type'] == 'WORKFLOW_CONFIRMATION']
        self.assertEqual(json.loads(material_events[-1]['detail_json'])['confirmation_kind'], 'material')

    def test_json_workflow_confirm_keeps_stdout_machine_parseable_and_card_display_on_stderr(self):
        task_id = 'TASK-V527-CARD-JSON'
        task_dir = self.create_task(task_id, 'L1')
        self.checkpoint(task_id, task_dir, 'tp-product-manager', 'requirement')

        rc, out, err = self.call(
            'workflow', 'confirm', '--task', task_id, '--task-dir', str(task_dir),
            '--confirmation-policy', 'each_stage', '--json', refresh_card=True,
        )

        self.assertEqual(rc, 0, (out, err))
        payload = json.loads(out)
        self.assertEqual(payload['recommended_action'], 'dispatch_role')
        self.assertNotIn('CARD_DISPLAY:', out)
        self.assertIn('CARD_DISPLAY:', err)

    def test_each_stage_applies_to_verification_rework_review_and_delivery(self):
        task_id = 'TASK-V522-REWORK'
        task_dir = self.create_task(task_id, 'L1')
        self.checkpoint(task_id, task_dir, 'tp-product-manager', 'requirement')
        self.confirm_each_stage(task_id, task_dir)
        self.checkpoint(task_id, task_dir, 'tp-software-architect', 'architecture')
        self.confirm_each_stage(task_id, task_dir)
        self.checkpoint(task_id, task_dir, 'tp-development-engineer', 'development')
        self.confirm_each_stage(task_id, task_dir)
        self.verify(task_id, task_dir, 'NEEDS_FIX')
        rework = orchestration.resolve_route(task_id, db_path=str(self.db), confirmation_policy='each_stage')
        self.assertEqual(rework['next_stage'], 'development')
        self.assertEqual(rework['recommended_action'], 'await_confirmation')
        self.assertIsNone(rework['skill_path'])

        task2 = 'TASK-V522-DELIVERY-BOUNDARY'
        dir2 = self.create_task(task2, 'L2')
        self.prepare_l2_to_verification_pass(task2, dir2)
        review = orchestration.resolve_route(task2, db_path=str(self.db), confirmation_policy='each_stage')
        self.assertEqual(review['next_stage'], 'review')
        self.assertEqual(review['recommended_action'], 'await_confirmation')
        self.confirm_each_stage(task2, dir2)
        self.code_review(task2, dir2, 'PASS')
        delivery = orchestration.resolve_route(task2, db_path=str(self.db), confirmation_policy='each_stage')
        self.assertEqual(delivery['next_stage'], 'delivery')
        self.assertEqual(delivery['recommended_action'], 'await_confirmation')
        self.assertIsNone(delivery['skill_path'])

    def test_plain_delivery_checkpoint_cannot_complete_but_valid_ready_delivery_can(self):
        task_id = 'TASK-V522-DELIVERY'
        task_dir = self.create_task(task_id, 'L2')
        self.prepare_l2_to_verification_pass(task_id, task_dir)
        self.code_review(task_id, task_dir, 'PASS')
        route = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(route['next_stage'], 'delivery')
        self.checkpoint(task_id, task_dir, 'tp-integration-engineer', 'delivery', 'legacy-looking delivery checkpoint')
        still_delivery = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(still_delivery['next_stage'], 'delivery')
        self.assertEqual(still_delivery['recommended_action'], 'dispatch_role')

        rc, out, err = self.call(
            'task', 'complete', '--task', task_id, '--task-dir', str(task_dir),
            '--actor', 'tp-integration-engineer', '--summary', 'must not complete',
        )
        self.assertNotEqual(rc, 0)
        self.assertIn('INTEGRITY_PIPELINE_PENDING', err)

        rc, out, err = self.call(
            'task', 'delivery-converge', '--task', task_id, '--task-dir', str(task_dir),
            '--delivery-status', 'READY',
            '--reason', 'Verified change is ready for integration and no delivery blocker remains.',
        )
        self.assertEqual(rc, 0, (out, err))
        complete_route = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(complete_route['next_stage'], 'complete')
        self.assertEqual(complete_route['recommended_action'], 'task_complete')
        rc, out, err = self.call(
            'task', 'complete', '--task', task_id, '--task-dir', str(task_dir),
            '--actor', 'tp-integration-engineer', '--summary', 'done',
        )
        self.assertEqual(rc, 0, (out, err))


    def test_blocked_delivery_result_prevents_pipeline_completion(self):
        task_id = 'TASK-V522-BLOCKED-DELIVERY'
        task_dir = self.create_task(task_id, 'L2')
        self.prepare_l2_to_verification_pass(task_id, task_dir)
        self.code_review(task_id, task_dir, 'PASS')
        rc, out, err = self.call(
            'task', 'delivery-converge', '--task', task_id, '--task-dir', str(task_dir),
            '--delivery-status', 'BLOCKED',
            '--reason', 'Integration conflict prevents safe delivery of the verified subject.',
            '--blocker-kind', 'INTEGRATION_CONFLICT',
            '--recovery-condition', 'resolve integration conflict and rerun delivery readiness',
            '--responsibility', 'integration engineer resolves the conflict or escalates to human_owner',
        )
        self.assertEqual(rc, 0, (out, err))
        route = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(route['next_stage'], 'delivery')
        rc, out, err = self.call(
            'task', 'complete', '--task', task_id, '--task-dir', str(task_dir),
            '--actor', 'tp-integration-engineer', '--summary', 'must remain pending',
        )
        self.assertNotEqual(rc, 0)
        self.assertIn('INTEGRITY_PIPELINE_PENDING', err)

    def test_l1_existing_flow_does_not_gain_delivery_stage(self):
        task_id = 'TASK-V522-L1-NO-DELIVERY'
        task_dir = self.create_task(task_id, 'L1')
        self.checkpoint(task_id, task_dir, 'tp-product-manager', 'requirement')
        self.checkpoint(task_id, task_dir, 'tp-software-architect', 'architecture')
        self.checkpoint(task_id, task_dir, 'tp-development-engineer', 'development')
        self.verify(task_id, task_dir, 'PASS')
        route = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(route['next_stage'], 'complete')
        self.assertEqual(route['recommended_action'], 'task_complete')

    def test_record_first_checkpoint_and_verification_emit_structured_semantics(self):
        task_id = 'TASK-V527-EVENT-SEMANTICS'
        task_dir = self.create_task(task_id, 'L1')
        self.checkpoint(task_id, task_dir, 'tp-product-manager', 'requirement', summary='contains 0FAIL but completed')
        checkpoint = [dict(x) for x in self.events(task_id) if x['event_type'] == 'FACT'][-1]
        detail = json.loads(checkpoint['detail_json'])
        self.assertEqual(detail['schema'], 'tp-spec.event-semantics/v1')
        self.assertEqual(detail['operation'], 'CHECKPOINT')
        self.assertEqual(detail['result_status'], 'COMPLETED')
        self.assertEqual(detail['producer'], 'record-first')

        self.verify(task_id, task_dir, 'NEEDS_FIX')
        verification = [dict(x) for x in self.events(task_id) if x['event_type'] == 'VERIFICATION_COMPLETED'][-1]
        detail = json.loads(verification['detail_json'])
        self.assertEqual(detail['schema'], 'tp-spec.event-semantics/v1')
        self.assertEqual(detail['operation'], 'VERIFY')
        self.assertEqual(detail['result_status'], 'COMPLETED')
        self.assertEqual(detail['decision'], 'NEEDS_FIX')

    def test_review_and_workflow_confirmation_emit_structured_semantics(self):
        task_id = 'TASK-V527-REVIEW-SEMANTICS'
        task_dir = self.create_task(task_id, 'L1')
        self.checkpoint(task_id, task_dir, 'tp-product-manager', 'requirement')
        self.checkpoint(task_id, task_dir, 'tp-software-architect', 'architecture')
        self.checkpoint(task_id, task_dir, 'tp-development-engineer', 'development')
        self.verify(task_id, task_dir, 'PASS')
        self.code_review(task_id, task_dir, 'BLOCKED')
        review = [dict(x) for x in self.events(task_id) if x['event_type'] == 'REVIEW_COMPLETED'][-1]
        detail = json.loads(review['detail_json'])
        self.assertEqual(detail['schema'], 'tp-spec.event-semantics/v1')
        self.assertEqual(detail['operation'], 'REVIEW')
        self.assertEqual(detail['result_status'], 'BLOCKED')
        self.assertEqual(detail['decision'], 'BLOCKED')

        confirm_id = 'TASK-V527-CONFIRM-SEMANTICS'
        confirm_dir = self.create_task(confirm_id, 'L1')
        rc, out, err = run(['workflow', 'preference', '--set', 'each_stage', '--json'])
        self.assertEqual(rc, 0, (out, err))
        self.checkpoint(confirm_id, confirm_dir, 'tp-product-manager', 'requirement')
        self.confirm_each_stage(confirm_id, confirm_dir)
        event = [dict(x) for x in self.events(confirm_id) if x['event_type'] == 'WORKFLOW_CONFIRMATION'][-1]
        detail = json.loads(event['detail_json'])
        self.assertEqual(detail['schema'], 'tp-spec.event-semantics/v1')
        self.assertEqual(detail['operation'], 'WORKFLOW_CONFIRM')
        self.assertEqual(detail['result_status'], 'COMPLETED')

    def test_work_session_events_are_structured_without_ai_bookkeeping(self):
        task_id = 'TASK-V527-WORK-SEMANTICS'
        self.create_task(task_id, 'L1')
        rc, out, err = self.call('work', 'start', '--task', task_id, '--role', 'tp-development-engineer', '--summary', 'start')
        self.assertEqual(rc, 0, (out, err))
        rc, out, err = self.call('work', 'end', '--task', task_id, '--role', 'tp-development-engineer', '--reason', 'completed', '--summary', 'end')
        self.assertEqual(rc, 0, (out, err))
        events = [dict(x) for x in self.events(task_id)]
        started = [x for x in events if x['event_type'] == 'WORK_SESSION_STARTED'][-1]
        ended = [x for x in events if x['event_type'] == 'WORK_SESSION_ENDED'][-1]
        start_detail = json.loads(started['detail_json'])
        end_detail = json.loads(ended['detail_json'])
        self.assertEqual((start_detail['operation'], start_detail['result_status']), ('START', 'STARTED'))
        self.assertEqual((end_detail['operation'], end_detail['result_status']), ('END', 'COMPLETED'))
        self.assertEqual(start_detail['schema'], 'tp-spec.event-semantics/v1')
        self.assertEqual(end_detail['schema'], 'tp-spec.event-semantics/v1')

    def test_summary_only_verification_does_not_advance_workflow(self):
        task_id = 'TASK-V527-SUMMARY-NOT-FACT'
        task_dir = self.create_task(task_id, 'L1')
        self.checkpoint(task_id, task_dir, 'tp-product-manager', 'requirement')
        self.checkpoint(task_id, task_dir, 'tp-software-architect', 'architecture')
        self.checkpoint(task_id, task_dir, 'tp-development-engineer', 'development')
        conn = dbmod.connect(str(self.db))
        try:
            with dbmod.transactional(conn):
                conn.execute(
                    'INSERT INTO task_event(task_id,event_type,actor_role,summary,detail_json,created_at) VALUES(?,?,?,?,?,?)',
                    (task_id, 'VERIFICATION_COMPLETED', 'tp-test-engineer', 'PASS 17PASS0FAIL', '{}', dbmod.now_iso()),
                )
        finally:
            conn.close()
        route = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(route['next_stage'], 'verification')

    def test_untyped_checkpoint_does_not_complete_but_legacy_record_first_does(self):
        task_id = 'TASK-V527-LEGACY-CHECKPOINT'
        self.create_task(task_id, 'L1')
        conn = dbmod.connect(str(self.db))
        try:
            with dbmod.transactional(conn):
                conn.execute(
                    'INSERT INTO task_event(task_id,event_type,actor_role,summary,detail_json,created_at) VALUES(?,?,?,?,?,?)',
                    (task_id, 'FACT', 'tp-product-manager', 'requirement done', json.dumps({'operation':'CHECKPOINT','phase':'requirement'}), dbmod.now_iso()),
                )
        finally:
            conn.close()
        route = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(route['next_stage'], 'requirement')

        conn = dbmod.connect(str(self.db))
        try:
            with dbmod.transactional(conn):
                conn.execute('DELETE FROM task_event WHERE task_id=?', (task_id,))
                conn.execute(
                    'INSERT INTO task_event(task_id,event_type,actor_role,summary,detail_json,created_at) VALUES(?,?,?,?,?,?)',
                    (task_id, 'FACT', 'tp-product-manager', 'requirement done', json.dumps({'operation':'CHECKPOINT','phase':'requirement','producer':'record-first'}), dbmod.now_iso()),
                )
        finally:
            conn.close()
        route = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertNotEqual(route['next_stage'], 'requirement')

    def test_progress_never_uses_next_step_as_current_step(self):
        task_id = 'TASK-V527-CURRENT-STEP'
        self.create_task(task_id, 'L1')
        progress = orchestration.resolve_progress(task_id, db_path=str(self.db))
        self.assertEqual(progress['current_step'], {})
        self.assertEqual(progress['current_step_source'], 'unresolved')
        self.assertEqual(progress['next_step']['stage'], 'requirement')
        self.assertEqual(progress['next_step_source'], 'workflow_contract')


if __name__ == '__main__':
    unittest.main(verbosity=2)
