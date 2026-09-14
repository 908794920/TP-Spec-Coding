"""v5.3.3 Graphify M2 No-Go release-boundary contracts."""
from __future__ import annotations

import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
DECISION = BASE / "docs" / "decisions" / "V531_GRAPHIFY_PROVIDER_NO_GO.md"
GRAPHIFY_IMPORT = re.compile(r"(?m)^\s*(?:from|import)\s+graphify(?:\.|\s|$)")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_m2_no_go_decision_is_explicit_and_traceable():
    assert DECISION.is_file()
    text = _read(DECISION)
    for token in (
        "Decision: NO_GO",
        "graphifyy==0.9.53",
        "33362d969292b57eda82f3fbd9eb5f3f5bc9bbc2",
        "assert_valid",
        "dangling endpoint",
        "retentionpolicy",
        "AC-SPIKE-003",
        "FR-SPIKE-008",
        "Source Graph v1: NOT_IMPLEMENTED",
        "Requirement Frontier",
    ):
        assert token in text, token
    assert "13 missing required edges are independent failures" not in text


def test_no_go_keeps_graphify_out_of_product_dependencies_and_python_imports():
    for rel in ("requirements.txt", "requirements-dev.txt"):
        lines = [line.strip().lower() for line in _read(BASE / rel).splitlines()]
        assert not any(line.startswith("graphify") for line in lines), rel

    offenders: list[str] = []
    for path in BASE.rglob("*.py"):
        if ".git" in path.parts or ".worktrees" in path.parts:
            continue
        if GRAPHIFY_IMPORT.search(_read(path)):
            offenders.append(path.relative_to(BASE).as_posix())
    assert offenders == []


def test_release_notes_record_no_go_without_claiming_source_graph_delivery():
    changelog = _read(BASE / "CHANGELOG.md")
    notices = _read(BASE / "THIRD_PARTY_NOTICES.md")
    for token in ("Graphify Provider Spike", "No-Go", "Requirement Frontier"):
        assert token in changelog, token
    for token in ("Graphify", "graphifyy==0.9.53", "not a runtime dependency", "not vendored"):
        assert token in notices, token
    combined = changelog + "\n" + notices
    for forbidden in ("Source Graph v1 implemented", "Source Graph v1 已实现", "Graphify runtime dependency"):
        assert forbidden not in combined
