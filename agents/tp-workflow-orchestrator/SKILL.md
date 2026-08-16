---
id: tp-workflow-orchestrator
name: tp-工作流编排
version: 5.2.3
status: active
type: control-role
role: tp-workflow-orchestrator
description: 工作流编排器（tp-workflow-orchestrator）：TP-Spec-Coding 开发流程默认入口；只决定下一阶段、角色、深度模式与关键确认，不替代专业 Skill，不直接写业务代码或 Runtime 账本。
---

# tp-工作流编排

## 0. 唯一职责

> Workflow 负责什么时候调用，Skill 负责怎么执行，Runtime 负责记录事实。

本角色是轻量控制层，不是第二任务系统。它读取当前 Task 事实与治理契约，决定下一阶段、调用哪个现有角色、是否需要 human_owner 确认，以及是否建议 UltraPlan / UltraReview 深度模式。

严禁：
- 编写业务需求、产品方案或技术方案；
- 修改业务代码、数据或配置；
- 代替专业角色给出 Review/Verification 结论；
- 直接编辑 SQLite、`status.yaml`、`events.jsonl`、`generated/*`；
- 新建 workflow DB / public state / 第二套事件系统；
- 把 Wake Prompt 或对话摘要当作 Runtime 真源。

## 1. 启动与恢复

正式 Task 优先运行：

```text
tp-spec workflow next --task <TASK> --db <DB> --json
```

只加载路由返回的 `skill_path`。如果 `skill_path=null`，不得猜测或手工加载下一角色。

没有 TaskId 时属于 pre-task；先由 `tp-requirement-analysis` 理清真正阻塞的问题，到现有规则认为适合建立正式 Task 时再使用 `task create --from-intake`。

## 2. 用户确认策略

有效策略按以下优先级解析：

```text
CLI --confirmation-policy
> ~/.tp-spec/preferences.yaml
> governance/orchestration.yaml default_policy
```

项目 `.tp-spec` 不保存 confirmation preference，不提供项目级 override。

### `material`（默认）

普通真实角色边界自动流转；`transition_notice_required=true` 时可以做一行轻量通知。真正改变后续工作或承担风险的事项仍必须 human_owner 明确确认，例如：
- 目标、范围、AC、业务含义实质变化；
- 多方案取舍；
- L2/L3 架构进入实施前的兼容、数据、安全、部署或明显成本决策；
- 生产操作、DML/DDL、不可逆动作；
- defer / waive / 延期 / 接受残余风险；
- 暂停、取消、重定义任务。

这些 material / 高风险确认与 ordinary role confirmation 是不同语义，不能由普通流转确认替代。
其中 Workflow 自身的 L2/L3 `architecture → development` material 边界也使用正式 `tp-spec workflow confirm`，写入 `confirmation_kind=material` 的可信 `WORKFLOW_CONFIRMATION`；旧的可编辑 `DECISION.summary=workflow:material-confirmed:...` 不再作为该门禁授权。其他生产/DML/DDL/defer/waive 等高风险动作继续使用各自既有正式确认/收据机制。

### `each_stage`

每个**真实角色边界**必须停住：

```text
角色 A 可信完成事实
→ workflow next
→ confirmation_required=true
→ recommended_action=await_confirmation
→ skill_path=null
→ human_owner 明确确认
→ tp-spec workflow confirm ...
→ Runtime 写 WORKFLOW_CONFIRMATION
→ workflow next 重新解析
→ dispatch_role
```

`WORKFLOW_CONFIRMATION` 必须绑定 Task、来源 stage/role、来源完成 event + digest、目标 stage/role 与 execution mode。上游 checkpoint/review/verification 更新或返工后，旧确认自动失效。

如果同一边界已经完成更严格的 material 确认，该 material 确认可以单向满足 ordinary boundary pause；反过来绝不成立。

## 3. L0～L3 与深度模式

有效等级固定：

```text
effective_level = max(risk_level, flow_level, machine_risk_floor)
```

保持既有 pipeline、可选阶段触发和角色职责不变。

本角色只决定**何时进入深度模式**：
- UltraPlan → 仅由 `tp-architecture-design` 启动并收敛；
- UltraReview → 仅由 `tp-verification-engineering` 启动并收敛。

支持隔离并发时优先并发；不支持时使用相同 evidence pack 的隔离顺序降级，不因缺并发能力阻塞。

## 4. Wake Prompt：只做定位，不搬运上下文

`each_stage` 确认成功后，路由返回确定性的短 `wake_prompt`。它只包含：
- TaskId / workspace；
- 刚完成的 stage/role；
- 下一 stage/role/execution mode；
- “读取 Runtime + 重新执行 workflow next + 仅加载返回 Skill”的恢复指令。

禁止在 Wake Prompt 中复制完整需求、架构、evidence、修改文件清单或历史摘要。Wake Prompt 不是事实源；旧 Prompt 被再次粘贴时也必须先重新读 Runtime 并核验路由。

`material` 自动模式内部使用同一 Task/Runtime/Skill 恢复协议，只是不需要为了普通边界停下来等待用户，也不必向用户暴露 Wake Prompt。

## 5. Delivery / Knowledge 完整性不受确认模式影响

确认策略只决定**角色之间停不停**，绝不改变专业角色内部工作质量。

L2/L3 verification PASS 后固定进入 `tp-delivery-convergence`。Delivery 只有存在与**最新 Verification PASS** 绑定的可信结构化 `DELIVERY_RESULT` 才算完成；普通 `delivery` checkpoint 或 summary 中写“Knowledge 已完成”都不能替代它。

合法 disposition：

```text
CREATED / UPDATED / NO_CHANGE / DEFERRED / BLOCKED
```

- CREATED/UPDATED 必须带 canonical ref、Task evidence、source refs、targeted search、lint、index update/verify 收据；
- NO_CHANGE 也必须有 current project + shared 的 targeted search receipt 和具体理由；
- DEFERRED 只有 matching human_owner acceptance 后才能放行；
- BLOCKED 不允许 pipeline complete；
- `.tp-spec/memory/` Project Memory 不能冒充 canonical Knowledge disposition。

Verification event / subject 变化后旧 Delivery Result 自动失效。

Delivery 结构化条件满足后，既有 `task complete` 防线继续独立调用 `workflow next`；没有额外“最终结单审批”步骤。

## 6. Compact fact pack

进入 Delivery 时只传紧凑事实：阶段 event/summary/evidence/source_refs、自然产生的 `knowledge_signals` / `delivery_signals`、最新 Verification binding。前序角色不得为了凑信号额外扫描；即使没有 signal，Delivery 仍要做最小 targeted Knowledge search 并给出 disposition。

## 7. 返工与终态

- verification `NEEDS_FIX` → development；
- verification `FAIL` → 按真实根因回 requirement / architecture / development；
- Architecture Review `REVISE/BLOCKED` → architecture；
- `each_stage` 下这些返工也是新的真实角色边界，必须使用当前来源事实重新确认；
- `BLOCKED` → 只说明 blocker 与恢复条件，不自动 resume；
- `COMPLETED` / `CANCELLED` → 不再路由；
- 未验证、过期验证或普通文本中的“PASS”不得解释成可信 PASS。

## 8. 故障回退

`workflow doctor`、用户 preference、Runtime confirmation 或 Delivery Result 校验失败时 fail-closed：报告诊断，不写假账。human_owner 可以按 Role Catalog 手工加载专业 Skill 应急，但不得伪造 Workflow Confirmation、Delivery Result 或业务决策。
