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

知识收敛是工作副产物。缺少非关键 Knowledge 记录不能轻易阻塞已完成的真实开发工作；正式 Evidence 和任务状态仍以 Runtime 事实为准。
