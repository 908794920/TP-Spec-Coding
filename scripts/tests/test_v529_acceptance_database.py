# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from cli import yaml_checks
from scripts.tests.runtime_testutil import build_task, run

TASK_ID = "TASK-V529-AC-DB"


def _git_baseline(task_dir: str) -> Path:
    root = Path(task_dir).parents[2]
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    marker = root / "README.md"
    marker.write_text("baseline\n", encoding="utf-8", newline="\n")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
    return root


def _write_acceptance(task_dir: str, verdict: str, *, evidence: str = "") -> None:
    path = Path(task_dir) / "acceptance.md"
    path.write_text(
        "# 验收条件与证据矩阵\n\n"
        "| 编号 | 验收条件 | 来源 | 风险等级 | 验证方式 | 证据路径 | 见证等级 | 结论 |\n"
        "|---|---|---|---|---|---|---|---|\n"
        f"| AC-01 | 保存接口返回成功 | task.md | L0 | 自动测试 | {evidence} | verification | {verdict} |\n\n"
        "```yaml\n"
        "page_verification:\n"
        "  mode: NOT_REQUIRED\n"
        "  human_witness: pending\n"
        "  witness_evidence: \"\"\n"
        "deferred_acceptance: []\n"
        "owner_waivers: []\n"
        "database_operations: []\n"
        "```\n",
        encoding="utf-8",
        newline="\n",
    )


def _development(task_dir: str, db_path: str, task_id: str = TASK_ID) -> None:
    _git_baseline(task_dir)
    rc, out, err = run([
        "task", "checkpoint", "--task", task_id, "--task-dir", task_dir, "--db", db_path,
        "--actor", "tp-development-engineer", "--phase", "development", "--summary", "implemented",
    ])
    assert rc == 0, (out, err)


def _complete(task_dir: str, db_path: str, task_id: str = TASK_ID):
    return run([
        "task", "complete", "--task", task_id, "--task-dir", task_dir, "--db", db_path,
        "--actor", "tp-development-engineer", "--summary", "done",
    ])


