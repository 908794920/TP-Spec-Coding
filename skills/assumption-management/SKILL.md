---
name: assumption-management
version: 5.2.0
description: Use when a task relies on inferred business, technical, data, permission, compatibility, or risk facts. Keep assumptions explicit, evidence-linked, and unable to silently become confirmed facts.
---

# 假设管理 — V5.2.0 Record-first

## 目的
在不增加固定流程的前提下，把“已知事实”和“为了继续工作暂时采用的推断”分开，避免后续 Agent 把推测当成需求或授权。

## 方法
1. 对重要假设记录：来源、为什么需要、影响范围、验证方式、失效条件和当前状态。
2. 优先用项目知识、真实代码/配置、可复现实验或 human_owner 决策验证；不要用另一段 AI 推理替代证据。
3. 假设成立时转为确认事实并保留来源；不成立时只重做受影响的方案/实现/验收，不恢复长状态机。
4. 新证据、范围变化或时间失效使旧假设不再可靠时，明确标记冲突/过期，不静默覆盖历史。

## 硬边界
影响数据语义、权限/安全、接口兼容、生产动作、核心业务或验收结论的关键假设，不得作为默认事实继续编码；无法验证时形成真实 blocker 或请求 human_owner 决策。用户目标明确不等于高风险动作已授权。
