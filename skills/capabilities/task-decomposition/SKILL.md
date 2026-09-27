---
name: task-decomposition
display_name: 任务拆解
version: 5.3.5
description: Use when a technical plan is complex enough to benefit from explicit executable work items. Split by independently verifiable outcomes, dependencies, scope, and acceptance links.
---

# 任务拆解 — Record-first

## 目的
让复杂任务可并行或可接续，而不是给每个小任务强制制造工作项表。确定性小改无需拆解。

## Task / Work 与集成责任
一个独立需求对应父 Task，技术批次 Wxx 和当前范围内返修 FIXxx 归该 Task 的既有 Work。不能按名称猜父关系，不因新上下文、角色变化或版本批次再建顶层 Task；真正独立的需求才另建 Task。

优先 tracer-bullet / vertical slice：一个 Work 交付可验证的端到端结果，不按 DB/Backend/Frontend 机械切层。每个 Work 适合可接续的上下文；wide refactor 用 expand → 分批 migrate → contract，必要时使用 integration branch，最终绿灯仍绑定集成候选。

主 Agent 负责拆分、依赖、隔离安排、收回结果、冲突和授权后的集成；集成交付工程师负责专业收敛。每项明确父 Task、范围、AC、真实依赖、允许路径、责任角色/实际执行者、验证与结果；共享文件有一个明确写入所有者。Batch 与 worktree 不强制一一对应，可验证的 snapshot/Patch 也是结果，不要求每个 Work 自带 commit。

宿主有原生 spawn/message/wait 才使用，不自建消息总线。记录绑定或一句 cd 不是硬隔离；无相应能力时明确顺序执行与隔离限制。Work 不扩大父范围、不自行关闭父 Task，不自动 merge/push/删除工作树；这些动作需当次授权。范围内问题复用同一 Fix Work，父步骤等待后在原处复验；保留历史，失效 PASS 另行处理。登记范围、依赖、结果与 Fix 接续使用 [Work 结果契约](../../../docs/WORK_UNITS.md)；接口没有的事实保持未知，不伪造事件或直接改库。

步骤与 Work 不是同一对象。评估后的具体计划及其版本、步骤顺序、角色和既有 Work 关联，使用 [执行事实契约](../../../docs/EXECUTION_FACTS.md) 的正式入口；只调整未开始内容，既有发生记录不回写。

## 方法
1. 按可独立验证的业务/技术结果拆分，不按文件数量机械拆分；每项关联一个或多个 AC/预期结果。
2. 标明责任角色、依赖、允许/禁止范围、关键路径、预期产出与验证方式。
3. 共享核心文件、依赖不清、数据/接口强耦合时优先串行；并行项避免重叠写路径。
4. 把必要的整合、迁移/回滚、跨模块验证显式纳入计划，不默认由“最后一个开发者”承担。
5. 上游方案、范围或关键假设变化时，只标记和重规划受影响项，不重新生成整套流程。

## 完成判定
另一个 Agent 仅凭当前需求/方案/工作项与代码事实即可开始执行，并知道何时应该停止扩大范围。无需额外交接协议、固定状态迁移或额外门禁。

安全提案范围通过 [Security Change Authority](../../../docs/security-change-authority.md) 接入 Work 与步骤：沿用路径/AC 并按需声明 security_changes/effect_scope，未批准建议不进入实施步骤；调查和实施效果分开，计划与子 Agent 声明本身不是授权。
