# Knowledge Scheduler Bootstrap

每次运行先读取用户配置，发现可维护的 Knowledge 项目，按物理知识库执行一次日常维护，再按项目报告内容处理结果。AI 与执行时间由用户在定时器中选择。

1. 先读取用户 TP-Spec-Coding Installation（默认 `~/.tp-spec/installation.yaml`，或 `TP_SPEC_INSTALLATION_CONFIG`），解析 physical Base Root、Knowledge System Root、Workspace Inventory 与 Knowledge Project Registry。不得从当前工作目录、目录名、历史 Junction 或猜测路径推断项目。
2. 通过当前 Base Resolver、已启用的 Workspace Inventory 与 Knowledge Project Registry 的精确 `workspace_roots` 映射，枚举所有已注册且未归档的 workspace/project；独立解析项目身份后，按 Resolver 得到的 Knowledge 物理 System Root 归组去重。同一物理库只执行一条串行维护链，不因多个 workspace 指向它而重复或并发执行。没有唯一映射时标记受影响范围 `NEEDS_REVIEW`，不伪造项目范围。
3. 读取当前 Base 的 `agents/tp-knowledge/SKILL.md`，按其中定时维护路由加载能力，再读取 `automation/knowledge/daily-maintenance.md`。先按协议核对同库各 workspace 的共享状态路径、有效维护配置和库级操作范围；冲突或无法核实时保留该库 baseline、标记 `NEEDS_REVIEW`。确认一致后，从该组选择一个已解析 workspace 作为本轮库级命令入口，正式 CLI 始终传入它的 `--workspace-root <workspace>`；内容判断和检索仍使用对应项目身份。
4. 使用当前 Base 的正式 `scripts/tp-spec.ps1 knowledge ...`（或等价已安装命令）；不得依赖项目 `.tp-spec/knowledge` / `.tp-spec/scripts` Junction，也不要调用 Knowledge Vault 中的 legacy tools。未读到当前领域入口或维护协议时停止依赖动作，不凭旧提示词继续。
5. 每个项目的默认 Retrieval Scope 必须保持 `current project + shared`；只有任务明确要求跨项目时才使用 `--scope global`。不得因为一次调度处理多个项目而把默认查询扩大为全局。
6. 这是无人值守对话模型任务：**不得 AskUserQuestion**。遇到项目归属不明、删除/覆盖、merge/split 冲突、破坏性操作或证据不足时，对该项目 fail-closed，标记 `NEEDS_REVIEW`；同库其他项目可继续明确且安全的内容处理，但未解决项不得被总基线提交掩盖，保留该库旧 baseline。其他物理库可独立继续。
7. 最后先按物理库报告 scan/index/verify/audit/baseline，再按 workspace/project 输出内容变化、处置、检索范围和待人工处理事项；不得把库级结果冒充每项目独立提交，也不得用一个“全局已完成”结论隐藏单项目失败。
