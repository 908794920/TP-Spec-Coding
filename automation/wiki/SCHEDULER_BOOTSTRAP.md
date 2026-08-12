# Wiki Scheduler Bootstrap

当前定时任务可以在 **Wiki System Root** 作为工作目录运行；该目录只作为执行锚点，不是 Source Workspace。

1. 先读取用户 TP-Spec-Coding Installation（默认 `~/.ai-work/installation.yaml`，或 `AI_WORK_INSTALLATION_CONFIG`），解析 physical Base Root 与 Wiki System Root；不得在 Scheduler Prompt 中硬编码用户机器绝对路径。
2. 从当前 Base 读取 `automation/wiki/daily-maintenance.md`，严格按该版本 canonical protocol 执行。
3. 使用正式 `<BaseRoot>/scripts/Invoke-AiWorkCli.ps1`（或等价已安装 `ai-work` 命令）；不得依赖项目 `.ai-work/scripts` / `.ai-work/wiki` Junction，也不得调用旧 Wiki 数据仓中的 legacy tools。
4. 需要维护哪些 Source Workspace，必须通过当前 Base 标准 Resolver、Workspace Inventory 与 Wiki Repo Registry 解析。对每个 workspace/repo **独立保持 project/repository scope**；当前 Wiki System Root 绝不能被当成 `--workspace-root`，也不得因此执行无边界中央 Wiki 全库源码扫描。
5. 这是无人值守对话模型任务：**不得 AskUserQuestion**。某个 workspace/repo 若 Registry/Resolver 不唯一、发生破坏性操作歧义、MASS_CHANGE 无充分证据或 L4 证据不足，则该范围 fail-closed、保留旧 baseline，并标记 `NEEDS_REVIEW`；不得猜路径或用历史 Junction 恢复旧流程。
6. 最后按 repository 输出变化、verify/coverage/L4/baseline 结果以及需要人工处理的问题；不得用一个“全库已完成”结论隐藏单仓失败。
