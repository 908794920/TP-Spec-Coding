from cli import delivery_contract, workflow_records
from cli.knowledge import state as knowledge_state


def test_integration_delivery_detail_owns_delivery_not_knowledge():
    detail = workflow_records.build_delivery_detail(
        task_id="TASK-1", transaction_id="tx", flush_id="f",
        created_at="2026-08-18T00:00:00+00:00", schema_version="5.2.4",
        verification_event_id=7, verification_subject_digest="subject",
        delivery_status="READY", reason="verified change is ready for integration",
        repo_snapshot={"before_head": "a", "after_head": "b", "merge_commit": "m"},
        knowledge_handoff={"task_id": "TASK-1", "verification_event_id": 7},
    )
    assert detail["actor_role"] == "tp-integration-engineer"
    assert detail["delivery_status"] == "READY"
    assert detail["repo_snapshot"]["before_head"] == "a"
    assert "knowledge_disposition" not in detail
    assert detail["knowledge_handoff"]["task_id"] == "TASK-1"


def test_delivery_completion_does_not_wait_for_knowledge_disposition():
    detail = {
        "delivery_status": "READY",
        "reason": "verified change is ready for integration",
        "verification_event_id": 7,
        "verification_subject_digest": "subject",
    }
    assert delivery_contract.validate_delivery_result(detail) == []
    assert delivery_contract.delivery_result_matches_verification(detail, 7, "subject")


def test_task_scoped_knowledge_no_change_is_valid_fast_path():
    result = knowledge_state.task_scoped_convergence({
        "task_id": "TASK-1",
        "verified_facts": [],
        "reusable_findings": [],
    })
    assert result["status"] == "NO_CHANGE"
    assert result["blocks_delivery"] is False


def test_task_scoped_knowledge_handoff_requires_task_identity():
    try:
        knowledge_state.task_scoped_convergence({"verified_facts": ["x"]})
    except ValueError as exc:
        assert "task_id" in str(exc)
    else:
        raise AssertionError("missing task_id must fail")


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


def test_knowledge_cli_accepts_compact_task_handoff_without_workspace_scan():
    from cli.main import build_parser

    args = build_parser().parse_args([
        "knowledge", "task-converge",
        "--handoff-json", '{"task_id":"TASK-1","verified_facts":[]}',
    ])
    assert args.handoff_json.startswith("{")


def test_delivery_event_policy_requires_delivery_readiness_not_knowledge_disposition():
    from cli.event_policies import EVENT_POLICIES

    required = set(EVENT_POLICIES["DELIVERY_RESULT"]["required_fields"])
    assert "delivery_status" in required
    assert "knowledge_disposition" not in required
    assert "DELIVERY_DEFERRED_ACCEPTED" not in EVENT_POLICIES
