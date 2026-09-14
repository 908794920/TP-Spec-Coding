# -*- coding: utf-8 -*-
"""Bounded mapping of existing local reports into non-authoritative observations.

No tool is executed and no Verification/Review/owner decision is created here.
Reported subjects and actors remain claims of the source, not current bindings.
Raw traces stay in the explicitly accepted evidence rather than CLI summaries.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

from .evidence import validate_evidence_path

# Parsing is deliberately narrower than opaque artifact collection. This is a
# resource boundary, not a limit on which existing tests a user may execute.
MAX_REPORT_BYTES = 4 * 1024 * 1024
MAX_REPORT_ITEMS = 10000


def _nonnegative(value: Any, *, integer: bool = False, xml: bool = False) -> int | float:
    if xml:
        if not isinstance(value, str) or (integer and not re.fullmatch(r"[0-9]+", value)):
            raise ValueError("missing or invalid numeric report attribute")
        value = int(value) if integer else float(value)
    if type(value) not in ((int,) if integer else (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("report counts/times must be finite non-negative numbers")
    return value


def _text(value: Any, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("missing or oversized report identity")
    if any(ord(char) < 32 for char in value):
        raise ValueError("control characters in report identity")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _junit(text: str) -> dict[str, Any]:
    # Do not let declarations/entities expand before applying resource limits.
    # Only the flat suite layout emitted by pytest is supported in this adapter.
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.IGNORECASE):
        raise ValueError("DTD/entity declarations are not accepted")
    root = ET.fromstring(text)
    if root.tag == "testsuite":
        suites = [root]
        pytest_junit = False
    elif root.tag == "testsuites" and all(child.tag == "testsuite" for child in root):
        suites = list(root)
        # pytest 9 records unittest subTest successes in the suite's `tests`
        # count without emitting one testcase element per subTest.  The
        # producer's explicit root/suite dialect is the only supported case
        # where that declared count cannot be reconstructed from children.
        pytest_junit = root.get("name") == "pytest tests" and all(
            suite.get("name") == "pytest" for suite in suites)
    else:
        raise ValueError("unsupported JUnit root/layout; collect opaque output instead")
    if not suites or len(suites) > MAX_REPORT_ITEMS:
        raise ValueError("missing or excessive JUnit suites")
    if root.get("disabled") not in (None, "0"):
        raise ValueError("unsupported disabled-test accounting")
    totals = dict(tests=0, failures=0, errors=0, skipped=0)
    duration = 0.0
    for suite in suites:
        if suite.get("disabled") not in (None, "0"):
            raise ValueError("unsupported disabled-test accounting")
        if any(child.tag not in {"testcase", "properties", "system-out", "system-err"} for child in suite):
            raise ValueError("unsupported nested JUnit layout")
        counts = {key: _nonnegative(suite.get(key), integer=True, xml=True) for key in totals}
        cases = suite.findall("testcase")
        if counts["tests"] + totals["tests"] > MAX_REPORT_ITEMS:
            raise ValueError("JUnit case count mismatch or item limit exceeded")
        actual = {"failures": 0, "errors": 0, "skipped": 0}
        for case in cases:
            if case.get("status") is not None or case.get("result") is not None:
                raise ValueError("unsupported JUnit case status dialect")
            # Repeated error/failure elements are allowed; never hide them behind
            # a nominal suite count. All diagnostics remain in the raw report.
            for key, tag in (("failures", "failure"), ("errors", "error"), ("skipped", "skipped")):
                actual[key] += len(case.findall(tag))
            if any(child.tag not in {"failure", "error", "skipped", "properties", "system-out", "system-err"} for child in case):
                raise ValueError("unsupported JUnit case result")
        if any(counts[key] != value for key, value in actual.items()):
            raise ValueError("JUnit outcomes disagree with case contents")
        if pytest_junit:
            # Do not invent per-subTest case rows from the suite aggregate.
            # The raw immutable report preserves the producer detail; require
            # only that pytest never reports fewer tests than serialized cases.
            count_is_valid = counts["tests"] >= len(cases)
        else:
            # Other JUnit dialects must retain an exact one-case-per-test
            # count, so a manipulated aggregate cannot be silently accepted.
            count_is_valid = counts["tests"] == len(cases)
        if not count_is_valid:
            raise ValueError("JUnit case count mismatch or item limit exceeded")
        for key in totals:
            totals[key] += counts[key]
        duration += _nonnegative(suite.get("time"), xml=True)
    if root.tag == "testsuites":
        for key, total in totals.items():
            if root.get(key) is not None and _nonnegative(root.get(key), integer=True, xml=True) != total:
                raise ValueError("JUnit root counts disagree with suites")
    if not math.isfinite(duration):
        raise ValueError("JUnit total duration overflow")
    # A partial/empty report is not a full passing test run. Even 'passed' below
    # describes only this report, never the current Task or actual process exit.
    outcome = ("failed" if totals["failures"] or totals["errors"] else
               "not_run" if not totals["tests"] else
               "incomplete" if totals["skipped"] else "passed")
    return {"format": "junit", "reported_result": {
        **totals, "duration_seconds": duration, "suite_count": len(suites), "outcome": outcome,
    }}


def _base_report(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("version") != "1.0.0" or data.get("mode") not in {"Static", "Full"}:
        raise ValueError("unsupported Base report version/mode")
    items = data.get("items")
    if not isinstance(items, list) or not items or len(items) > MAX_REPORT_ITEMS:
        raise ValueError("missing or excessive Base report items")
    passed = _nonnegative(data.get("passed"), integer=True)
    failed = _nonnegative(data.get("failed"), integer=True)
    duration = _nonnegative(data.get("duration"))
    checks = []
    for item in items:
        if not isinstance(item, dict) or item.get("status") not in {"PASS", "FAIL"}:
            raise ValueError("invalid Base check status")
        code = item.get("exit_code")
        if type(code) is not int or (item["status"] == "PASS") != (code == 0):
            raise ValueError("Base check status/exit_code mismatch")
        checks.append({"name": _text(item.get("name")), "status": item["status"],
                       "exit_code": code, "duration_ms": _nonnegative(item.get("duration_ms"))})
    if (passed != sum(c["status"] == "PASS" for c in checks)
            or failed != sum(c["status"] == "FAIL" for c in checks)):
        raise ValueError("Base summary counts disagree with checks")
    preview = sorted(checks, key=lambda check: check["status"] != "FAIL")[:16]
    return {"format": "tp-spec-base-report", "reported_subject": {
        "git_sha": _text(data.get("git_sha")),
        "artifact_contract": _text(data.get("artifact_contract")),
    }, "reported_result": {"mode": data["mode"], "passed": passed, "failed": failed,
        "duration_seconds": duration, "outcome": "failed" if failed else "passed",
        "check_count": len(checks), "checks_truncated": len(checks) > len(preview), "checks": preview}}


def _review_report(data: dict[str, Any], task_id: str) -> dict[str, Any]:
    if data.get("task_id") != task_id:
        raise ValueError("review report belongs to a different Task")
    if data.get("review_kind") not in {"CODE", "IMPLEMENTATION", "ULTRA_REVIEW"} or data.get("actor_role") != "tp-code-reviewer":
        raise ValueError("unsupported review kind/actor")
    decision = data.get("decision")
    if decision not in {"PASS", "NEEDS_FIX", "FAIL", "REVISE", "BLOCKED"}:
        raise ValueError("invalid reported review decision")
    findings = _nonnegative(data.get("findings_count"), integer=True)
    round_no = _nonnegative(data.get("round"), integer=True)
    event_id = _nonnegative(data.get("verification_event_id"), integer=True)
    if not round_no or not event_id or data.get("verification_scope") not in {"full", "technical"}:
        raise ValueError("invalid reported review binding")
    # Deliberately not re-signing or validating a historical review as current.
    # Formal consumers still use the trusted ledger and its original evidence.
    return {"format": "tp-spec-code-review", "reported_actor_role": data["actor_role"],
        "reported_subject": {"task_id": task_id,
            "subject_digest": _text(data.get("subject_digest")),
            "change_set_id": _text(data.get("change_set_id")),
            "verification_event_id": event_id, "verification_scope": data["verification_scope"]},
        "reported_result": {"review_kind": data["review_kind"], "decision": decision,
            "round": round_no, "findings_count": findings,
            "recorded_at": _text(data.get("recorded_at"))}}


def report_text(task_dir: Path, item: dict[str, Any]):
    """Read one bounded, hash-checked accepted copy for parsing or attachment mapping."""
    checked = validate_evidence_path(task_dir, item, require_evidence_dir=True)
    if not checked.ok or checked.sha256 != item.get("sha256"):
        raise ValueError("report evidence missing or changed")
    with (task_dir / checked.path).open("rb") as handle:
        raw = handle.read(MAX_REPORT_BYTES + 1)
    if not raw or len(raw) > MAX_REPORT_BYTES:
        raise ValueError(f"parsed report limit is 1..{MAX_REPORT_BYTES} bytes; use --collect for larger opaque outputs")
    if hashlib.sha256(raw).hexdigest() != checked.sha256:
        raise ValueError("report changed while reading")
    return checked, raw.decode("utf-8-sig")


def read_report(task_dir: Path, item: dict[str, Any], *, task_id: str) -> dict[str, Any]:
    """Read the accepted immutable copy, not an arbitrary path declared by JSON."""
    try:
        checked, text = report_text(task_dir, item)
        if text.lstrip().startswith("<"):
            parsed = _junit(text)
        else:
            data = json.loads(text, object_pairs_hook=_unique_object)
            if not isinstance(data, dict):
                raise ValueError("report root must be an object")
            if data.get("schema") == "tp-spec.code-review-result/v1":
                parsed = _review_report(data, task_id)
            elif "items" in data and "artifact_contract" in data:
                parsed = _base_report(data)
            elif "suites" in data and "config" in data and "stats" in data:
                from .browser_reports import parse_playwright
                parsed = parse_playwright(data)
            else:
                raise ValueError("unsupported report format; use --collect for opaque evidence")
        return {"authority": "observation_only", "source_kind": "external_report",
            "execution_observed_by_cli": False, "command": None, "exit_code": None,
            "reported_actor_role": None, "reported_subject": None,
            "evidence": checked.item, **parsed}
    except (ValueError, TypeError, OSError, OverflowError, RecursionError, ET.ParseError) as exc:
        raise ValueError(f"RESULT_REPORT_INVALID: {exc}") from exc
