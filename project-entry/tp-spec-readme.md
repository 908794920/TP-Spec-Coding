# `.tp-spec` — TP-Spec-Coding 项目状态目录

本目录属于项目 **{{PROJECT_ID}}** 的 TP-Spec-Coding 本地状态面，不是 TP-Spec-Coding 程序目录。

## 权威边界

- `config/project-binding.yaml`：项目身份与当前 Base contract 绑定；不得写入其他机器的 Base/Wiki/Knowledge 绝对路径。
- `config/content-systems.yaml`：仅保存本项目真正需要的 Content Systems override；机器级 Wiki/Knowledge 根由 Installation/Resolver 提供。
- `db/`：项目 Runtime SQLite；其中 `project.root_path` 是当前机器 locator/cache，可由 Base 安全 rebind，不是 portable identity；`*.db-wal` / `*.db-shm` 是 transient。
- `tasks/`：活动任务事实与正式工件。
- `tasksHistory/`：已归档任务历史。
- `.execution/`：持久执行辅助状态；不替代任务账本。

## 使用方式

1. 研发任务默认从 `tp-workflow-orchestrator` 进入；已有 Task 可先运行只读 `tp-spec workflow next --task <TASK> --db <DB> --json` 决定下一专业角色。编排器故障时可按 `role-catalog.yaml` 手工加载对应内部专业 Skill 作为应急，但不得恢复并列开发入口或建立第二状态机。
2. 使用标准 TP-Spec-Coding Resolver 解析 Base、Wiki、Knowledge 与当前项目 scope；不要依赖历史 `.tp-spec/agents`、`wiki`、`knowledge`、`scripts` 等 Junction。
3. 代码理解优先使用项目 Wiki，再检索项目 Knowledge，最后回到 Source Code 核对当前技术事实。
4. Knowledge 默认仅检索 `current project + shared`；全局检索必须显式请求。
5. Runtime 状态只通过当前 Base 正式 CLI/角色流程修改，不直接编辑 SQLite 或伪造账本投影。
6. Base 版本升级、binding 修复、Runtime root rebind、项目入口文档同步由 `tp-base-maintenance` / 标准 `tp-spec base ...` 命令负责；Knowledge/Wiki 内容分别由对应维护能力负责。
7. 当前活动任务若仍包含具有执行语义的旧 Junction 路径，应 targeted repair；历史任务与 evidence 不因迁移而重写。

如果本目录中的说明与当前 Base canonical protocol 冲突，以当前 Base protocol + Resolver 的确定性结果为准。
