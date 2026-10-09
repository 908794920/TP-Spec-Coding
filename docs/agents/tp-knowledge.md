# tp-knowledge

## 适用场景

用于 Knowledge 检索、摄取、任务收敛和审计。Knowledge 是可复用知识层，不替代 Runtime 的任务状态和事件账本。

## 执行入口

通过 `tp-spec-coding` 按用户意图路由。领域 Agent 是薄入口，只选择本次需要的 SKILL；检索、任务收敛、日常维护、外部接入、旧库标准化和定时维护各自按需加载，不默认执行整条维护链。机器契约与能力 ID 以下方自动生成区块为准。

## 能力导航

<!-- TP-SPEC:AGENT-TOPOLOGY-BEGIN -->
<!-- 由 scripts/check_document_navigation.py --write 根据 governance/role-catalog.yaml 生成。不要手工编辑本区块。 -->

- **Agent**：tp-knowledge · `tp-knowledge`
- **执行契约**：[`agents/tp-knowledge/SKILL.md`](../../agents/tp-knowledge/SKILL.md)
- **能力 ID**：`knowledge.search`、`knowledge.ingest`、`knowledge.converge`、`knowledge.audit`

### Domain / Capability Skill

- `tp-knowledge-retrieval` (conditional) → [`skills/knowledge/tp-knowledge-retrieval/SKILL.md`](../../skills/knowledge/tp-knowledge-retrieval/SKILL.md)
- `tp-knowledge-task-convergence` (conditional) → [`skills/knowledge/tp-knowledge-task-convergence/SKILL.md`](../../skills/knowledge/tp-knowledge-task-convergence/SKILL.md)
- `tp-knowledge-maintenance` (conditional) → [`skills/knowledge/tp-knowledge-maintenance/SKILL.md`](../../skills/knowledge/tp-knowledge-maintenance/SKILL.md)
- `tp-knowledge-ingestion` (conditional) → [`skills/knowledge/tp-knowledge-ingestion/SKILL.md`](../../skills/knowledge/tp-knowledge-ingestion/SKILL.md)
- `tp-knowledge-normalization` (conditional) → [`skills/knowledge/tp-knowledge-normalization/SKILL.md`](../../skills/knowledge/tp-knowledge-normalization/SKILL.md)
- `tp-knowledge-scheduled-maintenance` (conditional) → [`skills/knowledge/tp-knowledge-scheduled-maintenance/SKILL.md`](../../skills/knowledge/tp-knowledge-scheduled-maintenance/SKILL.md)

<!-- TP-SPEC:AGENT-TOPOLOGY-END -->

## 相关文档

- [Knowledge 子系统](../../knowledge/README.md)
- [文档地图](../README.md)
- [Agent / Role / Skill 总体模型](../AGENTS_AND_SKILLS.md)

## 边界

standard Task 交付必须提炼有效需求与各步骤材料，无长期价值也需真实判断和定向检索依据；不强制新增知识。必要 Request/Result 缺失不能称已收敛，可选 Memory 未持久化按其自身边界披露。standard 新 READY Delivery 按适用的 L0–L3 义务生成或复用绑定有效 Task 输入的 Request，与是否存在 knowledge_signals 无关。quick 不自动要求知识/记忆收敛或消费计数。standard 通过 task-inputs 定向读取，再用 task-converge --assessment 记录覆盖、检索和记忆判断；稳定输入重放不重复写入。无标记旧 Request/终态保留旧解释，不伪造过去的提炼；正式 Evidence 和任务状态仍以 Runtime 事实为准。
