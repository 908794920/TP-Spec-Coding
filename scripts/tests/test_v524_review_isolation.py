import pytest

from cli import review_cmd


def test_architecture_review_rejects_same_execution_context():
    assert review_cmd._validate_review_isolation(
        design_context_id="ctx-1",
        review_context_id="ctx-1",
        context_policy="isolated",
        subject_digest="abc",
    ) == "formal architecture review requires distinct design and review execution contexts"


def test_architecture_review_accepts_isolated_bound_subject():
    assert review_cmd._validate_review_isolation(
        design_context_id="ctx-design",
        review_context_id="ctx-review",
        context_policy="isolated",
        subject_digest="abc",
    ) is None


def test_architecture_review_requires_subject_binding():
    assert review_cmd._validate_review_isolation(
        design_context_id="ctx-design",
        review_context_id="ctx-review",
        context_policy="isolated",
        subject_digest="",
    ) == "formal architecture review requires a non-empty subject digest"
