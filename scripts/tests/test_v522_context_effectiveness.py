from __future__ import annotations

import contextlib
import io
import json
import tempfile
from pathlib import Path

from cli import db as dbmod
from cli import main as climain
from cli import context_effectiveness


def _make_db() -> tuple[Path, object]:
    root = Path(tempfile.mkdtemp(prefix="v522-context-report-"))
    path = root / "runtime.db"
    conn = dbmod.connect(str(path))
    dbmod.init_schema(conn)
    now = dbmod.now_iso()
    with dbmod.transactional(conn):
        conn.execute(
            "INSERT INTO project(project_id,project_name,root_path,base_version,schema_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("A", "A", str(root / "A"), "5.2.1", 1, now, now),
        )
        conn.execute(
            "INSERT INTO project(project_id,project_name,root_path,base_version,schema_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("B", "B", str(root / "B"), "5.2.1", 1, now, now),
        )
        for task_id, project_id in (("TASK-A1", "A"), ("TASK-A2", "A"), ("TASK-B1", "B")):
            conn.execute(
                "INSERT INTO task(task_id,project_id,title,risk_level,flow_level,current_state,current_stage,owner_role,base_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, project_id, task_id, "L1", "L1", "ACTIVE", "development", "tp-development-engineering", "5.2.1", now, now),
            )
    return path, conn


def _detail(producer: str, operation: str | None, usage: list[dict], **extra):
    data = {"producer": producer, "context_usage": usage, **extra}
    if operation:
        data["operation"] = operation
    return json.dumps(data, ensure_ascii=False)


def _insert_event(conn, *, task_id="TASK-A1", event_type="FACT", detail="{}", actor="tp-development-engineering", created_at=None, to_stage="development"):
    created_at = created_at or dbmod.now_iso()
    with dbmod.transactional(conn):
        cur = conn.execute(
            "INSERT INTO task_event(task_id,event_type,to_stage,actor_role,detail_json,created_at) VALUES(?,?,?,?,?,?)",
            (task_id, event_type, to_stage, actor, detail, created_at),
        )
    return int(cur.lastrowid)


def _usage(source_type, asset_id, stage="retrieved", outcome="unknown", followup="unknown", evidence=None):
    return {
        "source_type": source_type,
        "asset_id": asset_id,
        "stage": stage,
        "outcome": outcome,
        "confidence": "high",
        "source_followup": followup,
        "evidence": list(evidence or []),
    }


def test_fetch_prefilters_project_time_and_event_type():
    path, conn = _make_db()
    try:
        _insert_event(conn, task_id="TASK-A1", detail=_detail("record-first", "CHECKPOINT", [_usage("wiki", "wiki:A/x.md")]))
        _insert_event(conn, task_id="TASK-B1", detail=_detail("record-first", "CHECKPOINT", [_usage("wiki", "wiki:B/x.md")]))
        _insert_event(conn, task_id="TASK-A1", event_type="STATE", detail="{}")
        _insert_event(conn, task_id="TASK-A1", created_at="2020-01-01T00:00:00+08:00", detail=_detail("record-first", "CHECKPOINT", [_usage("wiki", "wiki:A/old.md")]))
        rows = context_effectiveness.fetch_context_event_rows(conn, project_id="A", since_iso="2026-01-01T00:00:00+08:00")
        assert len(rows) == 1
        assert rows[0]["task_id"] == "TASK-A1"
        assert rows[0]["event_type"] == "FACT"
    finally:
        conn.close()
        import shutil; shutil.rmtree(path.parent, ignore_errors=True)


def test_public_fact_cannot_forge_context_usage():
    path, conn = _make_db()
    try:
        forged = _detail("event_add", None, [_usage("wiki", "wiki:A/forged.md", "adopted")])
        trusted = _detail("record-first", "CHECKPOINT", [_usage("wiki", "wiki:A/good.md", "adopted")])
        _insert_event(conn, detail=forged)
        _insert_event(conn, detail=trusted)
        rows = context_effectiveness.fetch_context_event_rows(conn, project_id="A", since_iso="2026-01-01T00:00:00+08:00")
        records = context_effectiveness.context_usage_records(rows)
        assert [x["asset_id"] for x in records] == ["wiki:A/good.md"]
    finally:
        conn.close()
        import shutil; shutil.rmtree(path.parent, ignore_errors=True)


def test_aggregation_counts_adopted_as_retrieved_and_followup_proxies():
    records = [
        {"event_id": 1, "task_id": "TASK-A1", **_usage("wiki", "wiki:A/x.md", "retrieved")},
        {"event_id": 2, "task_id": "TASK-A1", **_usage("wiki", "wiki:A/x.md", "adopted", "success", "targeted", ["tool:read:src/x.py"])},
        {"event_id": 3, "task_id": "TASK-A2", **_usage("wiki", "wiki:A/y.md", "adopted", "stale", "broad", ["tool:search:src/"])},
        {"event_id": 4, "task_id": "TASK-A2", **_usage("memory_project", "memory_project:A#constraints", "adopted")},
    ]
    result = context_effectiveness.aggregate_context_usage(records, [])
    wiki = result["sources"]["wiki"]
    assert wiki["retrieved"] == 3
    assert wiki["adopted"] == 2
    assert wiki["adoption_rate"] == 2 / 3
    assert wiki["effective_proxy"] == {"positive": 1, "negative": 1, "unknown": 1}
    assert result["sources"]["memory_project"]["effective_proxy"]["unknown"] == 1


