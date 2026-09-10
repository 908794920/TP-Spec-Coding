# `.tp-spec` — TP-Spec-Coding 项目状态目录

本目录属于项目 **{{PROJECT_ID}}** 的 TP-Spec-Coding 本地状态面，不是 TP-Spec-Coding 程序目录。

## 权威边界

- 稳定重要的项目规则归项目根 `AGENTS.md` 自有区（Base 托管标记外）；临时事实留 Task，方法按需沉淀。同步 Base 只更新托管内容，不覆盖自有规则，也不把 Memory 整体搬入入口。
- `config/project-binding.yaml`：项目身份与当前 Base contract 绑定；不得写入其他机器的 Base/Wiki/Knowledge 绝对路径。
- `config/content-systems.yaml`：仅保存本项目真正需要的 Content Systems override；机器级 Wiki/Knowledge 根由 Installation/Resolver 提供。
- `db/`：项目 Runtime SQLite；其中 `project.root_path` 是当前机器 locator/cache，可由 Base 安全 rebind，不是 portable identity；`*.db-wal` / `*.db-shm` 是 transient。
- `tasks/`：活动任务事实与正式工件。
- `tasksHistory/`：已归档任务历史。
- `.execution/`：持久执行辅助状态；不替代任务账本。
- `card/`：固定项目级 Web Artifact，入口为 `.tp-spec/card/index.html`；该目录是 **presentation-only / rebuildable / non-authoritative**，不属于 Runtime/Task truth，删除后可重新生成。
- `memory/`：项目 Git 可携带的轻量热记忆与项目级 Skill；`INDEX.md` 是目标未知时的可选导航，`PROJECT.md` 不是事实真源，不保存敏感或 machine-local 信息。

## 使用方式

1. 默认产品入口是 `tp-spec-coding`；软件研发意图由它交给 `tp-software-lifecycle`。已有 Task 可先运行只读 `tp-spec workflow next --task <TASK> --db <DB> --json` 决定下一专业角色。生命周期路由异常时可按 `governance/role-catalog.yaml` 手工加载对应内部专业 Skill 作为应急，但不得恢复并列开发入口或建立第二状态机。
2. 已知目标 Skill/片段时直达；目标未知且本轮需要经验时才查 `memory/INDEX.md`，无关 Memory 不读。可选索引/缓存缺失或损坏可跳过，不预加载 PROJECT、全部 Skills、Task History 或 Knowledge，不全盘搜索补缺。已确认稳定 Rule 或高价值经验按需使用内部 `tp-memory-capture`；Rule 不受重发现成本限制，可选经验才过 Gate，不得为学习扫描历史。根规则写失败须说明未持久化，当前已知规则仍遵守，权限不明只停止受影响动作。
3. 使用标准 TP-Spec-Coding Resolver 解析 Base、Wiki、Knowledge 与当前项目 scope；不要依赖历史 `.tp-spec/agents`、`wiki`、`knowledge`、`scripts` 等 Junction。
4. 需要导航或业务背景时按需使用 Wiki/Knowledge，已知源码位置可直接核对当前技术事实；Memory 只提供快速导航/执行提示。
5. Knowledge 默认仅检索 `current project + shared`；全局检索必须显式请求。
6. Runtime 状态只通过当前 Base 正式 CLI/角色流程修改，不直接编辑 SQLite 或伪造账本投影。
7. Base 版本升级、binding 修复、Runtime root rebind、项目入口文档同步由 `tp-base-maintenance` / 标准 `tp-spec base ...` 命令负责；Knowledge/Wiki 内容分别由对应维护能力负责。
8. 当前活动任务若仍包含具有执行语义的旧 Junction 路径，应 targeted repair；历史任务与 evidence 不因迁移而重写。
9. 项目级可重建生成物默认放入 `.tp-spec/<feature>/`，不要在项目根新增 `.tp-spec-*` 或 preview/cache 兄弟目录；高频短生命周期 execution scratch 继续使用 **system Temp**，不迁入项目状态目录。

如果本目录中的说明与当前 Base canonical protocol 冲突，以当前 Base protocol + Resolver 的确定性结果为准。
