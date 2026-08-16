# Autonomous Maintenance Automation

Autonomous Maintenance 使用“短 Scheduler bootstrap → 当前 Base protocol → 本地 Agent Executor → deterministic `tp-spec autonomy ...` CLI”的模式。

## Scheduler != Executor

Scheduler 只决定什么时候唤醒。真正 Executor 至少必须：
- 能访问 Canonical 与 Autonomous Workspace 的本地文件系统；
- 能执行 Git、Python 与当前 `tp-spec` CLI；
- 能读取当前 Base/Agent/Skill；
- 能运行实际 AI Agent；
- 单次执行时长能覆盖 Profile safety budget。

仅能在云端定时发送一条聊天消息、无法访问本地 Workspace 的工具可以做提醒，**不能直接执行 Autonomy Cycle**。

外部 Scheduler 不要复制 L0～L3 pipeline、Agent 列表或长工作流提示词。Profile 自己保存 bootstrap prompt，真正协议以本目录和当前 `tp-workflow-orchestrator` 为准。
