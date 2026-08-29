# -*- coding: utf-8 -*-
"""Structured event semantics and presentation regression tests."""
from __future__ import annotations

from cli.event_contract import normalize_event_semantics, validate_event_semantics
from cli.event_presentation import resolve_event_presentation


def test_summary_never_overrides_structured_pass_result():
    semantics = normalize_event_semantics(
        "VERIFICATION_COMPLETED",
        {
            "schema": "tp-spec.event-semantics/v1",
            "operation": "VERIFY",
            "decision": "PASS",
            "result_status": "COMPLETED",
            "producer": "record-first",
        },
    )
    presentation = resolve_event_presentation(
        "VERIFICATION_COMPLETED", semantics["decision"], semantics["result_status"]
    )
    assert presentation["reason_label"] == "通过"
    assert presentation["status_class"] == "ok"


def test_untyped_summary_with_fail_words_stays_neutral():
    semantics = normalize_event_semantics("FACT", {})
    presentation = resolve_event_presentation("FACT", semantics["decision"], semantics["result_status"])
    assert semantics["source_kind"] == "legacy_untyped"
    assert semantics["result_status"] == "NOT_RECORDED"
    assert presentation["reason_label"] == "状态未声明"
    assert presentation["status_class"] == "info"


def test_legacy_record_first_checkpoint_is_deterministically_compatible():
    semantics = normalize_event_semantics(
        "FACT",
        {"operation": "CHECKPOINT", "phase": "development", "producer": "record-first"},
    )
    assert semantics["source_kind"] == "legacy_contract"
    assert semantics["result_status"] == "COMPLETED"


def test_plain_fact_cannot_impersonate_completed_checkpoint():
    semantics = normalize_event_semantics(
        "FACT", {"operation": "CHECKPOINT", "phase": "development"}
    )
    assert semantics["source_kind"] == "legacy_untyped"
    assert semantics["result_status"] == "NOT_RECORDED"


def test_blocked_remains_a_controlled_review_decision():
    detail = {
        "schema": "tp-spec.event-semantics/v1",
        "operation": "REVIEW",
        "review_kind": "CODE",
        "decision": "BLOCKED",
        "result_status": "BLOCKED",
        "producer": "review_record",
        "change_set_id": "sha256:fixture-code-review",
        "verification_event_id": "EV-FIXTURE-VERIFY",
    }
    assert validate_event_semantics("REVIEW_COMPLETED", detail) == []
    semantics = normalize_event_semantics("REVIEW_COMPLETED", detail)
    presentation = resolve_event_presentation(
        "REVIEW_COMPLETED", semantics["decision"], semantics["result_status"]
    )
    assert presentation["reason_label"] == "存在阻塞"
    assert presentation["status_class"] == "warn"


def test_unknown_structured_values_remain_visible_and_neutral():
    presentation = resolve_event_presentation("CUSTOM_EVENT", "CUSTOM_STATE", "NOT_RECORDED")
    assert presentation == {
        "event_label": "CUSTOM_EVENT",
        "reason_label": "CUSTOM_STATE",
        "status_class": "info",
        "decision": "CUSTOM_STATE",
        "result_status": "NOT_RECORDED",
    }