def test_completion_rejects_pending_acceptance():
    work = Path(tempfile.mkdtemp(prefix="v529-ac-pending-"))
    try:
        task_dir, db_path = build_task(work, task_id=TASK_ID, risk="L0", flow="L0")
        _write_acceptance(task_dir, "PENDING")
        _development(task_dir, db_path)
        rc, out, err = _complete(task_dir, db_path)
        assert rc != 0
        assert "PENDING/BLOCKED" in out + err
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_completion_rejects_blocked_acceptance():
    work = Path(tempfile.mkdtemp(prefix="v529-ac-blocked-"))
    try:
        task_dir, db_path = build_task(work, task_id=TASK_ID, risk="L0", flow="L0")
        _write_acceptance(task_dir, "BLOCKED")
        _development(task_dir, db_path)
        rc, out, err = _complete(task_dir, db_path)
        assert rc != 0
        assert "PENDING/BLOCKED" in out + err
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_trusted_defer_allows_completion_without_rewriting_pass():
    work = Path(tempfile.mkdtemp(prefix="v529-ac-defer-"))
    try:
        task_dir, db_path = build_task(work, task_id=TASK_ID, risk="L0", flow="L0")
        _write_acceptance(task_dir, "PENDING")
        _development(task_dir, db_path)
        rc, out, err = run([
            "task", "acceptance-override", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "human_owner", "--mode", "defer", "--ac", "AC-01",
            "--reason", "目标环境稍后验收", "--residual-risk", "尚未在目标环境执行",
            "--reverify-owner", "tp-test-engineer", "--trigger", "目标环境可用",
        ])
        assert rc == 0, (out, err)
        rc, out, err = _complete(task_dir, db_path)
        assert rc == 0, (out, err)
        assert "DEFERRED_ACCEPTED" in (Path(task_dir) / "acceptance.md").read_text(encoding="utf-8")
        assert "| PASS |" not in (Path(task_dir) / "acceptance.md").read_text(encoding="utf-8")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_owner_waive_allows_completion_without_rewriting_pass():
    work = Path(tempfile.mkdtemp(prefix="v529-ac-waive-"))
    try:
        task_dir, db_path = build_task(work, task_id=TASK_ID, risk="L0", flow="L0")
        _write_acceptance(task_dir, "PENDING")
        _development(task_dir, db_path)
        rc, out, err = run([
            "task", "acceptance-override", "--task", TASK_ID, "--task-dir", task_dir, "--db", db_path,
            "--actor", "human_owner", "--mode", "waive", "--ac", "AC-01",
            "--reason", "明确接受本项不执行", "--residual-risk", "该场景未做最终验证",
        ])
        assert rc == 0, (out, err)
        rc, out, err = _complete(task_dir, db_path)
        assert rc == 0, (out, err)
        acc = (Path(task_dir) / "acceptance.md").read_text(encoding="utf-8")
        assert "OWNER_WAIVED" in acc
        assert "| PASS |" not in acc
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _database_acceptance_text(*, dml_status: str = "EXECUTED", authorized_by: str = "human_owner", evidence: str = "evidence/sql/db-01-result.md") -> str:
    return f'''# 验收条件与证据矩阵

| 编号 | 验收条件 | 来源 | 风险等级 | 验证方式 | 证据路径 | 见证等级 | 结论 |
|---|---|---|---|---|---|---|---|
| AC-01 | 开发库数据更新成功 | task.md | L2 | SQL 回读 | evidence/sql/db-01-result.md | verification | PASS |
| AC-02 | 目标库结构升级 | task.md | L2 | DDL 执行 |  | human | DEFERRED_ACCEPTED |

```yaml
deferred_acceptance:
- ac: AC-02
  recorded_at: '2026-08-29T10:00:00+08:00'
  residual_risk: 目标库尚未执行 DDL
  reverify_owner: tp-database-engineer
  trigger: 目标环境维护窗口
owner_waivers: []
database_operations:
- id: DB-01
  type: DML
  acceptance_refs: [AC-01]
  environment: development
  status: {dml_status}
  authorized_by: {authorized_by!r}
  artifact_ref: evidence/sql/db-01-statement.sql
  execution_evidence: {evidence!r}
  expected_result: 更新 1 行并回读一致
  rollback_or_cleanup: evidence/sql/db-01-rollback.md
  residual_risk: ''
- id: DB-02
  type: DDL
  acceptance_refs: [AC-02]
  environment: target
  status: NOT_EXECUTED
  authorized_by: ''
  artifact_ref: sql/mysql/upgrade.sql
  execution_evidence: ''
  expected_result: 创建目标表结构
  rollback_or_cleanup: sql/mysql/rollback.sql
  residual_risk: 需在目标环境单独授权执行
```
'''


def test_database_operations_support_executed_dml_and_unexecuted_ddl():
    result = yaml_checks.check_acceptance_yaml(_database_acceptance_text(), enforce_completion=False)
    assert result.ok, result.issues
    assert [x["id"] for x in result.database_operations] == ["DB-01", "DB-02"]
    assert result.database_operations[0]["status"] == "EXECUTED"
    assert result.database_operations[1]["status"] == "NOT_EXECUTED"


def test_executed_dml_requires_owner_authorization_and_evidence():
    missing_auth = yaml_checks.check_acceptance_yaml(
        _database_acceptance_text(authorized_by=""), enforce_completion=False
    )
    assert not missing_auth.ok
    assert any("authorized_by" in x for x in missing_auth.issues)

    missing_evidence = yaml_checks.check_acceptance_yaml(
        _database_acceptance_text(evidence=""), enforce_completion=False
    )
    assert not missing_evidence.ok
    assert any("execution_evidence" in x for x in missing_evidence.issues)


def test_final_result_exposes_acceptance_counts_and_database_statuses():
    work = Path(tempfile.mkdtemp(prefix="v529-final-summary-"))
    try:
        task_dir, db_path = build_task(work, task_id=TASK_ID, risk="L0", flow="L0")
        evidence = Path(task_dir) / "evidence" / "test-result.txt"
        evidence.write_text("pass\n", encoding="utf-8", newline="\n")
        _write_acceptance(task_dir, "PASS", evidence="evidence/test-result.txt")
        _development(task_dir, db_path)
        rc, out, err = _complete(task_dir, db_path)
        assert rc == 0, (out, err)
        final = (Path(task_dir) / "generated" / "final-result.md").read_text(encoding="utf-8")
        assert "PASS：1" in final
        assert "未处置：0" in final
        assert "数据库操作" in final
    finally:
        shutil.rmtree(work, ignore_errors=True)
