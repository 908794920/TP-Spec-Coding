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

### Runtime DB 定位

保留当前 workspace 已有默认 `<project-id>.db` 的选择；默认库不存在时，使用显式 `TP_SPEC_DB` 或同 project id 的 Runtime Registry 定位，不扫描/猜测其他数据库。项目内自定义库随目录迁移时，按已登记旧 root 下的相对位置找到新库；外置/共享库保留自身 locator，确已迁移时由调用者显式指定新路径。

解析、契约检查与 rebind 使用同一个数据库。已选库缺失、身份/schema 不匹配、旧 workspace 或冲突注册库仍存在时停止受影响同步，不按“Runtime 尚未安装”继续生成入口；重绑只更新 machine-local locator，不改 Task 历史、项目配置或 portable binding。

### Active task portability

Base 只检查 `.tp-spec/tasks` 中仍处于 `NEW/ACTIVE/BLOCKED` 的顶层 Markdown formal artifacts。若发现具有执行语义的旧 `.tp-spec/knowledge|wiki|scripts|agents|governance|skills|templates|automation|cli` 路径，报告 `LEGACY_ACTIVE_REFERENCE` 并要求 targeted review。明确的 legacy/禁止使用描述不作为 actionable finding。`tasksHistory`、evidence 与已完成任务不做历史清洗。

SQLite `*.db-wal` / `*.db-shm` 属于 transient runtime，不作为 portable truth，不因其存在判定 portability FAIL。
