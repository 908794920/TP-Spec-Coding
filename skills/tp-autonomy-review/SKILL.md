---
name: tp-autonomy-review
version: 5.2.4
description: 只读查看所有 Autonomy Profile 的 Inbox、Batch、Task、真实 Git commit/diff 与 Verification evidence；不写 Canonical。
---

# tp-autonomy-review

## 原则
Review 只读。Git/Task Runtime 是真源，AI 总结只是导航。

## 推荐下钻
```text
tp-spec autonomy review inbox --json
→ 所有 Profile：待决策 / 在途 / 失败 / 待 Integration

tp-spec autonomy review profile --profile <id> --json
→ 单 Profile 概览

tp-spec autonomy review batch --profile <id> --batch <BATCH> --json
→ Task→commit、files、+/-、repo range

tp-spec autonomy review task --profile <id> --task <TASK> --json
→ Task 级 commit/stat

用户明确要看代码时：
tp-spec autonomy review task ... --diff --json
→ 展开真实 Git diff
```

默认摘要不得主动输出大段源码/完整 diff；外部 Scheduler Digest 更必须脱敏。

## 用户决策
用户批准/拒绝等待 Task 时，使用 `tp-spec autonomy decide`。批准只写可信事实，不在当前交互会话顺势开发；下一 Cycle 才解除对应 Envelope。

如果用户从 Review 表达“这个 Batch 可以合并”，转 `tp-autonomy-integrate`，Review 本身不得写 Canonical。
