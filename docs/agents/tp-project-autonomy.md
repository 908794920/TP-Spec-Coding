# tp-project-autonomy

## 适用场景

用于长期项目的候选发现、自治周期、独立审查和安全集成。自治能力按配置、风险和 human_owner 边界启用，不是所有项目默认开启的固定后台流程。

## 执行入口

通过 `tp-spec-coding` 按自治维护意图进入。具体 Domain Skill 由 Role Catalog 自动投影到下方区块。

## 能力导航

<!-- TP-SPEC:AGENT-TOPOLOGY-BEGIN -->
<!-- 由 scripts/check_document_navigation.py --write 根据 governance/role-catalog.yaml 生成。不要手工编辑本区块。 -->

- **Agent**：tp-项目自治维护 · `tp-project-autonomy`
- **执行契约**：[`agents/tp-project-autonomy/SKILL.md`](../../agents/tp-project-autonomy/SKILL.md)
- **能力 ID**：`autonomy.discovery`、`autonomy.cycle`、`autonomy.review`、`autonomy.integration`

### Domain / Capability Skill

- `tp-autonomy-setup` (conditional) → [`skills/autonomy/tp-autonomy-setup/SKILL.md`](../../skills/autonomy/tp-autonomy-setup/SKILL.md)
- `tp-autonomy-cycle` (conditional) → [`skills/autonomy/tp-autonomy-cycle/SKILL.md`](../../skills/autonomy/tp-autonomy-cycle/SKILL.md)
- `tp-autonomy-review` (conditional) → [`skills/autonomy/tp-autonomy-review/SKILL.md`](../../skills/autonomy/tp-autonomy-review/SKILL.md)
- `tp-autonomy-integrate` (conditional) → [`skills/autonomy/tp-autonomy-integrate/SKILL.md`](../../skills/autonomy/tp-autonomy-integrate/SKILL.md)

<!-- TP-SPEC:AGENT-TOPOLOGY-END -->

## 相关文档

- [Autonomy 子系统](../../automation/autonomy/README.md)
- [自动化总入口](../../automation/README.md)
- [文档地图](../README.md)

## 边界

自治发现、执行、Review 和集成保持职责分离；高风险效果仍由 human_owner 控制。自治 Governance 记录应由 Runtime/CLI 自动产生，而不是要求 Agent 手写周期报告驱动状态。
