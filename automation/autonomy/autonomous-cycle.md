# Autonomous Maintenance Cycle Canonical Protocol

每次运行都重新读取当前 Base，不把本文件内容复制成长期 Scheduler 真源。

```text
cycle begin
→ doctor / workspace status / drift
→ 优先恢复已有允许执行 Task
→ approved Tasks → thin Batch
→ 每 Task 继续当前 tp-workflow-orchestrator
→ Task 完成 → Git commit binding
→ 有余量才 targeted discovery
→ 新发现 = ordinary Task
→ route 到 repo_mutation / requires_human boundary 即 BLOCKED
→ digest
→ cycle end
```

硬约束：
- 使用当前 `cycle_id + generation` 进行 cycle-scoped mutation fencing；
- user-session `decide/review/integrate` 不需要 Cycle token；
- Stage Effects 的 `repo_mutation` 表示 mutable repo 的任何 git-visible write；
- `effects: []` Stage 不得产生 repo mutation；
- human_owner 的任何 unblock 都在下一 Cycle 生效；
- v1 不自动 rebase/merge Canonical 到 staging；
- Integration Apply 永远不是无人值守 Cycle 的动作；
- safety budget 到达后停止，不无限 rework。
