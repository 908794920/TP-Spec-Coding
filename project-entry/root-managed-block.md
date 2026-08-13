## TP-Spec-Coding 协作入口

- 研发任务默认入口是 `tp-workflow-orchestrator`；已有 Task 先用只读 `tp-spec workflow next --task <TASK> --db <DB> --json` 解析下一阶段/角色。Orchestrator 只编排，不替代专业 Skill、不直接写 Runtime；故障时可按 `role-catalog.yaml` 手工加载对应内部专业 Skill 作为应急，不恢复并列开发入口。
- 项目身份以 `.tp-spec/config/project-binding.yaml` 为准；Base、Wiki、Knowledge 的物理路径属于机器安装信息，必须通过当前 TP-Spec-Coding Resolver 解析，不得从目录名、历史 Junction 或其他机器的绝对路径猜测。
- 需要确认当前解析结果时，使用标准 `tp-spec base resolve --workspace-root <workspace-root>`（或当前 Base 的等价 CLI）。项目文件不得保存 machine-local Base/Wiki/Knowledge 绝对路径。
- 代码理解顺序：**Wiki → Knowledge → Source verification**。Wiki 是源码的结构化导航缓存，Knowledge 是长期 canonical 业务/经验知识；Source Code 是当前技术事实的最终权威。
- Knowledge 检索使用标准 `tp-spec knowledge search`，默认保持 `current project + shared`；除非任务明确要求，不得扩大为全局跨项目检索。
- `.tp-spec/` 只承载项目 binding、Runtime/Task 状态与项目级配置 override；Base 程序、公共角色/规则/Skill/模板/脚本不依赖项目 Junction。
- 进入具体任务时，以该任务 `status.yaml`、`events.jsonl` 与正式工件为事实记录；账本投影和 generated 文件按当前 Base contract 维护，不手工伪造。
- 若 Resolver、Registry、Base contract 或项目 binding 无法可靠解析，fail-closed 并如实报告；不得根据本文件之外的旧提示词或历史目录结构自行恢复旧流程。
