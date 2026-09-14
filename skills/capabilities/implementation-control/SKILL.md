---
name: implementation-control
display_name: 实现过程控制
version: 5.3.2
description: Use while implementing an TP-Spec-Coding task when code changes, refactoring, reuse decisions, debugging, or scope control are required.
---

# 实现过程控制 — V5.3.2 Record-first

## 目的
把“先理解、再最小修改、验证后再继续”变成默认开发习惯。目标不是写更多代码，而是用最小、可读、可验证的改动解决当前真实问题。

## 按当前影响选用的方法

这是方法清单，不是每轮必跑步骤；按触发条件选用，不要求逐项回答或生成固定路线。已确认的局部反馈留在原 Task，围绕本轮目标、当前事实、获准范围和完成/停止条件行动；父 Task 为 L2/L3 不改变本轮边界。无需修改是合法结论。

### THINK — 事实先于简化
找到真实入口、当前实现、调用链、可验证目标和关键假设。仅相关事实存在缺口时定向调查，不为凑清单扫描全仓。

| 触发条件 | 必要核对 |
| --- | --- |
| 删除、接口、配置驱动或共享行为改动 | 形成必要的 Usage Footprint：真实静态调用及适用的 Spring/反射、XML/配置、模板/JSP、消息/定时任务、序列化、外部契约；全文搜索无引用不等于可安全删除。 |
| 代码/证据与原方案冲突 | 查明已证伪前提，修正 canonical 当前结论并保留来源；产品错误不反向改成需求，业务取舍或授权变化才交用户决定。 |
| 共享、安全、数据或关键契约风险 | 核对真实消费方与专项风险；Diff 小不等于低风险，影响不明不盲猜。 |

### SIMPLIFY — 选择最小合理实现
事实明确后再选路线：当前功能是否真的需要存在？当前代码库是否已有可直接复用实现，或只需修改现有实现？没有合适现成路径时，再比较 JDK / 标准库、框架或平台原生能力、项目已安装依赖、最简单的局部表达；最后才新增满足当前需求的最小实现。找到充分方案即停止无关比较，不逐层写报告。

保持 `直接复用 → 修改现有实现 → 替换/删除重复实现`；新 abstraction/config/dependency/compatibility path 必须对应当前真实 caller、variation、requirement 或已证明风险，不为以后可能使用预留。Solution Ladder 不得削弱**信任边界输入验证、防数据丢失的错误处理、安全、权限和隐私、可访问性、事务、一致性、并发、幂等、必要兼容性和最小充分验证**。

### SURGICAL CHANGE — 只改必要范围
一轮只做 smallest coherent diff，保护用户已有修改，不顺手格式化/重构旧代码。只有确需保存复杂实施约束时才维护 `implementation.md` 的相关段；简单反馈复用批次摘要，不另造路线或空阶段工件。只清理由本次改动制造的 orphan、重复路径、失效兼容、无调用 helper、调试残留和低价值平行测试。

### GOAL-DRIVEN VERIFY — 验证并正确停止
重新阅读完整 Diff，使 changed file 对应 AC、Finding、必要 Migration 或本次清理。在既有授权内复用/扩展已有测试，按 Diff、调用方、当前 AC 和风险做最小充分验证，不默认全量构建/回归，不用数量或覆盖率替代真实行为。持久回归与临时诊断分开；涉及页面/动效/流程时按需读取 [testing-strategy](../testing-strategy/SKILL.md)，静态契约不等于真实视觉/流程通过。

留真实 Evidence、未运行边界和复验点后停在本批约定位置；只有新问题或有效触发才继续。缺权限/环境保持等待，不用无 Finding 的开发代替验收，也不把局部通过写成整任务 PASS。

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
