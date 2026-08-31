import pytest

from cli import delivery_contract, workflow_records
from cli.knowledge import state as knowledge_state

CHANGE_SET_ID = 'sha256:change-set'


def test_integration_delivery_detail_owns_delivery_not_knowledge():
    detail = workflow_records.build_delivery_detail(
        task_id="TASK-1", transaction_id="tx", flush_id="f",
        created_at="2026-08-18T00:00:00+00:00", schema_version="5.3.0",
        verification_event_id=7, verification_subject_digest="subject",
        verification_change_set_id=CHANGE_SET_ID, review_event_id=8,
        review_change_set_id=CHANGE_SET_ID, change_set_id=CHANGE_SET_ID,
        delivery_status="READY", reason="verified change is ready for integration",
        repo_snapshot={"before_head": "a", "after_head": "b", "merge_commit": "m"},
    )
    assert detail["actor_role"] == "tp-integration-engineer"
    assert detail["delivery_status"] == "READY"
    assert detail["repo_snapshot"]["before_head"] == "a"
    assert "knowledge_disposition" not in detail
    assert "knowledge_handoff" not in detail


def test_delivery_completion_does_not_wait_for_knowledge_disposition():
    detail = {
        "delivery_status": "READY",
        "reason": "verified change is ready for integration",
        "verification_event_id": 7,
        "verification_subject_digest": "subject",
        "verification_change_set_id": CHANGE_SET_ID,
        "review_event_id": 8,
        "review_change_set_id": CHANGE_SET_ID,
        "change_set_id": CHANGE_SET_ID,
    }
    assert delivery_contract.validate_delivery_result(detail) == []
    assert delivery_contract.delivery_result_matches_verification(detail, 7, "subject")


def test_delivery_cli_is_integration_owned_not_knowledge_owned():
    from cli.main import build_parser

    args = build_parser().parse_args([
        "task", "delivery-converge",
        "--task", "TASK-1",
        "--task-dir", "/tmp/task",
        "--delivery-status", "READY",
        "--reason", "verified change is ready for integration",
        "--before-head", "a",
        "--after-head", "b",
    ])
    assert args.delivery_status == "READY"
    assert not hasattr(args, "knowledge_disposition")
    assert not hasattr(args, "knowledge_ref")


def test_knowledge_cli_requires_typed_request_result_inputs():
    from cli.main import build_parser

    args = build_parser().parse_args([
        "knowledge", "task-converge",
        "--task", "TASK-1", "--task-dir", "/tmp/task", "--db", "/tmp/task.db",
        "--workspace-root", "/tmp/project", "--request-event-id", "7",
        "--disposition", "NO_DURABLE_INSIGHT", "--reason-code", "TASK_SPECIFIC_LOW_REUSE_VALUE",
        "--query", "specific durable rule", "--source", "evidence/verify.txt",
    ])
    assert args.request_event_id == 7
    assert args.disposition == "NO_DURABLE_INSIGHT"
    assert not hasattr(args, "handoff_json")


def test_delivery_event_policy_requires_delivery_readiness_not_knowledge_disposition():
    from cli.event_policies import EVENT_POLICIES

    required = set(EVENT_POLICIES["DELIVERY_RESULT"]["required_fields"])
    assert "delivery_status" in required
    assert "knowledge_disposition" not in required
    assert "DELIVERY_DEFERRED_ACCEPTED" not in EVENT_POLICIES
