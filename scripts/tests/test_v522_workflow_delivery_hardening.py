# -*- coding: utf-8 -*-
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import db as dbmod
from cli import main as climain
from cli import orchestration
from cli import event_policies


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = climain.main(argv)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


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
        return task_dir

    def call(self, *args):
        return run(list(args) + ['--db', str(self.db)])

    def checkpoint(self, task_id: str, task_dir: Path, actor: str, phase: str, summary: str = 'done'):
        rc, out, err = self.call(
            'task', 'checkpoint', '--task', task_id, '--task-dir', str(task_dir),
            '--actor', actor, '--phase', phase, '--summary', summary,
        )
        self.assertEqual(rc, 0, (out, err))

    def verify(self, task_id: str, task_dir: Path, decision: str = 'PASS'):
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

    def prepare_l2_to_verification_pass(self, task_id: str, task_dir: Path):
        self.checkpoint(task_id, task_dir, 'tp-product-manager', 'requirement')
        self.checkpoint(task_id, task_dir, 'tp-software-architect', 'architecture')
        self.checkpoint(task_id, task_dir, 'tp-tech-lead', 'planning')
        rc, out, err = self.call(
            'workflow', 'confirm', '--task', task_id, '--task-dir', str(task_dir), '--json',
        )
        self.assertEqual(rc, 0, (out, err))
        self.checkpoint(task_id, task_dir, 'tp-development-engineer', 'development')
        self.verify(task_id, task_dir, 'PASS')


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

    def test_plain_delivery_checkpoint_cannot_complete_but_valid_no_change_can(self):
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

    def test_new_verification_invalidates_old_delivery_result(self):
        task_id = 'TASK-V522-STALE-DELIVERY'
        task_dir = self.create_task(task_id, 'L2')
        self.prepare_l2_to_verification_pass(task_id, task_dir)
        self.code_review(task_id, task_dir, 'PASS')
        rc, out, err = self.call(
            'task', 'delivery-converge', '--task', task_id, '--task-dir', str(task_dir),
            '--delivery-status', 'READY',
            '--reason', 'Verified change is ready for integration and no delivery blocker remains.',
        )
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual(orchestration.resolve_route(task_id, db_path=str(self.db))['next_stage'], 'complete')
        self.verify(task_id, task_dir, 'PASS')
        stale = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(stale['next_stage'], 'review')
        self.code_review(task_id, task_dir, 'PASS')
        self.assertEqual(orchestration.resolve_route(task_id, db_path=str(self.db))['next_stage'], 'delivery')

    def test_task_scoped_knowledge_deferred_does_not_block_ready_delivery(self):
        task_id = 'TASK-V522-KNOWLEDGE-DEFERRED'
        task_dir = self.create_task(task_id, 'L2')
        self.prepare_l2_to_verification_pass(task_id, task_dir)
        self.code_review(task_id, task_dir, 'PASS')
        rc, out, err = self.call(
            'task', 'delivery-converge', '--task', task_id, '--task-dir', str(task_dir),
            '--delivery-status', 'READY',
            '--reason', 'Verified change is ready for integration and no delivery blocker remains.',
        )
        self.assertEqual(rc, 0, (out, err))
        detail = json.loads([dict(x) for x in self.events(task_id) if x['event_type']=='DELIVERY_RESULT'][-1]['detail_json'])
        handoff = detail['knowledge_handoff']
        handoff['verified_facts'] = ['durable reusable fact']
        rc, out, err = run(['knowledge', 'task-converge', '--handoff-json', json.dumps(handoff)])
        self.assertEqual(rc, 0, (out, err))
        knowledge = json.loads(out)
        self.assertEqual(knowledge['status'], 'DEFERRED')
        self.assertFalse(knowledge['blocks_delivery'])
        self.assertEqual(orchestration.resolve_route(task_id, db_path=str(self.db))['next_stage'], 'complete')

    def test_ready_delivery_handoff_can_finish_with_no_change_without_knowledge_scan(self):
        task_id = 'TASK-V522-KNOWLEDGE-NOCHANGE'
        task_dir = self.create_task(task_id, 'L2')
        self.prepare_l2_to_verification_pass(task_id, task_dir)
        self.code_review(task_id, task_dir, 'PASS')
        rc, out, err = self.call(
            'task', 'delivery-converge', '--task', task_id, '--task-dir', str(task_dir),
            '--delivery-status', 'READY',
            '--reason', 'Verified change is ready for integration and no delivery blocker remains.',
        )
        self.assertEqual(rc, 0, (out, err))
        detail = json.loads([dict(x) for x in self.events(task_id) if x['event_type']=='DELIVERY_RESULT'][-1]['detail_json'])
        rc, out, err = run(['knowledge', 'task-converge', '--handoff-json', json.dumps(detail['knowledge_handoff'])])
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual(json.loads(out)['status'], 'NO_CHANGE')

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


if __name__ == '__main__':
    unittest.main(verbosity=2)
