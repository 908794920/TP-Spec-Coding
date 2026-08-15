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
            '--actor', 'tp-verification-engineering', '--decision', decision,
            '--summary', f'verification {decision}',
        ]
        if decision == 'PASS':
            evidence = task_dir / 'evidence' / f'verify-{len(self.events(task_id))}.txt'
            evidence.parent.mkdir(exist_ok=True)
            evidence.write_text('verified\n', encoding='utf-8')
            args += ['--evidence', str(evidence.relative_to(task_dir)).replace('\\', '/')]
        rc, out, err = self.call(*args)
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
        self.checkpoint(task_id, task_dir, 'tp-requirement-analysis', 'requirement')
        self.checkpoint(task_id, task_dir, 'tp-architecture-design', 'architecture')
        rc, out, err = self.call(
            'workflow', 'confirm', '--task', task_id, '--task-dir', str(task_dir), '--json',
        )
        self.assertEqual(rc, 0, (out, err))
        self.checkpoint(task_id, task_dir, 'tp-development-engineering', 'development')
        self.verify(task_id, task_dir, 'PASS')


    def test_new_gate_events_are_trusted_only_from_official_producers(self):
        self.assertTrue(event_policies.event_allowed_for_producer('WORKFLOW_CONFIRMATION', 'workflow_confirm'))
        self.assertTrue(event_policies.event_allowed_for_producer('DELIVERY_RESULT', 'delivery_converge'))
        self.assertTrue(event_policies.event_allowed_for_producer('DELIVERY_DEFERRED_ACCEPTED', 'delivery_deferred_accept'))
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
        self.checkpoint(task_id, task_dir, 'tp-requirement-analysis', 'requirement')

        pending = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(pending['recommended_action'], 'await_confirmation')
        self.assertIsNone(pending['skill_path'])
        self.assertEqual(pending['confirmation_reason'], 'EACH_STAGE_POLICY')
        self.assertTrue(pending['confirmation_binding']['route_digest'])

        dispatched = self.confirm_each_stage(task_id, task_dir)
        self.assertEqual(dispatched['recommended_action'], 'dispatch_role')
        self.assertEqual(dispatched['role_id'], 'tp-architecture-design')
        self.assertIn(task_id, dispatched['wake_prompt'])
        self.assertIn('workflow next', dispatched['wake_prompt'])
        self.assertLess(len(dispatched['wake_prompt']), 500)

        self.checkpoint(task_id, task_dir, 'tp-architecture-design', 'architecture', 'architecture v1')
        self.assertEqual(orchestration.resolve_route(task_id, db_path=str(self.db))['recommended_action'], 'await_confirmation')
        self.confirm_each_stage(task_id, task_dir)
        # A new source fact creates a new binding; the old confirmation cannot be reused.
        self.checkpoint(task_id, task_dir, 'tp-architecture-design', 'architecture', 'architecture v2')
        stale = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(stale['recommended_action'], 'await_confirmation')
        self.assertIsNone(stale['skill_path'])

    def test_material_gate_remains_stronger_than_each_stage_confirmation(self):
        task_id = 'TASK-V522-MATERIAL'
        task_dir = self.create_task(task_id, 'L2')
        self.checkpoint(task_id, task_dir, 'tp-requirement-analysis', 'requirement')
        self.checkpoint(task_id, task_dir, 'tp-architecture-design', 'architecture')
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
        self.assertEqual(dispatched['role_id'], 'tp-development-engineering')
        self.assertIn('wake_prompt', dispatched)
        material_events = [dict(x) for x in self.events(task_id) if x['event_type'] == 'WORKFLOW_CONFIRMATION']
        self.assertEqual(json.loads(material_events[-1]['detail_json'])['confirmation_kind'], 'material')

    def test_each_stage_applies_to_verification_rework_and_pass_to_delivery(self):
        task_id = 'TASK-V522-REWORK'
        task_dir = self.create_task(task_id, 'L1')
        self.checkpoint(task_id, task_dir, 'tp-requirement-analysis', 'requirement')
        self.confirm_each_stage(task_id, task_dir)
        self.checkpoint(task_id, task_dir, 'tp-architecture-design', 'architecture')
        self.confirm_each_stage(task_id, task_dir)
        self.checkpoint(task_id, task_dir, 'tp-development-engineering', 'development')
        self.confirm_each_stage(task_id, task_dir)
        self.verify(task_id, task_dir, 'NEEDS_FIX')
        rework = orchestration.resolve_route(task_id, db_path=str(self.db), confirmation_policy='each_stage')
        self.assertEqual(rework['next_stage'], 'development')
        self.assertEqual(rework['recommended_action'], 'await_confirmation')
        self.assertIsNone(rework['skill_path'])

        task2 = 'TASK-V522-DELIVERY-BOUNDARY'
        dir2 = self.create_task(task2, 'L2')
        self.prepare_l2_to_verification_pass(task2, dir2)
        delivery = orchestration.resolve_route(task2, db_path=str(self.db), confirmation_policy='each_stage')
        self.assertEqual(delivery['next_stage'], 'delivery')
        self.assertEqual(delivery['recommended_action'], 'await_confirmation')
        self.assertIsNone(delivery['skill_path'])

    def test_plain_delivery_checkpoint_cannot_complete_but_valid_no_change_can(self):
        task_id = 'TASK-V522-DELIVERY'
        task_dir = self.create_task(task_id, 'L2')
        self.prepare_l2_to_verification_pass(task_id, task_dir)
        route = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(route['next_stage'], 'delivery')
        self.checkpoint(task_id, task_dir, 'tp-delivery-convergence', 'delivery', 'legacy-looking delivery checkpoint')
        still_delivery = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(still_delivery['next_stage'], 'delivery')
        self.assertEqual(still_delivery['recommended_action'], 'dispatch_role')

        rc, out, err = self.call(
            'task', 'complete', '--task', task_id, '--task-dir', str(task_dir),
            '--actor', 'tp-delivery-convergence', '--summary', 'must not complete',
        )
        self.assertNotEqual(rc, 0)
        self.assertIn('INTEGRITY_PIPELINE_PENDING', err)

        rc, out, err = self.call(
            'task', 'delivery-converge', '--task', task_id, '--task-dir', str(task_dir),
            '--knowledge-disposition', 'NO_CHANGE',
            '--knowledge-query', 'verified delivery behavior and reusable rule',
            '--reason', 'Targeted project+shared search found no durable Knowledge delta beyond already covered canonical facts.',
        )
        self.assertEqual(rc, 0, (out, err))
        complete_route = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(complete_route['next_stage'], 'complete')
        self.assertEqual(complete_route['recommended_action'], 'task_complete')
        rc, out, err = self.call(
            'task', 'complete', '--task', task_id, '--task-dir', str(task_dir),
            '--actor', 'tp-delivery-convergence', '--summary', 'done',
        )
        self.assertEqual(rc, 0, (out, err))

    def test_new_verification_invalidates_old_delivery_result(self):
        task_id = 'TASK-V522-STALE-DELIVERY'
        task_dir = self.create_task(task_id, 'L2')
        self.prepare_l2_to_verification_pass(task_id, task_dir)
        rc, out, err = self.call(
            'task', 'delivery-converge', '--task', task_id, '--task-dir', str(task_dir),
            '--knowledge-disposition', 'NO_CHANGE', '--knowledge-query', 'current verified implementation durable behavior',
            '--reason', 'Targeted project+shared search found no durable Knowledge delta after the current verified implementation.',
        )
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual(orchestration.resolve_route(task_id, db_path=str(self.db))['next_stage'], 'complete')
        self.verify(task_id, task_dir, 'PASS')
        stale = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(stale['next_stage'], 'delivery')

    def test_deferred_delivery_requires_matching_human_acceptance(self):
        task_id = 'TASK-V522-DEFERRED'
        task_dir = self.create_task(task_id, 'L2')
        self.prepare_l2_to_verification_pass(task_id, task_dir)
        rc, out, err = self.call(
            'task', 'delivery-converge', '--task', task_id, '--task-dir', str(task_dir),
            '--knowledge-disposition', 'DEFERRED',
            '--reason', 'Knowledge Resolver is unavailable, so the required targeted canonical search cannot be completed safely.',
            '--blocker-kind', 'RESOLVER_UNAVAILABLE',
            '--recovery-condition', 'knowledge doctor passes and current project scope resolves without conflict',
            '--responsibility', 'restore the Knowledge Resolver, then rerun delivery convergence',
        )
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual(orchestration.resolve_route(task_id, db_path=str(self.db))['next_stage'], 'delivery')
        rc, out, err = self.call(
            'task', 'delivery-accept-deferred', '--task', task_id, '--task-dir', str(task_dir),
            '--reason', 'Accept this temporary Knowledge deferral until the Resolver is restored; follow-up is required.',
        )
        self.assertEqual(rc, 0, (out, err))
        accepted = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(accepted['next_stage'], 'complete')



    def test_created_delivery_validates_exact_canonical_binding_then_runs_lint_and_index(self):
        task_id = 'TASK-V522-CREATED'
        task_dir = self.create_task(task_id, 'L2')
        self.prepare_l2_to_verification_pass(task_id, task_dir)
        evidence_rel = sorted((task_dir / 'evidence').glob('verify-*.txt'))[-1].relative_to(task_dir).as_posix()
        canonical_rel = '10-projects/demo/30-features/DEMO-FEAT-001-delivery-rule.md'
        canonical = self.knowledge_root / canonical_rel
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_text(
            '---\n'
            'id: DEMO-FEAT-001\n'
            'title: Delivery Rule\n'
            'project: demo\n'
            'kind: feature\n'
            'status: active\n'
            'canonical: true\n'
            'source_refs: []\n'
            'confidence: 0.95\n'
            'last_verified: 2026-08-14\n'
            'evidence_refs:\n'
            f'  - type: task\n    ref: {task_id}\n    locator: {evidence_rel}\n'
            '  - type: code\n    ref: repo/app.py:42\n'
            '---\n\nA verified reusable delivery rule.\n',
            encoding='utf-8',
        )
        rc, out, err = self.call(
            'task', 'delivery-converge', '--task', task_id, '--task-dir', str(task_dir),
            '--knowledge-disposition', 'CREATED', '--knowledge-query', 'delivery rule',
            '--knowledge-ref', 'DEMO-FEAT-001', '--evidence', evidence_rel, '--source-ref', 'repo/app.py:42',
            '--reason', 'Created a canonical reusable rule bound to this Task evidence and the verified source location.',
        )
        self.assertEqual(rc, 0, (out, err))
        events = [dict(x) for x in self.events(task_id)]
        delivery = [x for x in events if x['event_type'] == 'DELIVERY_RESULT'][-1]
        detail = json.loads(delivery['detail_json'])
        self.assertEqual(detail['knowledge_disposition'], 'CREATED')
        self.assertEqual(detail['resolved_knowledge_refs'][0]['path'], canonical_rel)
        self.assertEqual(detail['lint_receipts'][0]['status'], 'PASS')
        self.assertTrue(detail['index_receipts'][0]['fresh'])
        self.assertEqual(orchestration.resolve_route(task_id, db_path=str(self.db))['next_stage'], 'complete')

    def test_stale_deferred_delivery_cannot_be_accepted_after_new_verification(self):
        task_id = 'TASK-V522-STALE-DEFERRED'
        task_dir = self.create_task(task_id, 'L2')
        self.prepare_l2_to_verification_pass(task_id, task_dir)
        rc, out, err = self.call(
            'task', 'delivery-converge', '--task', task_id, '--task-dir', str(task_dir),
            '--knowledge-disposition', 'DEFERRED',
            '--reason', 'Knowledge Resolver ownership needs a human decision before the canonical convergence can proceed safely.',
            '--blocker-kind', 'HUMAN_DECISION',
            '--recovery-condition', 'human_owner resolves canonical ownership and delivery convergence is rerun',
            '--responsibility', 'human_owner selects the canonical owner; delivery reruns against current verification',
        )
        self.assertEqual(rc, 0, (out, err))
        self.verify(task_id, task_dir, 'PASS')
        rc, out, err = self.call(
            'task', 'delivery-accept-deferred', '--task', task_id, '--task-dir', str(task_dir),
            '--reason', 'Do not accept a deferral that was bound to the previous verification event.',
        )
        self.assertNotEqual(rc, 0)
        self.assertIn('stale against the current Verification PASS', err)

    def test_blocked_delivery_result_prevents_pipeline_completion(self):
        task_id = 'TASK-V522-BLOCKED-DELIVERY'
        task_dir = self.create_task(task_id, 'L2')
        self.prepare_l2_to_verification_pass(task_id, task_dir)
        rc, out, err = self.call(
            'task', 'delivery-converge', '--task', task_id, '--task-dir', str(task_dir),
            '--knowledge-disposition', 'BLOCKED',
            '--reason', 'Canonical ownership conflict prevents safe merge and no human_owner deferral has been accepted.',
        )
        self.assertEqual(rc, 0, (out, err))
        route = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(route['next_stage'], 'delivery')
        rc, out, err = self.call(
            'task', 'complete', '--task', task_id, '--task-dir', str(task_dir),
            '--actor', 'tp-delivery-convergence', '--summary', 'must remain pending',
        )
        self.assertNotEqual(rc, 0)
        self.assertIn('INTEGRITY_PIPELINE_PENDING', err)

    def test_l1_existing_flow_does_not_gain_delivery_stage(self):
        task_id = 'TASK-V522-L1-NO-DELIVERY'
        task_dir = self.create_task(task_id, 'L1')
        self.checkpoint(task_id, task_dir, 'tp-requirement-analysis', 'requirement')
        self.checkpoint(task_id, task_dir, 'tp-architecture-design', 'architecture')
        self.checkpoint(task_id, task_dir, 'tp-development-engineering', 'development')
        self.verify(task_id, task_dir, 'PASS')
        route = orchestration.resolve_route(task_id, db_path=str(self.db))
        self.assertEqual(route['next_stage'], 'complete')
        self.assertEqual(route['recommended_action'], 'task_complete')


if __name__ == '__main__':
    unittest.main(verbosity=2)
