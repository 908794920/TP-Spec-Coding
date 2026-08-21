from __future__ import annotations

import json
import tempfile
from pathlib import Path

from cli import db as dbmod
from cli import orchestration, record_first, risk_signals
from cli.version import active_version


def _seed_workspace(root: Path, *, risk: str = "L2", flow: str = "L2") -> tuple[str, Path]:
    task_id = "TASK-RISK-FLOOR"
    task_dir = root / ".tp-spec" / "tasks" / task_id
    task_dir.mkdir(parents=True)
    (task_dir / "task.md").write_text(
        "---\nartifact: task\ntask_id: TASK-RISK-FLOOR\nartifact_contract:\n  version: \"5.2.6\"\n---\n\n"
        "目标：仅流程内相关人员可以查看原始身份证照片，非流程内人员不下发原图并显示无权限查看。\n",
        encoding="utf-8",
    )
    (task_dir / "status.yaml").write_text("placeholder\n", encoding="utf-8")
    (task_dir / "events.jsonl").write_text("", encoding="utf-8")
    db_path = root / ".tp-spec" / "db" / "runtime.db"
    db_path.parent.mkdir(parents=True)
    conn = dbmod.connect(str(db_path))
    dbmod.init_schema(conn)
    now = dbmod.now_iso()
    with dbmod.transactional(conn):
        conn.execute(
            "INSERT INTO project(project_id,project_name,root_path,base_version,schema_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("p-risk", "p-risk", str(root), active_version(), 1, now, now),
        )
        conn.execute(
            "INSERT INTO task(task_id,project_id,title,risk_level,flow_level,current_state,current_stage,owner_role,base_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, "p-risk", "敏感信息可见性", risk, flow, "NEW", "intake", "tp-product-manager", active_version(), now, now),
        )
    conn.close()
    return str(db_path), task_dir


def test_sensitive_access_control_is_machine_classified_as_l3_floor():
    result = risk_signals.scan_texts([
        "仅申请人可查看原始信息，非流程内人员不下发原图并显示无权限查看。"
    ])
    assert result["floor"] == "L3"
    assert "SENSITIVE_ACCESS_CONTROL" in result["signals"]


def test_orchestrator_raises_effective_level_from_formal_task_artifacts_without_writing_runtime():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "workspace"
        db, _task_dir = _seed_workspace(root, risk="L1", flow="L1")
        before = Path(db).read_bytes()
        route = orchestration.resolve_route("TASK-RISK-FLOOR", db_path=db)
        after = Path(db).read_bytes()
        assert route["effective_level"] == "L3"
        assert "SENSITIVE_ACCESS_CONTROL" in route["risk_escalation_signals"]
        assert before == after


def test_architecture_checkpoint_persists_security_risk_escalation_under_professional_actor():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "workspace"
        db, task_dir = _seed_workspace(root, risk="L2", flow="L2")
        result = record_first.checkpoint(
            task_id="TASK-RISK-FLOOR",
            task_dir=str(task_dir),
            actor="tp-software-architect",
            phase="architecture",
            summary="security design complete",
            db=db,
        )
        assert result["risk_level"] == "L3"
        conn = dbmod.connect(db)
        try:
            task = conn.execute("SELECT risk_level,owner_role FROM task WHERE task_id='TASK-RISK-FLOOR'").fetchone()
            fact = conn.execute(
                "SELECT actor_role,detail_json FROM task_event WHERE task_id='TASK-RISK-FLOOR' AND event_type='FACT' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        assert task["risk_level"] == "L3"
        assert task["owner_role"] == "tp-software-architect"
        assert fact["actor_role"] == "tp-software-architect"
        detail = json.loads(fact["detail_json"])
        assert detail["risk_escalation"]["from"] == "L2"
        assert detail["risk_escalation"]["to"] == "L3"
        assert "SENSITIVE_ACCESS_CONTROL" in detail["risk_escalation"]["signals"]


def test_negated_technical_risk_terms_do_not_pollute_signals_but_sensitive_access_still_escalates():
    result = risk_signals.scan_texts([
        "无 DDL、无新表、无接口契约变更、无定时任务。仅申请人可查看原始信息，非流程内人员不下发原图。",
        "不改角色/授权模型、无 DDL、可回滚。",
    ])
    assert result["floor"] == "L3"
    assert "SENSITIVE_ACCESS_CONTROL" in result["signals"]
    assert "DDL" not in result["signals"]
    assert "SCHEDULED_JOB" not in result["signals"]


def test_governed_security_change_has_l3_floor():
    result = risk_signals.scan_texts(["本次修改安全策略并调整脱敏规则。"])
    assert result["floor"] == "L3"
    assert "SECURITY" in result["signals"]


def test_default_acceptance_template_boilerplate_does_not_raise_risk_floor():
    with tempfile.TemporaryDirectory() as td:
        task_dir = Path(td)
        template = Path(__file__).parents[2] / "templates" / active_version() / "acceptance.md"
        (task_dir / "acceptance.md").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        result = risk_signals.scan_task_artifacts(task_dir)
        assert result["floor"] is None
        assert "DDL" not in result["signals"]
        assert "DML" not in result["signals"]


def test_actual_database_action_in_acceptance_still_raises_l2_floor():
    with tempfile.TemporaryDirectory() as td:
        task_dir = Path(td)
        (task_dir / "acceptance.md").write_text(
            "```yaml\ndatabase_verification:\n  action: DML # selected action\n```\n",
            encoding="utf-8",
        )
        result = risk_signals.scan_task_artifacts(task_dir)
        assert result["floor"] == "L2"
        assert "DML" in result["signals"]
