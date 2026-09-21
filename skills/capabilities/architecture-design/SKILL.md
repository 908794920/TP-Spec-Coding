---
name: architecture-design
display_name: 架构设计与复审
version: 5.3.4
description: 在系统设计或独立架构复审有实际价值时读取；以真实代码、约束和成本决策，不扩大范围。
---

# 架构设计与复审

## 触发与输入
只有系统边界、模块、接口、兼容、可靠性、数据流、迁移或技术选型确有设计价值时读取。复杂度和成本不足以支持新增设计时，复用现有方案。技术实施拆解交技术主管，风险增加调查深度但不扩大授权范围。

## 工作方法
1. 先读取 canonical Requirement、确认 decision 和必要代码坐标。未知关键事实进入定向 `discovery`，不把推测写成设计前提；历史知识先做 canonical-first 定向检索，当前实现仍回 Wiki/Source Code 核验。
2. 依据 `governance/risk-rule.yaml` 判断真实影响与风险。代码量不是风险等级依据；未知影响不默认低风险。认证授权、敏感信息可见性、数据下发/附件、权限边界等至少按高风险安全信号处理。
3. 根据 `governance/planning-strategy.yaml` 选择 DIRECT 或深度规划。只有多条 materially different 且真实可行路线会显著改变风险、性能、兼容或维护成本时才 fan-out。
4. 设计前后检查：需求覆盖、模块/依赖、接口兼容、数据、权限/安全、并发/事务/幂等、消息/定时/缓存、配置/部署运行、失败恢复、回滚/补偿和可验证 acceptance criteria。
5. 有实际设计价值时形成 Architecture Artifact / ADR / tech design；简单确定任务允许只记录必要方案和风险，不为模板完整造文档。

## Knowledge Target
按 `governance/knowledge-rule.yaml` 判断是否出现值得长期沉淀的架构事实；需要时只标记合法 `knowledge_target` 与候选 evidence，真正 canonical/source/index 维护交 `tp-knowledge`。Knowledge Target 缺失默认只是 WARN，不是开发许可证。

## Deep Planning Capability（UltraPlan 模式）
UltraPlan 由本角色主持。候选方案必须独立读取事实、独立输出，不能共享中间结论；Architect 核验关键事实后收敛为唯一 decision-complete architecture。Orchestrator 只决定是否触发深度规划，不代替专业判断。

## Runtime
Task 已存在且形成有意义架构结果时最多一次 `task checkpoint --phase architecture`。独立 Review 只通过 trusted review command 记录，不用 phase/metadata 作为开发许可证。真实 blocker 才 block。

## 边界
规划/评审默认只读，不直接实现业务代码。生产读写、DML/DDL、不可逆动作继续遵守最小权限和动作级授权。业务目标、范围与风险接受改变交 human_owner/Product Manager。

## 按需复审
高风险、跨系统、数据库/安全架构变化、多实质路线、高不确定性或用户要求正式评审时，只读 [独立架构复审](references/architecture-review.md)。不将设计自查当作正式 PASS，不因 L2/L3 固定追加评审。工程交付规划复用 [交付计划](../delivery-planning/SKILL.md)。
