# tp-software-lifecycle

## 适用场景

用于软件需求、架构、规划、开发、数据库、安全、测试、代码审查和交付。它提供完整软件生命周期能力，但实际任务只启用必要阶段与 Role。

## 执行入口

从产品入口 `tp-spec-coding` 路由到本 Agent。机器执行契约、Formal Role 与 Capability Skill 关系以下方自动生成区块和 Role Catalog 为准。

## 能力导航

<!-- TP-SPEC:AGENT-TOPOLOGY-BEGIN -->
<!-- 由 scripts/check_document_navigation.py --write 根据 governance/role-catalog.yaml 生成。不要手工编辑本区块。 -->

- **Agent**：tp-软件工程生命周期 · `tp-software-lifecycle`
- **执行契约**：[`agents/tp-software-lifecycle/SKILL.md`](../../agents/tp-software-lifecycle/SKILL.md)
- **能力 ID**：`lifecycle.routing`、`role.resolution`、`workflow.coordination`

### Formal Role

| Name | ID | 执行契约 |
| --- | --- | --- |
| tp-产品经理 | `tp-product-manager` | [`skills/roles/tp-product-manager/SKILL.md`](../../skills/roles/tp-product-manager/SKILL.md) |
| tp-软件架构师 | `tp-software-architect` | [`skills/roles/tp-software-architect/SKILL.md`](../../skills/roles/tp-software-architect/SKILL.md) |
| tp-技术主管 | `tp-tech-lead` | [`skills/roles/tp-tech-lead/SKILL.md`](../../skills/roles/tp-tech-lead/SKILL.md) |
| tp-安全工程师 | `tp-security-engineer` | [`skills/roles/tp-security-engineer/SKILL.md`](../../skills/roles/tp-security-engineer/SKILL.md) |
| tp-开发工程师 | `tp-development-engineer` | [`skills/roles/tp-development-engineer/SKILL.md`](../../skills/roles/tp-development-engineer/SKILL.md) |
| tp-数据库工程师 | `tp-database-engineer` | [`skills/roles/tp-database-engineer/SKILL.md`](../../skills/roles/tp-database-engineer/SKILL.md) |
| tp-测试工程师 | `tp-test-engineer` | [`skills/roles/tp-test-engineer/SKILL.md`](../../skills/roles/tp-test-engineer/SKILL.md) |
| tp-代码审查员 | `tp-code-reviewer` | [`skills/roles/tp-code-reviewer/SKILL.md`](../../skills/roles/tp-code-reviewer/SKILL.md) |
| tp-集成交付工程师 | `tp-integration-engineer` | [`skills/roles/tp-integration-engineer/SKILL.md`](../../skills/roles/tp-integration-engineer/SKILL.md) |

### Domain / Capability Skill

- `tp-card-display` (conditional) → [`skills/capabilities/tp-card-display/SKILL.md`](../../skills/capabilities/tp-card-display/SKILL.md)

<!-- TP-SPEC:AGENT-TOPOLOGY-END -->

## 相关文档

- [Agent / Role / Skill 总体模型](../AGENTS_AND_SKILLS.md)
- [安装与项目接入](../GETTING_STARTED.md)
- [Role Catalog](../../governance/role-catalog.yaml)

## 边界

Role 是能力集合，不是固定流程包。工作流按任务复杂度、风险和配置条件选择需要的能力；普通开发工作不应为了补齐非关键 Governance 记录而被回滚。
