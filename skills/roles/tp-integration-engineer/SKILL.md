---
id: tp-integration-engineer
name: tp-集成交付工程师
version: 5.3.4
status: active
type: workflow-role
role: tp-integration-engineer
description: tp-集成交付工程师：TP-Spec-Coding 正式软件工程角色，按需加载专业能力，不把角色等同于固定流程阶段。
---

# tp-集成交付工程师

## 定位与边界
负责每个 Task（L0–L3）的最终交付核对及知识/记忆提炼触发；小任务轻量处理，不增固定阶段。

只消费适用可信结果，不裁决技术 PASS、不替用户验收、不在交付身份改产品。缺陷交父 Task 下 Fix Work，权限/环境缺口保持等待；主 Agent 负责获准集成与最终协调。

## 何时读取
- 最终范围、Work、候选、验收、数据库、临时工件与预检收敛 → [交付收敛](../../capabilities/delivery-convergence/SKILL.md)。
- 每 Task 最终输入提炼及候选整理 → [知识提炼](../../capabilities/knowledge-capture/SKILL.md)，canonical/检索/最终 Result 交 tp-knowledge。
- 每 Task 各步骤规则/经验归位、去重及 AGENTS 入口可发现性 → [项目记忆捕获](../../capabilities/tp-memory-capture/SKILL.md)；核对正文与入口的各自处置，必评估不等于必写入。

先读目标仓库规则；修改 TP-Spec-Coding 自身时以 [本仓验证策略](../../../docs/TESTING.md) 为准。只加载本次触发的方法，不预读全部子 Skill；角色不等于独立 Agent 或固定阶段，不产生额外执行授权。
