# V5.3.5 Task 模板 — Record-first

这套模板服务于 **完成开发任务 + 事后溯源**。SQLite/event ledger 是权威记录；Markdown 只承载有业务价值的内容。

## 正常主链

`NEW → ACTIVE → COMPLETED`。真实依赖未解决时使用 `BLOCKED`；取消使用 `CANCELLED`。

`requirement / product / architecture / discovery / development / verification / delivery` 是 `current_phase` 事实，不是额外 Task 状态；实际阶段义务由当前 Runtime 路由及适用契约决定。

## 必要工件

新 Task 只预置：
- `task.md`：目标、范围、约束、关键决策；
- `acceptance.md`：需要明确验收项时使用；
- `status.yaml`：Runtime 投影。

其他模板均是**按需工件**：没有真实澄清、决策或架构内容时不创建空工件，也不因模板存在就强制生成。但当前路由、有效验收声明或正式结果确实要求的内容/证据不能以“按需”为由省略；是否满足结单义务由同源预检判断，不由文件是否有模板决定。

## 当前有效区（按需）

Task 与 canonical Requirement 中只有一处维护 `tp-spec:current` 标记之间的必要业务内容：当前目标、范围/非范围、有效决定和来源、验收与操作边界。已有 Requirement 承担需求时优先沿用它，Task 留短指针；没有 Requirement 的局部任务直接使用 Task。不新增文件、不为填写标记补问卷。模板只有空标题/注释时视为没有当前区。

旧决定留在标记外的历史区或已有 `requirement-decisions.md`，保留 `SUPERSEDED`、继任及依据；不得为精简删除唯一授权来源。接续和路由只摘取当前区并标明来源，不解析自然语言来授予权限。具体读取/限制见现有 [生命周期说明](../../docs/agents/tp-software-lifecycle.md)。

## Requirement Frontier（条件方法）

Requirement Frontier 只用于复杂 L2/L3 且多个关键决策存在前置依赖的需求；L0/L1、单一问题和无依赖决策仍走最小澄清路径，不增加固定问卷。它只复用 `requirement.md`、`requirement-clarifications.md` 和 `requirement-decisions.md`，不新增 Runtime state、workflow stage、Task Event、数据库或固定工件。

`blocking_open` 表示当前相关决策树中全部未解决的 blocking decision 和 blocking fact investigation，包括等待事实、等待前置 decision 和 Current Frontier；它不是当前可向用户提问的数量。Current Frontier 包含所有前置条件已解决、技术事实已调查且现在可以决定的未决 decision；Agent 只提出其中真正 blocking 的问题，或组成最小 coherent batch。依赖本轮答案的下游问题必须延后，事实问题先由 Agent 读取 Wiki、Knowledge、Memory、代码、配置和文档并做只读调查。

## 日常 Runtime 动作

- `task checkpoint`：一个角色完成一次有意义的阶段成果时最多记录一次；
- `task verify`：记录真实 `PASS / FAIL / NEEDS_FIX`，PASS 必须绑定真实 `evidence/*`；
- `task block / resume`：只记录真实 blocker；
- `task complete`：工作结束并自动生成 truthful final-result。

角色无需维护 generated、handoff、projection、front matter 机器字段，也无需调用 refresh/phase-exit/refs-validate 来解锁流程。

## 风险与评审

L0～L3 继续作为风险/查询标签，但不决定一条固定昂贵链路。独立 Architecture Review 只在高风险、跨系统、数据库/安全架构变化、多方案高不确定性或用户明确要求时触发；未触发不阻塞开发。

## 真实性边界

账本/状态完整性、未解决 blocker、高风险动作授权及真实验证继续按当前契约校验；实际结单还需核对当前适用的步骤、Work/候选、验收、证据、交付和知识/记忆结果。使用 `task complete --check` 读取同源预检，不把本模板概述当作全部门禁清单。

未测试不能写 PASS；human_owner 可对已按声明范围实际核验的人工/视觉项通过官方 `acceptance-override --mode accept` 留证，也可对未执行项 defer/waive，但不得伪装成 PASS。Owner 决策不解除无关 blocker。

知识/记忆评估不等于强制新增知识或保存可选 Memory。已采用新交付契约时，必要 Request/Result 缺失或失效不能靠填写 `DEFERRED` 放行；历史未采用记录不追补新义务。具体输入、复用与保存边界按 [Task 收敛契约](../../agents/tp-knowledge/references/task-convergence.md)执行。