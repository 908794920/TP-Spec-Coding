import json
from pathlib import Path

import pytest

from cli import autonomy_integration, context_effectiveness, delivery_contract, record_first
from cli.migrations.v5_2_3.role_map import ROLE_MAP


def _trusted_event(event_type, actor, producer, decision, *, event_id=1, subject="subject"):
    created = "2026-08-18T00:00:00+00:00"
    detail = {
        "transaction_id": "tx-1",
        "producer": producer,
        "schema_version": "5.2.4",
        "task_id": "TASK-1",
        "actor_role": actor,
        "created_at": created,
        "decision": decision,
        "subject_digest": subject,
        "operation": "VERIFY" if event_type == "VERIFICATION_COMPLETED" else None,
    }
    return {
        "id": event_id,
        "task_id": "TASK-1",
        "event_type": event_type,
        "actor_role": actor,
        "created_at": created,
        "workflow_version": "5.2.4",
        "detail_json": json.dumps(detail),
    }


def test_record_first_verify_uses_test_engineer_actor(tmp_path):
    with pytest.raises(ValueError, match="task-dir not found"):
        record_first.verify(
            task_id="TASK-1", task_dir=str(tmp_path / "missing"), actor="tp-test-engineer",
            decision="PASS", summary="verified", evidence=[]
        )
    old_verify_actor = next(k for k, v in ROLE_MAP.items() if v == "tp-test-engineer")
    with pytest.raises(ValueError, match="technical verification must be recorded by tp-test-engineer"):
        task_dir = tmp_path / "task"
        task_dir.mkdir()
        record_first.verify(
            task_id="TASK-1", task_dir=str(task_dir), actor=old_verify_actor,
            decision="PASS", summary="verified", evidence=[]
        )


def test_context_effectiveness_trusts_test_engineer_not_old_actor():
    new = _trusted_event("VERIFICATION_COMPLETED", "tp-test-engineer", "record-first", "PASS")
    old_actor = next(k for k, v in ROLE_MAP.items() if v == "tp-test-engineer")
    old = _trusted_event("VERIFICATION_COMPLETED", old_actor, "record-first", "PASS")
    assert context_effectiveness._trusted_verification_decision(new) == "PASS"
    assert context_effectiveness._trusted_verification_decision(old) == ""


def test_delivery_contract_binds_test_and_integration_roles():
    verification = _trusted_event("VERIFICATION_COMPLETED", "tp-test-engineer", "record-first", "PASS", event_id=11)
    delivery = _trusted_event("DELIVERY_RESULT", "tp-integration-engineer", "delivery_converge", "PASS", event_id=12)
    detail = json.loads(delivery["detail_json"])
    detail.update({
        "delivery_status": "READY",
        "reason": "verified change is ready for integration",
        "verification_event_id": 11,
        "verification_subject_digest": "subject",
        "knowledge_handoff": {"task_id": "TASK-1", "verification_event_id": 11},
    })
    delivery["detail_json"] = json.dumps(detail)
    found = delivery_contract.find_delivery_completion_event(
        [verification, delivery], verification_event=verification, current_subject_digest="subject"
    )
    assert found is delivery


def test_autonomy_integration_verification_actor_is_formal_test_engineer(monkeypatch, tmp_path):
    auto_root = tmp_path / "auto"
    evidence_root = auto_root / "integrations" / "INT-1" / "evidence"
    evidence_root.mkdir(parents=True)
    ev = evidence_root / "test.txt"
    ev.write_text("pass", encoding="utf-8")
    data = {"integration_id": "INT-1", "verification": {}}
    monkeypatch.setattr(autonomy_integration, "_profile_root", lambda profile_id: ({}, auto_root, tmp_path))
    monkeypatch.setattr(autonomy_integration, "load_integration", lambda profile_id, integration_id: dict(data))
    monkeypatch.setattr(autonomy_integration, "_root", lambda root, integration_id: root / "integrations" / integration_id)
    monkeypatch.setattr(autonomy_integration, "_save", lambda root, payload: payload)
    out = autonomy_integration.record_verification("P", "INT-1", decision="PASS", evidence=[str(ev)])
    assert out["verification"]["actor"] == "tp-test-engineer"
