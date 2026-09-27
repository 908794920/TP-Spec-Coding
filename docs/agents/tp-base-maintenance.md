# tp-base-maintenance

## 适用场景

基座维护是薄领域入口，按本次目标加载安装健康、项目接入、契约迁移、工作台或自定义 SKILL 管理能力。已有安装优先核对事实并做最小修复，不重复初始化，也不把五项能力变成固定流水线。

## 执行入口

入口负责意图、对象、范围和转交；具体方法与安全边界由能力 SKILL 维护。统一入口收到用户级外部方法包的管理请求时进入本领域；使用某个外部方法完成业务工作时，仍由该业务所属领域判断采用。

## 能力导航

<!-- TP-SPEC:AGENT-TOPOLOGY-BEGIN -->
<!-- 由 scripts/check_document_navigation.py --write 根据 governance/role-catalog.yaml 生成。不要手工编辑本区块。 -->

- **Agent**：tp-基座维护 · `tp-base-maintenance`
- **执行契约**：[`agents/tp-base-maintenance/SKILL.md`](../../agents/tp-base-maintenance/SKILL.md)
- **能力 ID**：`base.configure`、`base.migrate`、`base.doctor`、`base.repair`、`base.workbench`、`skill.external.manage`

### Domain / Capability Skill

- `tp-base-installation` (conditional) → [`skills/base/tp-base-installation/SKILL.md`](../../skills/base/tp-base-installation/SKILL.md)
- `tp-base-project-integration` (conditional) → [`skills/base/tp-base-project-integration/SKILL.md`](../../skills/base/tp-base-project-integration/SKILL.md)
- `tp-base-contract-migration` (conditional) → [`skills/base/tp-base-contract-migration/SKILL.md`](../../skills/base/tp-base-contract-migration/SKILL.md)
- `tp-base-workbench` (conditional) → [`skills/base/tp-base-workbench/SKILL.md`](../../skills/base/tp-base-workbench/SKILL.md)
- `tp-external-skill-management` (conditional) → [`skills/base/tp-external-skill-management/SKILL.md`](../../skills/base/tp-external-skill-management/SKILL.md)

<!-- TP-SPEC:AGENT-TOPOLOGY-END -->

## 兼容更新与显式契约迁移

只读计划、备份、具体对象授权、提交和缓存恢复边界见 [契约升级迁移](../../skills/base/tp-base-contract-migration/SKILL.md)。Project contract、Binding 和运行中的工作台分别验证，不能只同步模板或查看顶部版本就宣布升级完成。

## 相关文档与边界

- [Getting Started](../GETTING_STARTED.md)、[文档地图](../README.md)、[Agent / Role / Skill](../AGENTS_AND_SKILLS.md)。
- [用户级外部 SKILL](../EXTERNAL_SKILLS.md)：被管理的外部包与 Base、项目独立；管理能力本身是 Base 内置 SKILL。
- [本地工作台](../WORKBENCH.md)：展示与读取共用目录，图的列布局不改变真实关系或使用效果。

修改业务代码与 Base 产品源码交软件工程领域，内容维护交 Wiki/Knowledge 领域。管理能力不拥有 Task state，也不因为节点存在就获得执行授权。
