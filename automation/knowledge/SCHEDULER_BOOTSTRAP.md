# Knowledge Scheduler Bootstrap

每次运行先读取用户配置，发现可维护的 Knowledge 项目，再逐项目执行日常维护。

1. 先读取用户 TP-Spec-Coding Installation（默认 `~/.tp-spec/installation.yaml`，或 `TP_SPEC_INSTALLATION_CONFIG`），解析 physical Base Root、Knowledge System Root、Workspace Inventory 与 Knowledge Project Registry。不得从当前工作目录、目录名、历史 Junction 或猜测路径推断项目。
2. 通过当前 Base Resolver、Workspace Inventory 与 Knowledge Project Registry 的精确 `workspace_roots` 映射，枚举所有已注册且未归档的 workspace/project；每个 workspace 独立解析 Knowledge Project Root 和 project scope。没有唯一映射、配置不可读或没有可维护范围时，报告事实并停止，不伪造项目范围。
3. 读取当前 Base 的 `automation/knowledge/daily-maintenance.md`，对每个已解析 workspace 严格按该版本协议执行；向正式 CLI 传入解析得到的 `--workspace-root <workspace>`，而不是 Scheduler 当前目录。
4. 使用 `tp-knowledge` 与正式 `tp-spec knowledge ...` CLI；不得依赖项目 `.tp-spec/knowledge` / `.tp-spec/scripts` Junction，也不要调用 Knowledge Vault 中的 legacy tools。
5. 每个项目的默认 Retrieval Scope 必须保持 `current project + shared`；只有任务明确要求跨项目时才使用 `--scope global`。不得因为一次调度处理多个项目而把默认查询扩大为全局。
6. 这是无人值守对话模型任务：**不得 AskUserQuestion**。遇到项目归属不明、删除/覆盖、merge/split 冲突、破坏性操作或证据不足时，对该项目 fail-closed，保留旧 baseline，并在日报标记 `NEEDS_REVIEW`；其他项目仍可独立继续。
7. 最后按 workspace/project 输出变化、已执行动作、verify/audit/index/baseline、检索范围和需要人工处理的问题；不得用一个“全局已完成”结论隐藏单项目失败。
