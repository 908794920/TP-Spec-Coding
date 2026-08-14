---
name: implementation-control
version: 5.2.1
description: Use while implementing an TP-Spec-Coding task to control scope, evidence, database safety, and discovery escalation without making bookkeeping part of development.
---

# 实现过程控制 — V5.2.1 Record-first

## 目的
让开发集中在真实代码与测试，同时防止范围膨胀、未授权数据操作和“实现者自我验收”。

## 方法
1. 从确认需求、decision、方案和 acceptance criteria 得到最小合理修改范围；不要因为顺手优化扩大无关文件/接口/数据范围。
2. 先建立可复现基线，再小步修改；每个关键修改应能回到需求/AC/缺陷或技术风险。
3. 发现需求、方案、代码事实冲突或需要范围外改动时停止扩大修改，形成明确 finding/blocker 后再决定。
4. 调试失败用 `systematic-debugging`：固定复现 → 可证伪假设 → 最小证据 → 根因 → 最小修复 → 回归。
5. 有价值的测试、命令或数据证据写 `evidence/`；`implementation.md` 仅在复杂实施确实需要解释时生成。

## 数据边界
任务范围内 dev/test 只读调查允许；production read 必须用户明确确认并最小权限；DML/DDL/生产写/删除或不可逆动作必须动作级、环境级授权并保留结果/回滚证据。

## Runtime
只在有意义里程碑使用 `task checkpoint`；真实 blocker 用 `task block/resume`。不要手工维护兼容交接协议、机器投影或 status/events；这些由 Runtime 负责。
