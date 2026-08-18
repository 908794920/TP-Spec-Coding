## TP-Spec-Coding 协作入口

- 默认产品入口是 `tp-spec-coding`；软件研发意图交给 `tp-software-lifecycle`。已有 Task 先用只读 `tp-spec workflow next --task <TASK> --db <DB> --json` 解析下一阶段/角色。Software Lifecycle 只做生命周期/角色路由，不替代专业 Skill、不直接写 Runtime；故障时可按 `governance/role-catalog.yaml` 手工加载对应内部专业 Skill 作为应急，不恢复并列开发入口。
- 进入项目先读 `.tp-spec/memory/INDEX.md`（若存在）；默认不展开整个 `PROJECT.md`、全部 Skills、Task History 或 Knowledge，只按当前任务加载命中片段/Top 1 Skill。Memory 是机会式热缓存，不替代事实真源；角色仅在当前工作自然出现高价值、已证实且高重发现成本的经验时按需加载内部 `tp-memory-capture`，不得主动扫描寻找记忆。
- 项目身份以 `.tp-spec/config/project-binding.yaml` 为准；Base、Wiki、Knowledge 的物理路径属于机器安装信息，必须通过当前 TP-Spec-Coding Resolver 解析，不得从目录名、历史 Junction 或其他机器的绝对路径猜测。
- 需要确认当前解析结果时，使用标准 `tp-spec base resolve --workspace-root <workspace-root>`（或当前 Base 的等价 CLI）。项目文件不得保存 machine-local Base/Wiki/Knowledge 绝对路径。
- 需要进一步理解代码时按 **Wiki → Knowledge → Source verification**；Wiki 是源码的结构化导航缓存，Knowledge 是长期 canonical 业务/经验知识，Source Code 是当前技术事实最终权威。
- Knowledge 检索使用标准 `tp-spec knowledge search`，默认保持 `current project + shared`；除非任务明确要求，不得扩大为全局跨项目检索。
- 正式 Task 中若本阶段真实使用了 Wiki / Knowledge / Project Memory / Project Skill，可在原本的 checkpoint / review / verify / delivery 写入上顺带附 `--context-usage-json`；不得为了 telemetry 额外搜索、扫描、读取或调用模型。`source_followup` 默认 `unknown`，只有存在明确 tool-call/source-read 证据时才填写 `none|targeted|broad`。Telemetry 失败不得阻塞研发。
- `.tp-spec/` 承载项目 binding、Runtime/Task 状态、项目级 Memory 与配置 override；Memory 可随项目 Git 演进，但不得保存 machine-local/敏感信息。Base 程序、公共角色/规则/Skill/模板/脚本不依赖项目 Junction。
- 进入具体任务时，以该任务 `status.yaml`、`events.jsonl` 与正式工件为事实记录；账本投影和 generated 文件按当前 Base contract 维护，不手工伪造。
- 若 Resolver、Registry、Base contract 或项目 binding 无法可靠解析，fail-closed 并如实报告；不得根据本文件之外的旧提示词或历史目录结构自行恢复旧流程。
