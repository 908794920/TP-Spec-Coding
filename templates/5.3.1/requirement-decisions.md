---
artifact: requirement-decisions
task_id: ""
artifact_contract:
  version: 5.3.1
---

# Requirement Decisions（按需）

只记录真实发生、之后值得追溯的用户/业务决策；没有真实 decision 时不创建本工件。该表是业务记录，不是 Runtime 表、数据库状态或新的工作流阶段。

状态按需使用：`WAITING_FACT / WAITING_PREREQUISITE / FRONTIER / RESOLVED / DEFAULTED / SUPERSEDED / EXCLUDED`。只有低风险、可逆且不改变核心验收的小事项可以 `DEFAULTED`；数据、权限、安全、生产和核心业务未知不得静默默认。

| decision_id | 问题 | prerequisites | status | blocking | recommendation | human decision / 受控默认 | impact | evidence_refs | supersedes / history |
|---|---|---|---|---|---|---|---|---|---|

新证据推翻已记录结论时，保留原 decision 并将旧行标记为 `SUPERSEDED`；新增或重开继任 decision，在 `supersedes / history` 中关联原记录。不得覆盖历史，继任节点满足前置条件后重新进入 Current Frontier。
