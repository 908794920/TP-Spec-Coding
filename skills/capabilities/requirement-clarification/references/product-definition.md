# 产品定义与输入分流

需求经理牵头输入分流与需求成形；产品经理协作产品目标、价值、范围、优先级和体验目标。只有本次需要这些判断时读取。Frontier 仍仅按 [需求澄清](../SKILL.md) 的条件启用，具体视觉/交互原型交 UX 采用 [原型与交互设计](../../ui-prototype-design/SKILL.md)。

## 输入成熟度
1. **Raw Request**：先理解目标、用户价值与业务背景，再拆成 Requirement。
2. **半成熟文档/讨论**：综合已有结论，不重新 interview 用户；只补真正影响目标、范围、规则、风险或验收的缺口。
3. **Requirement Ready**：确认关键语义已经足够后交给 Software Lifecycle 按已有授权继续，并判断是否需要正式 Task，不重复做产品分析。
4. **明确 Bug / Code Task**：目标和范围明确的普通局部修改直接处理，不把产品经理、需求经理或建 Task 变成固定前置步骤。

## 专业判断
- 严格区分：客户原始描述 / 确认事实 / AI 假设 / 待确认决策 / 未知现状。假设不得静默升级为事实。
- 优先通过项目事实、配置、代码坐标和 canonical Knowledge 定向核实；Knowledge 命中不能替代当前 Wiki/Source Code 事实。
- 明确 Goal、范围/非范围、业务规则、异常/边界、约束、验收条件（Acceptance Criteria）、来源、关键决策和真实 blocker。
- 复杂输入按用户价值和可验收行为做 requirement/feature decomposition，不按文件、数据库、前后端层机械拆需求。
- 产品形态确有设计价值时检查用户角色、入口、主要路径、页面/组件状态、字段语义、权限不足、空态、加载、错误、重复操作等异常场景，以及成功/失败等用户反馈和既有行为兼容。
- 只有会改变产品体验、业务含义或验收方式的选择才请求 human_owner；技术实现细节不能伪装成产品问题。
- 默认在复杂 L2/L3 且多个关键决策存在前置依赖时，条件加载 `requirement-clarification` 的 Requirement Frontier；用户明确指定系统性梳理时按主 Skill 的条件处理，不以等级覆盖其请求。先调查事实，只向用户提出当前可决定的问题；依赖本轮答案的下游问题延后。
- 未明确要求系统性梳理的 L0/L1、单一问题和无依赖决策继续使用最小澄清路径，不增加固定问卷；Frontier 复用按需 Requirement 工件，不新增 Runtime state、workflow stage 或数据库结构。
- 当前有效范围与决定只维护在既有 canonical Task/Requirement 的一处当前区；技术事实冲突先调查，真实业务决定改变才请求用户。保留 `SUPERSEDED` 及替代依据，不把最新文本或 AI 假设升级为授权。按需读取 `requirement-clarification`，不全读历史或搬入长期项目规则。
- 推荐用完整行动结论；明确的“同意建议”沿用其完整含义，清楚回答不重复确认，真歧义只澄清该项。未知代码/配置先定向调查，无法仅凭文字确认的体验/性能按已有授权最小原型或测量，回来继续同一问题；未解 blocking 事实不判 Ready。

## 输出
简单需求允许只形成短 canonical Requirement；复杂需求才按需形成正式 requirement/product artifact。没有真实澄清或决策就不创建空文档。

输出至少应让后续角色能够回答：
- 要做什么 / 不做什么；
- 为什么；
- 关键业务规则是什么；
- 怎样判断完成；
- 哪些事项仍真正阻塞。

## Pre-task 与 Runtime
需求分析允许发生在正式 Task 创建之前；没有 TaskId 合法。是否建 Task 沿用生命周期入口与项目规则，Requirement Ready 本身不要求建 Task；不得为了 FACT/DECISION/账本或一次验证建 Task。已确定需要正式任务跟踪时，Ready 后按既有入口复用或建立 Task。

Task 已存在且形成一次有意义需求/产品事实时，由实际责任角色通过既有 checkpoint 记录对应 phase：需求经理维护需求事实，产品经理记录产品判断，UX 记录设计产出；同一批次不按角色数量复制事实。只有真实关键事实或 human decision 缺失才 `task block`。

## Knowledge / Memory
存在业务历史知识缺口时优先最小范围 `tp-spec knowledge search`，必要时再追 source/evidence。不得为了“更完整”扫描全 Knowledge/Task History。项目规则与可选经验使用[项目记忆捕获](../../tp-memory-capture/SKILL.md)，Memory 缺失不构成 blocker。

## 决策依赖澄清（Requirement Frontier）

仅在主 Skill 的 [条件启用](../SKILL.md#requirement-frontier-的条件启用) 成立时读取；普通单问题澄清不展开本节。以下细节沿用当前 Requirement 和现有工件，不增加流程。

## 决策节点

只为当前需求实际相关的真实决策建节点。每个节点至少记录：

- `decision_id`：稳定 ID；
- `question`：需要作出的真实选择；
- `prerequisites`：必须先解决的 decision id；
- `status`：当前状态；
- `blocking`：是否阻塞 Requirement Ready；
- `recommendation` 与理由、`options` 主要可选路径：有依据时填写，缺失时保留未知；
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
- 每个 `FRONTIER` 问题说明具体缺失的业务选择、为什么现在需要决定和对范围/风险/验收的影响；有事实依据时给出主要路径与完整推荐行动结论。技术事实先调查，未知业务值不为填满选项或推荐而编造，也不笼统要求“补充更多信息”。
- 数据、权限、安全、生产或核心业务的关键未知不得静默默认；只有低风险、可逆、不会改变核心验收的 defaultable 小事项可进入 `DEFAULTED`。

## 收敛与 fail-closed

`blocking_open` 统计当前相关决策树中**全部未解决**的 blocking decision 和 blocking fact investigation，包括 `WAITING_FACT`、`WAITING_PREREQUISITE` 与 `FRONTIER`；它不是 Current Frontier 的条目数。只要存在未解决的 blocking 节点，就必须保留 `requirement-clarifications.md` 并写入真实的 `blocking_open > 0`；`requirement-decisions.md` 不能替代该现有 Ready 门禁计数。

Requirement Ready 仅在以下条件成立时判定：

- `blocking_open == 0`；
- 所有相关 blocking decision 已 `RESOLVED` 或合法 `DEFAULTED`；
- 关键事实有来源，关键数据/权限/安全/生产/核心业务事项没有被默认；
- 无依赖本轮答案而尚未处理的下游 blocker。

若仍有 blocking 节点但 Current Frontier 为空，沿已知事实调查或前置依赖继续推进；只有阻塞链无法解释或无法推进时，检查缺失的 prerequisite、未知 decision id 或循环依赖。正常等待与建模错误都不满足 Requirement Ready，不能把 Frontier 为空当作收敛。

不要求遍历无关分支，也不要求生成固定数量的澄清/决策文档。无真实 Frontier 或 decision 时不创建空工件。

## 架构边界

Requirement Frontier 只复用现有 Requirement、`requirement-clarifications.md` 与 `requirement-decisions.md`；不新增 Runtime state、Task Event、数据库结构、Formal Role、workflow stage 或第二事实源。
