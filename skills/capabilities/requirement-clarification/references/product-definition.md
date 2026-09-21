# 产品定义与输入分流

从产品经理入口抽取；只有输入分流、产品定义或需求成形需要时读取。Frontier 仍仅按 [需求澄清](../SKILL.md) 的条件启用，视觉原型另读 [原型与交互设计](../../ui-prototype-design/SKILL.md)。

## 输入成熟度
1. **Raw Request**：先理解目标、用户价值与业务背景，再拆成 Requirement。
2. **半成熟文档/讨论**：综合已有结论，不重新 interview 用户；只补真正影响目标、范围、规则、风险或验收的缺口。
3. **Requirement Ready**：确认关键语义已经足够后直接交给 Software Lifecycle 建 Task，不重复做产品分析。
4. **明确 Bug / Code Task**：允许直接进入轻量 Task，不把 Product Manager 变成固定收费站。

本地需求材料若是 PDF、DOCX、XLS/XLSX、PPTX 等非 Markdown 文档，按需先使用 `tp-spec document convert --source <file> --output <file>.md` 做输入标准化，再读取转换后的 Markdown；转换能力直接由 Microsoft MarkItDown 提供。不要要求用户手工转格式，也不要因为转换就自动写入 Knowledge/canonical。

## 专业判断
- 严格区分：客户原始描述 / 确认事实 / AI 假设 / 待确认决策 / 未知现状。假设不得静默升级为事实。
- 优先通过项目事实、配置、代码坐标和 canonical Knowledge 定向核实；Knowledge 命中不能替代当前 Wiki/Source Code 事实。
- 明确 Goal、范围/非范围、业务规则、异常/边界、约束、验收条件（Acceptance Criteria）、来源、关键决策和真实 blocker。
- 复杂输入按用户价值和可验收行为做 requirement/feature decomposition，不按文件、数据库、前后端层机械拆需求。
- 产品形态确有设计价值时检查用户角色、入口、主要路径、页面/组件状态、字段语义、权限不足、空态、加载、错误、重复操作等异常场景，以及成功/失败等用户反馈和既有行为兼容。
- 只有会改变产品体验、业务含义或验收方式的选择才请求 human_owner；技术实现细节不能伪装成产品问题。
- 复杂 L2/L3 且多个关键决策存在前置依赖时，条件加载 `requirement-clarification` 的 Requirement Frontier：先调查事实，只向用户提出 Current Frontier 中当前可决定的 blocking 问题；依赖本轮答案的下游问题延后。
- L0/L1、单一问题和无依赖决策继续使用最小澄清路径，不增加固定问卷；Frontier 复用按需 Requirement 工件，不新增 Runtime state、workflow stage 或数据库结构。
- 当前有效范围与决定只维护在既有 canonical Task/Requirement 的一处当前区；技术事实冲突先调查，真实业务决定改变才请求用户。保留 `SUPERSEDED` 及替代依据，不把最新文本或 AI 假设升级为授权。按需读取 `requirement-clarification`，不全读历史或搬入长期项目规则。

## 输出
简单需求允许只形成短 canonical Requirement；复杂需求才按需形成正式 requirement/product artifact。没有真实澄清或决策就不创建空文档。

输出至少应让后续角色能够回答：
- 要做什么 / 不做什么；
- 为什么；
- 关键业务规则是什么；
- 怎样判断完成；
- 哪些事项仍真正阻塞。

## Pre-task 与 Runtime
需求分析允许发生在正式 Task 创建之前；没有 TaskId 合法。Requirement Ready 以后再创建 Task；不得为了 FACT/DECISION/账本提前建 Task。

Task 已存在且形成一次有意义需求/产品事实时，最多记录一次 `task checkpoint --phase requirement|product`。只有真实关键事实或 human decision 缺失才 `task block`。

## Knowledge / Memory
存在业务历史知识缺口时优先最小范围 `tp-spec knowledge search`，必要时再追 source/evidence。不得为了“更完整”扫描全 Knowledge/Task History。项目规则与可选经验使用[项目记忆捕获](../../tp-memory-capture/SKILL.md)，Memory 缺失不构成 blocker。
