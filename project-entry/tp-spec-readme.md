# `.tp-spec` — TP-Spec-Coding 项目状态目录

本目录属于项目 **{{PROJECT_ID}}** 的 TP-Spec-Coding 本地状态面，不是 TP-Spec-Coding 程序目录。

## 权威边界

- 项目根 `AGENTS.md` 自有区（Base 托管标记外）保留必要硬约束和高价值经验的薄入口，以问题现象/关键术语指向详细内容；详细稳定规则归 Memory `PROJECT.md` 相应分节，可复用方法归项目 Skill，临时事实留 Task。沉淀时同时评估入口是否需要新增或更新，已有覆盖则复用；具体格式与可发现性核对统一见 `tp-memory-capture`。同步 Base 只更新托管内容，不覆盖自有规则，也不把 Memory 整体搬入入口。
- `config/project-binding.yaml`：项目身份与当前 Base contract 绑定；不得写入其他机器的 Base/Wiki/Knowledge 绝对路径。
- `config/content-systems.yaml`：仅保存本项目真正需要的 Content Systems override；机器级 Wiki/Knowledge 根由 Installation/Resolver 提供。
- `db/`：项目 Runtime SQLite；其中 `project.root_path` 是当前机器 locator/cache，可由 Base 安全 rebind，不是 portable identity；`*.db-wal` / `*.db-shm` 是 transient。
- `tasks/`：活动任务事实与正式工件。
- `tasksHistory/`：已归档任务历史。
- `.execution/`：持久执行辅助状态；不替代任务账本。
- 历史 `card/`：旧展示文件不再生成或更新，不属于 Runtime/Task truth；不要因升级批量删除其中的用户历史文件。
- `memory/`：项目 Git 可携带的轻量热记忆与项目级 Skill；`INDEX.md` 是目标未知时的可选导航，不承载正文；`PROJECT.md` 保存详细稳定规则和有来源、适用条件的事实线索，方法正文归项目 Skill。Memory 不是当前技术事实真源，不保存敏感或 machine-local 信息。

## 使用方式

1. 默认产品入口是 `tp-spec-coding`；软件研发意图由它交给 `tp-software-lifecycle`。已有 Task 可先运行只读 `tp-spec workflow next --task <TASK> --db <DB> --json` 决定下一专业角色。生命周期路由异常时可按 `governance/role-catalog.yaml` 手工加载对应内部专业 Skill 作为应急，但不得恢复并列开发入口或建立第二状态机。
2. 已知目标 Skill/片段时直达；目标未知且本轮需要经验时才查 `memory/INDEX.md`，无关 Memory 不读。可选索引/缓存缺失或损坏可跳过，不预加载 PROJECT、全部 Skills、Task History 或 Knowledge，不全盘搜索补缺。日常已确认稳定 Rule 或高价值经验按需使用唯一 `tp-memory-capture`；每 Task 最终交付必须基于有效需求及各步骤材料做知识/记忆评估，不依赖信号，但不强制写入。Rule 不受重发现成本限制，可选经验才过 Gate，不得为学习扫描历史。根规则写失败须说明未持久化，当前已知规则仍遵守，权限不明只停止受影响动作。
3. 使用标准 TP-Spec-Coding Resolver 解析 Base、Wiki、Knowledge 与当前项目 scope；不要依赖历史 `.tp-spec/agents`、`wiki`、`knowledge`、`scripts` 等 Junction。
4. 需要导航或业务背景时按需使用 Wiki/Knowledge，已知源码位置可直接核对当前技术事实；Memory 只提供快速导航/执行提示。
5. Knowledge 默认仅检索 `current project + shared`；全局检索必须显式请求。
6. Runtime 状态只通过当前 Base 正式 CLI/角色流程修改，不直接编辑 SQLite 或伪造账本投影。
7. Base 版本升级、binding 修复、Runtime root rebind、项目入口文档同步由 `tp-base-maintenance` / 标准 `tp-spec base ...` 命令负责；Knowledge/Wiki 内容分别由对应维护能力负责。
8. 当前活动任务若仍包含具有执行语义的旧 Junction 路径，应 targeted repair；历史任务与 evidence 不因迁移而重写。
9. 查看项目/任务/配置的可视化，在 TP-Spec-Coding 自身源码根运行 `npm run dev` 并打开终端地址；不要在本业务项目复制前端，也不通过会话宿主生成 HTML。页面只读现有事实，进入页面或手动读取才更新。
10. 项目级可重建生成物默认放入 `.tp-spec/<feature>/`，不要在项目根新增 `.tp-spec-*` 或 preview/cache 兄弟目录；高频短生命周期 execution scratch 继续使用 **system Temp**，不迁入项目状态目录。

如果本目录中的说明与当前 Base canonical protocol 冲突，以当前 Base protocol + Resolver 的确定性结果为准。


## 按需读取与记录
- 角色与能力：Resolver 定位的 Base 内 `governance/role-catalog.yaml` 是唯一挂载源，角色入口提供触发/边界；方法只在实际使用时读取，故障手工加载不绕过 Runtime 或身份隔离。
- Memory：Rule 要有来源、范围与写入授权，不受重发现成本限制；Fact/Procedure 需证据、稳定、可复用且重发现成本高。按共享方法先保存并读回正文，再在授权范围内维护 AGENTS 自有区的相关触发入口并核对可发现性；不改托管标记或无关自有原文。分别记录正文与入口的实际处置，重要规则或必要入口写失败说明未持久化、责任与恢复条件，当前已知规则仍遵守；可选缓存失败不无关阻塞。INDEX 只在导航变化时更新，不要求每次交付修改所有 Memory 文件。
- Telemetry：本阶段真实使用 Wiki/Knowledge/Memory/项目 Skill 时，才在原有 checkpoint/review/verify/delivery 附 `--context-usage-json`。不得为遥测额外搜索、扫描、读取或调用模型；source_followup 默认 unknown，仅有实际 tool-call/source-read 证据才写 none/targeted/broad；失败不阻塞研发。
- 状态面：`.tp-spec/` 保存 binding、Runtime/Task、Memory 和配置 override；Base 程序/公共方法不复制到项目、不依赖 Junction。进入 Task 读取真实 status/events/正式工件，派生视图过期不推翻已提交事实。
