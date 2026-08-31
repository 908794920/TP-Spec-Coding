# 项目接入与可移植性

适用条件：执行 `base sync-project` 或检查 active task portability 时读取。

### Project integration surface

`tp-spec base sync-project --workspace-root <ROOT>` 默认只读计划；显式 `--apply` 后才允许：

- 新建/更新根 `AGENTS.md` 的 `tp-spec-base:managed` block；
- 新建/更新根 `README.md` 的同一 managed block，并保留项目自身内容；
- 生成/更新 Base-owned `.tp-spec/README.md`；
- 从 project-local `content-systems.yaml` 移除与当前 Installation 完全重复的 machine roots；若只剩 schema/空 override，则删除该冗余 project config；
- 含真实项目级 coverage/quality 等 override 时保留语义，只移除可证明冗余的 machine roots。

遇到 malformed managed markers、与 Installation 不一致的 absolute project override 或其他无法证明安全的 machine path 必须 `BLOCKED`，不得猜测或静默重写。

### Active task portability

Base 只检查 `.tp-spec/tasks` 中仍处于 `NEW/ACTIVE/BLOCKED` 的顶层 Markdown formal artifacts。若发现具有执行语义的旧 `.tp-spec/knowledge|wiki|scripts|agents|governance|skills|templates|automation|cli` 路径，报告 `LEGACY_ACTIVE_REFERENCE` 并要求 targeted review。明确的 legacy/禁止使用描述不作为 actionable finding。`tasksHistory`、evidence 与已完成任务不做历史清洗。

SQLite `*.db-wal` / `*.db-shm` 属于 transient runtime，不作为 portable truth，不因其存在判定 portability FAIL。
