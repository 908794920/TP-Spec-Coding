# V5.2.9 迁移说明

V5.2.9 是单活动契约切换，不追溯改写历史终态任务。

## 迁移边界

- `COMPLETED` / `CANCELLED` 的 V5.2.8 Task 保持不可变历史，不执行 `task migrate`；需要检查目录后续变化时使用只读 `task terminal-check`。
- V5.2.8 在途 Task 必须先升级 Project contract，再显式迁移 Task。
- 迁移不会把旧 Verification/Review 的 PASS 自动升级成可信 V5.2.9 结论。旧 Development checkpoint 缺少 `change_set_id` 时，工作流会重新路由 Development；随后重新 Verification、Review。
- 旧 `database_verification` 最多机械迁移为一条 `database_operations`；不会猜测不存在的第二条数据库操作，也不会伪造缺失的 SQL 工件或执行证据。
- 旧 task-scoped `NO_CHANGE` / `DEFERRED` 仅保留历史可读性，不满足新的 `KNOWLEDGE_CONVERGENCE_RESULT`。
- `PENDING` / `BLOCKED` AC 保留真实状态；结单前必须 PASS、NOT_REQUIRED/N/A，或由 human_owner defer/waive。

## 在途 Task 升级

```bash
python -m cli.main project upgrade-contract --id <PROJECT> --db <DB>
python -m cli.main task migration-plan --project <PROJECT> --db <DB> --gate
python -m cli.main task migrate --task <TASK> --task-dir <TASK-DIR> --db <DB>
python -m cli.main workflow next --task <TASK> --db <DB>
```

迁移完成后，以 `workflow next` 的真实路由为准。出现 `CHANGE_SET_REQUIRED` 时重新进入 Development，不复用旧代码 PASS。

## 数据库旧声明

旧 `database_verification` 是 task 级单操作声明。迁移只保留这一条操作：

- `NONE` → `database_operations: []`；
- `READ/DML/DDL` → `DB-LEGACY-01`；
- 旧字段缺少 `artifact_ref` 等新契约必需事实时保持空值，由后续验证显式补齐，不能猜测。

## Knowledge

V5.2.9 的任务知识收敛必须使用 typed effect：

```text
KNOWLEDGE_CONVERGENCE_REQUEST
→ tp-knowledge targeted search
→ KNOWLEDGE_CONVERGENCE_RESULT
```

没有结构化知识信号时为 `NOT_REQUIRED`；有 Request 但没有可信 Result 时为 `NOT_RUN`，不得用旧 `NO_CHANGE` 替代。
