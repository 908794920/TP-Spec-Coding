-- TP-Spec-Coding V5.0 initial schema (schema_version = 1)
-- 账本结构定义；历史升级计划已归档，不作为运行时依赖。
-- 5 表 + 8 索引；连接时还需执行 PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_meta (
  schema_version INTEGER NOT NULL,
  applied_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project (
  project_id     TEXT PRIMARY KEY,
  project_name   TEXT,
  root_path      TEXT,
  base_version   TEXT,
  schema_version INTEGER,
  created_at     TEXT,
  updated_at     TEXT
);

CREATE TABLE IF NOT EXISTS task (
  task_id       TEXT PRIMARY KEY,
  project_id    TEXT NOT NULL,
  title         TEXT,
  risk_level    TEXT,
  flow_level    TEXT,
  current_state TEXT,
  current_stage TEXT,
  owner_role    TEXT,
  owner_agent   TEXT,
  priority      TEXT,
  base_version  TEXT,
  created_at    TEXT,
  updated_at    TEXT,
  completed_at  TEXT,
  FOREIGN KEY(project_id) REFERENCES project(project_id)
);

CREATE TABLE IF NOT EXISTS task_event (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id          TEXT NOT NULL,
  event_type       TEXT NOT NULL,
  from_state       TEXT,
  to_state         TEXT,
  from_stage       TEXT,
  to_stage         TEXT,
  actor_role       TEXT,
  actor_agent      TEXT,
  model_used       TEXT,
  tokens_input     INTEGER,
  tokens_output    INTEGER,
  work_item_id     TEXT,
  reason_code      TEXT,
  summary          TEXT,
  detail_json      TEXT,
  evidence_path    TEXT,
  workflow_version TEXT,
  created_at       TEXT NOT NULL,
  FOREIGN KEY(task_id) REFERENCES task(task_id)
);

CREATE TABLE IF NOT EXISTS work_item (
  item_id              TEXT PRIMARY KEY,
  task_id              TEXT NOT NULL,
  title                TEXT,
  status               TEXT,
  owner_role           TEXT,
  owner_agent          TEXT,
  depends_on_json      TEXT,
  allowed_paths_json   TEXT,
  acceptance_refs_json TEXT,
  created_at           TEXT,
  updated_at           TEXT,
  FOREIGN KEY(task_id) REFERENCES task(task_id)
);

CREATE TABLE IF NOT EXISTS config (
  key         TEXT NOT NULL,
  value_json  TEXT,
  scope       TEXT NOT NULL,
  scope_id    TEXT,
  description TEXT,
  updated_at  TEXT,
  PRIMARY KEY (key, scope, scope_id)
);

CREATE INDEX IF NOT EXISTS idx_task_project    ON task(project_id);
CREATE INDEX IF NOT EXISTS idx_task_state      ON task(current_state);
CREATE INDEX IF NOT EXISTS idx_task_risk       ON task(risk_level);
CREATE INDEX IF NOT EXISTS idx_event_task      ON task_event(task_id);
CREATE INDEX IF NOT EXISTS idx_event_type      ON task_event(event_type);
CREATE INDEX IF NOT EXISTS idx_event_time      ON task_event(created_at);
CREATE INDEX IF NOT EXISTS idx_workitem_task   ON work_item(task_id);
CREATE INDEX IF NOT EXISTS idx_workitem_status ON work_item(status);
