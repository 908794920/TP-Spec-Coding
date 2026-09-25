# 独立架构复审

正式 Architecture Review 是本角色的独立 capability，不再另造永久“评审动作角色”。它不是所有 L2/L3 的固定门禁；只有高风险、跨系统、数据库/安全架构变化、多实质路线、高不确定性或 human_owner 明确要求时触发。

正式 Review 必须：
- 使用与设计执行不同的 isolated execution context；
- 绑定被评审 Architecture subject digest；
- 只读 canonical Requirement、Architecture Artifact、Project Truth、Risk 和必要代码/数据事实；
- 不读取设计者私有 scratchpad；
- 定点回读争议事实；不要重新扫描整个仓库，不要从头重做 Architecture Design。

检查至少覆盖：需求/范围、可实施性、数据、并发、事务、幂等风险；权限、安全、隐私与敏感数据风险；接口/外部兼容、配置/运行风险；回滚、恢复或补偿策略；acceptance criteria 与验证策略。输出 `PASS / REVISE / BLOCKED` 与高价值 findings。Self-check 不等于正式 Review PASS。

设计方法在 [架构设计](../SKILL.md)，只按争议点回读。无独立执行上下文时如实标为自查或待正式复审，不把顺序重读冒称隔离；正式结果通过受支持的 trusted review 命令记录。
