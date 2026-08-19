---
name: requirement-clarification
version: 5.2.5
description: Use when a requirement is ambiguous, incomplete, or conflicts with project facts. Ask only high-value questions and keep facts, assumptions, decisions, and unknowns distinct.
---

# 需求澄清 — V5.2.5 Record-first

## 目的
用尽量少的用户交互消除真正影响实现或验收的不确定性；能通过已有事实自行确认的内容不反问用户。

## 方法
1. 将信息分为：确认事实、AI 假设、待确认决策、未知现状。
2. 围绕业务目标、用户/入口、范围/非范围、业务规则与异常、数据/权限/接口、兼容性和验收组织问题。
3. 先问会改变方案、风险、范围或验收的高价值问题；一个问题说明为什么需要确认、主要影响和可选路径。
4. 未知技术现状优先定向读取项目知识/代码/配置或做只读调查，不把用户当作代码检索工具。
5. 用户确认后记录稳定 decision；后续角色读取而不是重新猜测。新证据与 decision 冲突时重新请求决策并保留历史来源。

## 收敛
blocking 问题关闭或有明确 human decision 后即可继续；defaultable 小事项可记录受控默认，不要求生成固定澄清文档。影响数据、权限、安全、生产或核心业务的关键未知不得静默默认。
