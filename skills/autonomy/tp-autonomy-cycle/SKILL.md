---
name: tp-autonomy-cycle
version: 5.2.6
description: 外部 Scheduler/本地 Executor 唤起的一次无人值守 Autonomous Maintenance Cycle；使用 generation fencing，复用普通 Task 与当前 tp-software-lifecycle。
---

# tp-autonomy-cycle

## 前提
这是无人值守协议：**不得 AskUserQuestion**。需要 human_owner 的事项必须 BLOCKED + Digest，等交互式会话处理后下一 Cycle 才生效。

## 执行骨架
1. `tp-spec autonomy cycle begin --profile ... --json`，保存返回的 `cycle_id + generation`。若 `CYCLE_ALREADY_RUNNING`，本次零副作用退出。
2. `autonomy doctor` + `workspace status`，记录 Canonical/Staging drift；v1 不自动 rebase/merge Canonical 到 staging。
3. 优先继续已有、已获准且在 safety budget 内的普通 Task。
4. 同 Cycle 可执行的已批准 Task 组成一个薄 Batch；逐 Task：
   - `batch start-task`；
   - `autonomy route` 获取当前 Orchestrator 决策；
   - 只加载返回的专业 Skill；
   - Task 正常 checkpoint/verify/delivery；
   - 自动 rework 前先执行 `autonomy cycle claim-rework`；达到 rework 上限时 fail-safe 停止该 Task；
   - 完成后 `batch commit-task` 建立 Task→Git commit 绑定；
   - 失败且需丢弃未验证工作时 `batch abort-task`。
5. 仍有 discovery capacity 才进行 targeted discovery。候选必须基于 **Autonomous staging HEAD** + Canonical Wiki/Knowledge 只读上下文，而不是重新以 Canonical 源码当开发基线。
6. 每个真实候选用 `autonomy discover` 创建普通 Task；不要为了达到 ceiling 制造需求或强拆 Task。
7. 新 Task 继续交给 `autonomy route`，只推进到当前 Execution Envelope 允许的位置。遇到任何 `requires_human` fail-closed。
8. `autonomy digest` 输出新 Task、等待决策、在途、失败、待 Integration、drift 与 next_user_actions。
9. `cycle end` 正常结束。若异常退出，下一 Cycle 通过 deadline + generation reclaim fencing 旧 Executor。

## Safety
尊重 Profile 的 `max_existing_tasks_per_cycle`、`max_rework_attempts_per_task`、`max_cycle_minutes`、pending-decision backlog guard。免费本地模型也不得无限重试。

## Cycle token 范围
只有 cycle-scoped mutation 命令需要 `cycle_id + generation`。`autonomy decide`、`review`、`integrate` 属于 user-session，不得错误要求 Cycle token。
