## TP-Spec-Coding 协作入口

- 默认入口 `tp-spec-coding`；软件工作交 `tp-software-lifecycle`。已有 Task 先读 `tp-spec workflow next --task <TASK> --db <DB> --json`，按 Resolver 定位的 Base 内 `governance/role-catalog.yaml` 加载对应 Role，再按触发读 Skill，不预载全部能力。
- 遵守根 `AGENTS.md` 自有规则和本次授权；安全发现、Review/测试、计划/子工作与生成文档都不增加需求或动作权限。真实 scope/高风险取舍交 human_owner。
- 先判断是否需要正式 Task：目标和范围明确的普通局部修改直接定位、修改、做必要验证并说明结果，不因接入 TP-Spec、调用 Skill、测试、留日志或收尾自动建 Task；只有用户要求任务记录、项目自有规则明确要求，或工作确实需要持续跟踪与协作交付时，才复用或建立正式 Task。“全链路开发测试”“连续完成”本身不等于要求建 Task 或选择 standard。
- 已确定需要正式任务跟踪时，一个独立需求对应一个父 Task；同范围返修继续原 Task，批次或多个工作项按需归 Work，不逐问题另建 Task。standard Task 按适用义务完成专业参与、获准集成、精确接收及知识/记忆评估，复验旧 PASS 的适用性；quick 由用户明确选择，不强制 Work/角色链或知识/记忆评估。协调、候选登记及收尾按当前 Runtime 和领域 SKILL，不把正式 Task 流程套用到直接处理的普通修改。
- 项目身份来自 `.tp-spec/config/project-binding.yaml`；Base/Wiki/Knowledge 位置只经 `tp-spec base resolve --workspace-root <workspace-root>` 解析，不依赖旧 Junction 或硬编码机器路径。解析不可靠时停止受影响动作并报告，不恢复旧流程。
- Source Code 是当前技术事实，Wiki 是导航，Knowledge 是长期知识；需知识时使用 `tp-spec knowledge search`，默认 current project + shared，不擅自全局检索。
- 根 `AGENTS.md` 自有区保留必要硬约束和高价值经验的薄入口（问题现象/关键术语 + 精确相对指针）；详细规则归项目 Memory，方法归项目 Skill，已有 Task 的临时进度/授权/验收留 Task。沉淀时同时核对入口可发现性，不强制每次新增。已知目标直达，未知且需要时才读 `.tp-spec/memory/INDEX.md`；可选缓存缺失不阻塞，秘密和机器配置不沉淀。
- Task 事实经正式 Runtime/CLI 记录，status/events/generated 不手工伪造；历史 actor 不表示正在执行。同步仅更新 Base 托管区，不覆盖项目自有内容，不建 agent.md 或大小写副本。

需要 Memory 归位/持久化失败处置时读 Base 的 `skills/capabilities/tp-memory-capture/SKILL.md`；需要接入、Telemetry、工作台或迁移规则时读 [.tp-spec 使用说明](.tp-spec/README.md)。
