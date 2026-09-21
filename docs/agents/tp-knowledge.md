# tp-knowledge

## 适用场景

用于 Knowledge 检索、摄取、任务收敛和审计。Knowledge 是可复用知识层，不替代 Runtime 的任务状态和事件账本。

## 执行入口

通过 `tp-spec-coding` 按用户意图路由。机器契约与能力 ID 以下方自动生成区块为准。

## 能力导航

<!-- TP-SPEC:AGENT-TOPOLOGY-BEGIN -->
<!-- 由 scripts/check_document_navigation.py --write 根据 governance/role-catalog.yaml 生成。不要手工编辑本区块。 -->

- **Agent**：tp-knowledge · `tp-knowledge`
- **执行契约**：[`agents/tp-knowledge/SKILL.md`](../../agents/tp-knowledge/SKILL.md)
- **能力 ID**：`knowledge.search`、`knowledge.ingest`、`knowledge.converge`、`knowledge.audit`

<!-- TP-SPEC:AGENT-TOPOLOGY-END -->

## 相关文档

- [Knowledge 子系统](../../knowledge/README.md)
- [文档地图](../README.md)
- [Agent / Role / Skill 总体模型](../AGENTS_AND_SKILLS.md)

## 边界

每个 Task 交付必须提炼有效需求与各步骤材料，无长期价值也需真实判断和定向检索依据；不强制新增知识。必要 Request/Result 缺失不能称已收敛，可选 Memory 未持久化按其自身边界披露。新 READY Delivery 对 L0–L3 均生成或复用绑定有效 Task 输入的 Request，与是否存在 knowledge_signals 无关。通过 task-inputs 定向读取，再用 task-converge --assessment 记录覆盖、检索和记忆判断；稳定输入重放不重复写入。无标记旧 Request/终态保留旧解释，不伪造过去的提炼；正式 Evidence 和任务状态仍以 Runtime 事实为准。
