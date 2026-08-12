# Knowledge Scheduler Bootstrap

在当前 workspace 执行 TP-Spec-Coding Knowledge 日常维护。

1. 先读取用户 TP-Spec-Coding Installation（默认 `~/.ai-work/installation.yaml`，或 `AI_WORK_INSTALLATION_CONFIG`），解析 physical Base Root、Knowledge System Root；项目绑定/Registry 再解析当前 Knowledge Project Root。
2. 读取当前 Base 的 `automation/knowledge/daily-maintenance.md`，严格按该版本协议执行。
3. 使用 `tp-knowledge` 与正式 `ai-work knowledge ...` CLI；不得依赖项目 `.ai-work/knowledge` / `.ai-work/scripts` Junction，也不要调用 Knowledge Vault 中的 legacy tools。
4. 默认 Retrieval Scope 必须保持 `current project + shared`；只有任务明确要求跨项目时才使用 `--scope global`。
5. 这是无人值守对话模型任务：**不得 AskUserQuestion**。遇到项目归属不明、删除/覆盖、merge/split 冲突、破坏性操作或证据不足时 fail-closed，保留旧 baseline，并在日报标记 `NEEDS_REVIEW`。
6. 最后只输出变化、已执行动作、verify/audit/index/baseline 结果和需要人工处理的问题。
