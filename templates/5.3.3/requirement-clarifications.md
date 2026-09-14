---
artifact: requirement-clarifications
task_id: ""
artifact_contract:
  version: 5.3.3
blocking_open: 0
---

# Requirement Clarifications（按需）

只记录 AI 无法合理推导、且会实际影响实现或验收的问题。没有真实澄清项时不创建本工件。

`blocking_open` 统计当前相关决策树中**全部未解决**的 blocking decision 和 blocking fact investigation，包括 `WAITING_FACT`、`WAITING_PREREQUISITE` 与 `FRONTIER`；它不是 Current Frontier 的条目数。只要还有未解决的 blocking 节点，就必须保留本工件并填写真实正整数；决策历史表不能替代该计数。

## Fact Investigation

`WAITING_FACT` 由 Agent 先通过 Wiki、Knowledge、Memory、代码、配置、文档或其他只读调查解决，不把技术事实转嫁给用户。

| decision_id | 待调查技术事实 | status | evidence_refs | 置信度 | 调查结论 |
|---|---|---|---|---|---|

## Current Frontier

只向用户展示 `FRONTIER`，不展示仍在等待事实或前置 decision 的问题。实际只提出其中真正 blocking 的问题，或组成一个答案彼此独立的最小 coherent batch。每个问题必须说明为什么现在决定、主要路径、推荐答案以及对范围、风险或验收的影响。

| decision_id | blocking | 问题 | 为什么现在需要决定 | 主要路径 | 推荐答案 | 范围/风险/验收影响 |
|---|---|---|---|---|---|---|

## Deferred Decisions

`WAITING_PREREQUISITE` 只记录、不提前提问。依赖本轮其他答案的下游问题必须等待本轮 decision 后重新计算 Current Frontier。

| decision_id | prerequisites | status | 延后原因 |
|---|---|---|---|
