---
name: requirement-clarification
display_name: 需求澄清
version: 5.3.1
description: Use when a requirement is ambiguous, incomplete, conflicts with project facts, or contains material decisions with prerequisites. Ask only high-value questions and keep facts, assumptions, decisions, and unknowns distinct.
---

# 需求澄清 — V5.3.1 Record-first

## 目的

用尽量少的用户交互消除真正影响实现或验收的不确定性；能通过已有事实自行确认的内容不反问用户。Requirement Frontier 是本 Skill 内部的条件方法，不是新的 Skill、流程阶段或固定问卷。

## 基础方法

1. 将信息分为：确认事实、AI 假设、待确认决策、未知现状。
2. 围绕业务目标、用户/入口、范围/非范围、业务规则与异常、数据/权限/接口、兼容性和验收组织问题。
3. 先问会改变方案、范围、架构、风险、兼容性或验收的高价值问题；每个问题说明为什么现在需要决定、主要可选路径、推荐答案及影响。
4. 未知技术事实优先定向读取 Wiki、Knowledge、Memory、代码、配置或文档并执行只读调查，不把用户当作代码检索工具。
5. 用户确认后记录稳定 decision；不得把 AI 推荐或假设静默升级为 human decision。

## Requirement Frontier 的条件启用

默认仅在以下条件同时成立时启用：

- 当前是复杂 L2/L3；
- 多个关键决策存在前置依赖；
- 当前答案会改变范围、架构、风险、兼容性或验收。

用户明确要求系统性决策梳理时，应先完成风险、复杂度和依赖判断；明确请求不覆盖 L0/L1、单一问题或没有前置依赖的边界。普通 L0/L1、单一问题以及没有决策依赖的 L2/L3 不启用 Frontier，继续使用当前最小澄清路径，不增加固定问卷。

## 决策节点

只为当前需求实际相关的真实决策建节点。每个节点至少记录：

- `decision_id`：稳定 ID；
- `question`：需要作出的真实选择；
- `prerequisites`：必须先解决的 decision id；
- `status`：当前状态；
- `blocking`：是否阻塞 Requirement Ready；
- `recommendation` 与理由；
- `options`：主要可选路径；
- `decision`：human decision 或合法受控默认；
- `impact`：对范围、架构、风险、兼容性或验收的影响；
- `evidence_refs`：支撑事实与新证据来源；
- `supersedes` / `superseded_by`：历史替代关系。

允许的状态：

- `WAITING_FACT`：先由 Agent 调查技术事实，不向用户提问；
- `WAITING_PREREQUISITE`：前置 decision 尚未解决；
- `FRONTIER`：前置条件已解决，当前可以合理请求用户决定；
- `RESOLVED`：已有明确 human decision；
- `DEFAULTED`：仅 defaultable 小事项使用合法受控默认；
- `SUPERSEDED`：旧 decision 已被新证据推翻，保留历史；
- `EXCLUDED`：分支已被事实或上游 decision 排除，与当前需求无关。

`reopened` 是历史动作：新证据推翻既有结论时，保留原 decision 并标记 `SUPERSEDED`，创建或重开继任节点；其前置条件满足后重新加入 Current Frontier，不静默覆盖原记录。

## Current Frontier 算法

Current Frontier 是所有前置条件已解决、技术事实已完成调查、现在可以合理回答的未决决策。它不以 `blocking` 作为成员资格；`blocking` 只决定该节点是否必须在 Requirement Ready 前解决。

节点进入 Current Frontier 必须同时满足：

1. 状态尚未是 `RESOLVED / DEFAULTED / SUPERSEDED / EXCLUDED`；
2. 所有 `prerequisites` 已以 `RESOLVED / DEFAULTED` 合法结束；
3. 决策所需的技术事实已经完成调查；
4. 该问题现在由用户回答才有意义。

执行顺序：

1. 先定向调查 `WAITING_FACT`，记录事实来源和置信度。
2. 每次事实或上游 decision 变化后重新评估分支适用性；不再相关的下游节点标记为 `EXCLUDED`，不向用户提问，也不计入 `blocking_open`。
3. 重新计算依赖状态：前置未解决的节点保持 `WAITING_PREREQUISITE`，满足条件的未决节点进入 `FRONTIER`；`blocking` 只影响提问优先级与 Ready 阻塞。
4. 每轮只提出 Current Frontier 中真正 blocking 的问题，或把当前确实需要 human decision、相互独立且答案不依赖本轮其他答案的问题组成最小 coherent batch；低风险可逆的小事项优先使用合法受控默认。
5. 依赖本轮其他答案的下游问题必须延后，不得提前提出并要求用户基于未知前提猜测。
6. 每次收到 decision 或新事实后更新节点，再重新计算 Current Frontier；不得沿用旧 Frontier 快照。

## 事实与决策边界

- 文件、代码、配置、工具输出、Wiki、Knowledge、Memory 或只读调查可以确认的技术事实由 Agent 获取。
- 用户只负责真实业务选择、产品含义、风险接受、优先级和高风险授权。
- 每个 `FRONTIER` 问题必须给出问题标题、为什么现在需要决定、主要路径、推荐答案和对范围/风险/验收的影响；不得只说“请补充更多信息”。
- 数据、权限、安全、生产或核心业务的关键未知不得静默默认；只有低风险、可逆、不会改变核心验收的 defaultable 小事项可进入 `DEFAULTED`。

## 收敛与 fail-closed

`blocking_open` 统计当前相关决策树中**全部未解决**的 blocking decision 和 blocking fact investigation，包括 `WAITING_FACT`、`WAITING_PREREQUISITE` 与 `FRONTIER`；它不是 Current Frontier 的条目数。只要存在未解决的 blocking 节点，就必须保留 `requirement-clarifications.md` 并写入真实的 `blocking_open > 0`；`requirement-decisions.md` 不能替代该现有 Ready 门禁计数。

Requirement Ready 仅在以下条件成立时判定：

- `blocking_open == 0`；
- 所有相关 blocking decision 已 `RESOLVED` 或合法 `DEFAULTED`；
- 关键事实有来源，关键数据/权限/安全/生产/核心业务事项没有被默认；
- 无依赖本轮答案而尚未处理的下游 blocker。

若仍有 blocking 节点但 Current Frontier 为空，先检查缺失的 prerequisite、未知 decision id 或循环依赖；这是建模错误或尚未完成的事实调查，必须 fail-closed，不得判定 Requirement Ready。

不要求遍历无关分支，也不要求生成固定数量的澄清/决策文档。无真实 Frontier 或 decision 时不创建空工件。

## 架构边界

Requirement Frontier 只复用现有 Requirement、`requirement-clarifications.md` 与 `requirement-decisions.md`；不新增 Runtime state、Task Event、数据库结构、Formal Role、workflow stage 或第二事实源。
