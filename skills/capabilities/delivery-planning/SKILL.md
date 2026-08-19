---
name: delivery-planning
version: 5.2.4
description: Use when a task benefits from an explicit technical delivery plan. Produce an implementation-ready, risk-aware plan without creating mandatory workflow gates or handoff bookkeeping.
---

# 交付计划 — V5.2.4 Record-first

## 目的
把已理解的需求与代码事实收敛为可实施方案。简单、路径唯一的任务可以不单独写计划；复杂任务才投入更多规划成本。

## 方法
1. 基于确认事实、需求/非范围、关键 decision、代码证据和 acceptance criteria 规划；未确认关键前提不得伪装成确定方案。
2. 读取 `governance/planning-strategy.yaml`：默认 `DIRECT`；只有多条实质路线且比较有决策价值时采用 `COMPARATIVE`。
3. 明确修改模块/接口/数据/权限/事务/消息/定时任务/缓存/配置/部署等真实影响，不做与任务无关的模板式枚举。
4. 给出选择理由、包含/不包含范围、依赖、回滚/补偿、风险与验证策略；方案应能直接指导开发，而不是只描述原则。
5. 复杂任务可调用 `task-decomposition` 拆成可独立验证的工作项；简单任务避免为拆解而拆解。

## 完成判定
后续开发 AI 能知道：为什么这样改、允许改什么、关键风险是什么、如何自测/验收、什么时候必须停止扩大范围。无需额外交接工件、阶段许可证或专门结单阶段才算“交付完成”。
