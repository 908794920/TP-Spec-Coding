# Autonomous Maintenance Scheduler Bootstrap

对指定 TP-Spec-Coding Autonomy Profile 执行一次无人值守 Maintenance Cycle。

1. 解析当前用户 Autonomy Profile 与 physical Base Root。
2. 读取当前 Base 的 `automation/autonomy/autonomous-cycle.md` 与 `agents/tp-project-autonomy/SKILL.md`。
3. 使用满足本地文件/Git/Python/Agent 能力的 Executor；纯提醒型云端 Scheduler 不足以执行。
4. 不缓存或自行模拟 Workflow；所有普通 Task 路由以当前 `tp-workflow-orchestrator` 为准。
5. 只能在 Profile 的 Autonomous Workspace 修改 Repo，绝不直接写 Canonical。
6. 无人值守阶段不得 AskUserQuestion；任何 `requires_human` 都 fail-closed 并进入 Digest。
7. `max_new_tasks_per_cycle` 是 ceiling，不是 quota；没有高价值改进时 0 Task 是正常成功结果。
8. 最后输出 redacted Cycle Digest：变化、在途、待用户决策、待 Integration、drift 与 next_user_actions。
