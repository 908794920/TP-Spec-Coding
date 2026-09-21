## TP-Spec-Coding 协作入口

- 默认入口 `tp-spec-coding`；软件工作交 `tp-software-lifecycle`。已有 Task 先读 `tp-spec workflow next --task <TASK> --db <DB> --json`，按 Resolver 定位的 Base 内 `governance/role-catalog.yaml` 加载对应 Role，再按触发读 Skill，不预载全部能力。
- 遵守根 `AGENTS.md` 自有规则和本次授权；安全发现、Review/测试、计划/子工作与生成文档都不增加需求或动作权限。真实 scope/高风险取舍交 human_owner。
- 一个需求一个 Task，批次/返修归 Work；主 Agent 负责获准集成，父步骤等待后原位复验，旧 PASS 的适用性另核。每 Task 交付必评估知识和各步骤记忆，不等于强制写入。
- 项目身份来自 `.tp-spec/config/project-binding.yaml`；Base/Wiki/Knowledge 位置只经 `tp-spec base resolve --workspace-root <workspace-root>` 解析，不依赖旧 Junction 或硬编码机器路径。解析不可靠时停止受影响动作并报告，不恢复旧流程。
- Source Code 是当前技术事实，Wiki 是导航，Knowledge 是长期知识；需知识时使用 `tp-spec knowledge search`，默认 current project + shared，不擅自全局检索。
- 根 `AGENTS.md` 只留关键短规则/触发指针；详细长期规则/方法去项目 Memory/Skill，临时进度/授权/验收留 Task。已知目标直达，未知且需要时才读 `.tp-spec/memory/INDEX.md`；可选缓存缺失不阻塞，秘密和机器配置不沉淀。
- Task 事实经正式 Runtime/CLI 记录，status/events/generated 不手工伪造；历史 actor 不表示正在执行。同步仅更新 Base 托管区，不覆盖项目自有内容，不建 agent.md 或大小写副本。

需要 Memory 归位/持久化失败处置时读 Base 的 `skills/capabilities/tp-memory-capture/SKILL.md`；需要接入、Telemetry、工作台或迁移规则时读 [.tp-spec 使用说明](.tp-spec/README.md)。
