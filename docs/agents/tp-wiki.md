# tp-wiki

## 适用场景

用于代码 Wiki 的搜索、计划、更新和审计，帮助 AI 在大型代码库中建立可追溯的源码理解链。

## 执行入口

通过 `tp-spec-coding` 按 Wiki 意图进入。机器契约与能力 ID 以下方自动生成区块为准。

## 能力导航

<!-- TP-SPEC:AGENT-TOPOLOGY-BEGIN -->
<!-- 由 scripts/check_document_navigation.py --write 根据 governance/role-catalog.yaml 生成。不要手工编辑本区块。 -->

- **Agent**：tp-wiki · `tp-wiki`
- **执行契约**：[`agents/tp-wiki/SKILL.md`](../../agents/tp-wiki/SKILL.md)
- **能力 ID**：`wiki.plan`、`wiki.update`、`wiki.audit`、`wiki.search`

<!-- TP-SPEC:AGENT-TOPOLOGY-END -->

## 相关文档

- [Wiki 子系统](../../wiki/README.md)
- [文档地图](../README.md)
- [Getting Started](../GETTING_STARTED.md)

## 边界

Wiki 是源码理解和导航投影，不是 Runtime 状态源。更新必须能回到真实源码核验，不用 Wiki 文案覆盖代码事实。
