# Wiki Scheduler Bootstrap

每次运行先读取用户配置，解析 Wiki System Root 及可维护的 Source Workspace/repository，再逐范围执行日常维护。

1. 先读取用户 TP-Spec-Coding Installation（默认 `~/.tp-spec/installation.yaml`，或 `TP_SPEC_INSTALLATION_CONFIG`），解析 physical Base Root、Wiki System Root、Workspace Inventory 与 Wiki Repo Registry；不得在 Scheduler Prompt 中硬编码用户机器绝对路径。
2. 通过当前 Base 标准 Resolver、Workspace Inventory 与 Wiki Repo Registry 的精确映射，枚举所有已注册且启用的 Source Workspace/repository；不得从 Scheduler 当前目录、目录名、历史 Junction 或猜测路径推断项目。
3. 从当前 Base 读取 `automation/wiki/daily-maintenance.md`，对每个解析得到的 workspace/repo 严格按该版本 canonical protocol 执行。
4. 使用正式 `<BaseRoot>/scripts/tp-spec.ps1`（或等价已安装 `tp-spec` 命令）；为每个范围传入解析得到的 `--workspace-root <workspace>` 与 `--repo <repo-id>`，不得依赖项目 `.tp-spec/scripts` / `.tp-spec/wiki` Junction，也不得调用旧 Wiki 数据仓中的 legacy tools。
5. 对每个 workspace/repo **独立保持 project/repository scope**；当前 Wiki System Root 绝不能被当成 `--workspace-root`，也不得因此执行无边界中央 Wiki 全库源码扫描。一个范围没有唯一映射或没有可维护范围时，报告事实并跳过，不伪造范围。
6. 这是无人值守对话模型任务：**不得 AskUserQuestion**。某个 workspace/repo 若 Registry/Resolver 不唯一、发生破坏性操作歧义、MASS_CHANGE 无充分证据或 L4 证据不足，则该范围 fail-closed、保留旧 baseline，并标记 `NEEDS_REVIEW`；其他范围仍可独立继续。
7. 最后按 workspace/repository 输出变化、verify/coverage/L4/baseline 结果以及需要人工处理的问题；不得用一个“全库已完成”结论隐藏单仓失败。