def test_memory_skill_proxy_uses_event_id_window():
    records = [
        {"event_id": 10, "task_id": "TASK-A1", **_usage("memory_skill", "memory_skill:A/build", "adopted", "success")},
        {"event_id": 20, "task_id": "TASK-A2", **_usage("memory_skill", "memory_skill:A/debug", "adopted", "success")},
        {"event_id": 30, "task_id": "TASK-A2", **_usage("memory_skill", "memory_skill:A/no-pass", "adopted", "success")},
    ]
    events = [
        {"id": 11, "task_id": "TASK-A1", "event_type": "VERIFICATION_COMPLETED", "actor_role": "tp-verification-engineering", "detail_json": json.dumps({"producer": "record-first", "operation": "VERIFY", "decision": "PASS"})},
        {"id": 21, "task_id": "TASK-A2", "event_type": "VERIFICATION_COMPLETED", "actor_role": "tp-verification-engineering", "detail_json": json.dumps({"producer": "record-first", "operation": "VERIFY", "decision": "NEEDS_FIX"})},
        {"id": 22, "task_id": "TASK-A2", "event_type": "REWORK", "actor_role": "tp-development-engineering", "detail_json": "{}"},
        {"id": 23, "task_id": "TASK-A2", "event_type": "VERIFICATION_COMPLETED", "actor_role": "tp-verification-engineering", "detail_json": json.dumps({"producer": "record-first", "operation": "VERIFY", "decision": "PASS"})},
        # Legacy commit producer is intentionally not trusted for P0 proxy.
        {"id": 31, "task_id": "TASK-A2", "event_type": "VERIFICATION_COMPLETED", "actor_role": "tp-verification-engineering", "detail_json": json.dumps({"producer": "commit", "operation": "VERIFY", "decision": "PASS"})},
    ]
    result = context_effectiveness.aggregate_context_usage(records, events)
    by_asset = {x["asset_id"]: x for x in result["assets"]}
    assert by_asset["memory_skill:A/build"]["effective_proxy"]["positive"] == 1
    assert by_asset["memory_skill:A/debug"]["effective_proxy"]["negative"] == 1
    assert by_asset["memory_skill:A/no-pass"]["effective_proxy"]["unknown"] == 1


def test_candidate_rules_are_deterministic():
    records = [
        {"event_id": i, "task_id": "TASK-A1", **_usage("wiki", "wiki:A/never.md", "retrieved")}
        for i in range(1, 4)
    ] + [
        {"event_id": 10, "task_id": "TASK-A1", **_usage("wiki", "wiki:A/broad.md", "adopted", "success", "broad", ["tool:search:src/"])},
        {"event_id": 11, "task_id": "TASK-A2", **_usage("wiki", "wiki:A/broad.md", "adopted", "success", "broad", ["tool:search:src/"])},
        {"event_id": 12, "task_id": "TASK-A2", **_usage("knowledge", "knowledge:STALE", "adopted", "stale")},
    ]
    result = context_effectiveness.aggregate_context_usage(records, [])
    reasons = {(x["asset_id"], x["reason"]) for x in result["candidates"]}
    assert ("wiki:A/never.md", "repeated-never-adopted") in reasons
    assert ("wiki:A/broad.md", "broad-followup") in reasons
    assert ("knowledge:STALE", "stale") in reasons


def test_report_command_is_read_only_and_has_all_source_buckets():
    path, conn = _make_db()
    try:
        _insert_event(conn, detail=_detail("record-first", "CHECKPOINT", [_usage("wiki", "wiki:A/x.md", "adopted")]))
        before = conn.execute("SELECT COUNT(*) AS c FROM task_event").fetchone()["c"]
        conn.close()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = climain.main(["report", "context-effectiveness", "--project", "A", "--days", "30", "--json", "--db", str(path)])
            except SystemExit as exc:
                rc = exc.code if isinstance(exc.code, int) else 1
        assert rc == 0, err.getvalue()
        data = json.loads(out.getvalue())
        assert data["schema"] == "tp-spec.context-effectiveness/v1"
        assert set(data["sources"]) == {"wiki", "knowledge", "memory_project", "memory_skill"}
        conn2 = dbmod.connect(str(path))
        try:
            after = conn2.execute("SELECT COUNT(*) AS c FROM task_event").fetchone()["c"]
        finally:
            conn2.close()
        assert after == before
    finally:
        try: conn.close()
        except Exception: pass
        import shutil; shutil.rmtree(path.parent, ignore_errors=True)


def test_report_text_renders_same_metrics():
    path, conn = _make_db()
    try:
        _insert_event(conn, detail=_detail("record-first", "CHECKPOINT", [_usage("wiki", "wiki:A/x.md", "adopted")]))
        conn.close()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = climain.main(["report", "context-effectiveness", "--project", "A", "--days", "30", "--db", str(path)])
            except SystemExit as exc:
                rc = exc.code if isinstance(exc.code, int) else 1
        assert rc == 0, err.getvalue()
        text = out.getvalue()
        assert "Context Effectiveness: A (30d)" in text
        assert "Wiki" in text
        assert "retrieved: 1" in text
        assert "adopted: 1" in text
        assert "Limitations" in text
    finally:
        try: conn.close()
        except Exception: pass
        import shutil; shutil.rmtree(path.parent, ignore_errors=True)


def test_report_days_must_be_positive():
    path, conn = _make_db(); conn.close()
    try:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = climain.main(["report", "context-effectiveness", "--project", "A", "--days", "0", "--json", "--db", str(path)])
            except SystemExit as exc:
                rc = exc.code if isinstance(exc.code, int) else 1
        assert rc != 0
    finally:
        import shutil; shutil.rmtree(path.parent, ignore_errors=True)
