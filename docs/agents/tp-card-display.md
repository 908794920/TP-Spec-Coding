# tp-card-display

## 适用场景

用于明确查看 TP-Spec 全局、项目或正式任务卡片。它只消费官方 `CARD_DISPLAY` 结果，按当前宿主能力提供会话内、Web Artifact 或离线 HTML 展示。

## 执行入口

从产品入口 `tp-spec-coding` 直接路由到本 Agent。正常 Runtime 命令不生成或刷新卡片；只有用户明确请求才使用当前 Base 的卡片渲染入口和本 Agent 的展示契约。

## 能力导航

<!-- TP-SPEC:AGENT-TOPOLOGY-BEGIN -->
<!-- 由 scripts/check_document_navigation.py --write 根据 governance/role-catalog.yaml 生成。不要手工编辑本区块。 -->

- **Agent**：卡片展示调度 · `tp-card-display`
- **执行契约**：[`agents/tp-card-display/SKILL.md`](../../agents/tp-card-display/SKILL.md)
- **能力 ID**：`card.global`、`card.project`、`card.task`、`card.host-display`

<!-- TP-SPEC:AGENT-TOPOLOGY-END -->

## 相关文档

- [Agent / Role / Skill 总体模型](../AGENTS_AND_SKILLS.md)
- [文档地图](../README.md)
- [Role Catalog](../../governance/role-catalog.yaml)

## 边界

不读取或改写 Runtime 状态，不维护后台服务，不自行编造卡片 HTML。fragment 已生成、宿主 capability 已确认和实际 Host render 是三项独立事实；展示失败不改变已成功的 Runtime 命令。
