---
name: implementation-control
display_name: 实现过程控制
version: 5.3.0
description: Use while implementing an TP-Spec-Coding task when code changes, refactoring, reuse decisions, debugging, or scope control are required.
---

# 实现过程控制 — V5.3.0 Record-first

## 目的
把“先理解、再最小修改、验证后再继续”变成默认开发习惯。目标不是写更多代码，而是用最小、可读、可验证的改动解决当前真实问题。

## 默认开发内循环

### THINK
1. 找到真实入口、当前实现和主要调用链，明确这一轮可验证成功标准与关键假设。
2. 检查静态调用、Spring/反射、XML/配置、模板/JSP、消息/定时任务、序列化和外部契约，形成 Usage Footprint；全文搜索无引用不等于可安全删除。
3. 代码事实与 Requirement/Architecture 冲突时先修正 canonical 文档，不把已证伪前提留给后续 AI。

### SIMPLIFY
4. 搜索相似实现、已有 helper/service/component/test utility，按 `直接复用 → 修改现有实现 → 替换/删除重复实现 → 新增最小实现` 选择。
5. 新 abstraction/config/dependency/compatibility path 必须对应当前真实 caller、variation、requirement 或已证明风险；“以后可能用”不是理由。
6. 如果不修改已经足够满足需求，明确选择不修改。

### SURGICAL CHANGE
7. 在 `implementation.md`（复杂任务）或五行短路线（简单任务）记录允许修改、明确不做和变更理由映射。
8. 一轮只做一个 smallest coherent diff；不顺手格式化、重构或清理与 Task 无关的旧代码。
9. 只清理由本次改动制造的 orphan、失效兼容路径、无调用 helper、重复测试和调试残留。

### GOAL-DRIVEN VERIFY
10. 写完后重新阅读完整 Diff，确认每个 changed file 能映射到 AC、Finding、必要 Migration 或本次清理。
11. 测试保护真实行为，不以测试数量/覆盖率制造信心；正式回归测试与临时诊断测试分开。
12. 运行与成功标准对应的最小充分验证，记录真实 Evidence；当前轮通过后再进入下一轮或 checkpoint。

## 文件归属
- 产品运行、部署、长期维护所需资产：遵循目标仓库既有目录，例如正式 Migration SQL、Mapper XML、长期回归测试、产品 README。
- 当前 Task 的方案、调查、路线和事实修正：放 `.tp-spec/tasks/<TASK-ID>/`。
- 当前 Task 的测试/验收证据：放 `evidence/`，例如验证 SQL、日志、截图、测试报告。
- 一次性夹具、Mock、中间输出：使用 TP-Spec 受控系统临时目录，不污染产品仓库。
- SQL 不按扩展名一刀切：随产品交付的 SQL 属于产品资产；一次性调查/验证 SQL 属于 Task Evidence。

## 反模式
遇到“顺手优化”“以后扩展”“多写测试更保险”等合理化时，按需读取 `references/anti-patterns.md`。

## 数据边界
任务范围内 dev/test 只读调查允许；production read 必须用户明确确认并最小权限；DML/DDL/生产写/删除或不可逆动作必须动作级、环境级授权并保留结果/回滚证据。

## Runtime
只在有意义里程碑使用 `task checkpoint`；真实 blocker 用 `task block/resume`。不要手工维护 status/events 或第二套状态；Runtime 负责机器事实。
