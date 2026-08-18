---
name: task-decomposition
version: 5.2.4
description: Use when a technical plan is complex enough to benefit from explicit executable work items. Split by independently verifiable outcomes, dependencies, scope, and acceptance links.
---

# 任务拆解 — V5.2.4 Record-first

## 目的
让复杂任务可并行或可接续，而不是给每个小任务强制制造工作项表。确定性小改无需拆解。

## 方法
1. 按可独立验证的业务/技术结果拆分，不按文件数量机械拆分；每项关联一个或多个 AC/预期结果。
2. 标明责任角色、依赖、允许/禁止范围、关键路径、预期产出与验证方式。
3. 共享核心文件、依赖不清、数据/接口强耦合时优先串行；并行项避免重叠写路径。
4. 把必要的整合、迁移/回滚、跨模块验证显式纳入计划，不默认由“最后一个开发者”承担。
5. 上游方案、范围或关键假设变化时，只标记和重规划受影响项，不重新生成整套流程。

## 完成判定
另一个 Agent 仅凭当前需求/方案/工作项与代码事实即可开始执行，并知道何时应该停止扩大范围。无需额外交接协议、固定状态迁移或额外门禁。
