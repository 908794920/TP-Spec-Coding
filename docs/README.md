# TP-Spec-Coding 文档

这里是当前发布面的统一文档地图。执行契约以 [`governance/role-catalog.yaml`](../governance/role-catalog.yaml) 与对应 `SKILL.md` 为准；本文档只负责帮助用户选择入口，不复制第二套能力定义。

## 先看这里

- 第一次接触项目：先读根目录 [`README.md`](../README.md)。
- 安装、机器配置、项目接入和排错：读 [`GETTING_STARTED.md`](GETTING_STARTED.md)。
- 理解 Agent / Role / Skill / Runtime：读 [`AGENTS_AND_SKILLS.md`](AGENTS_AND_SKILLS.md)。
- 升级到 V5.3.3 的在途项目/Task：读 [`MIGRATION_V529.md`](MIGRATION_V529.md)。

## 按 Agent 选择入口

<!-- TP-SPEC:AGENT-MAP-BEGIN -->
<!-- 由 scripts/check_document_navigation.py --write 根据 governance/role-catalog.yaml 生成。不要手工编辑本区块。 -->

| Domain Agent | ID | 导航 | 执行契约 |
| --- | --- | --- | --- |
| tp-软件工程生命周期 | `tp-software-lifecycle` | [打开](./agents/tp-software-lifecycle.md) | [`agents/tp-software-lifecycle/SKILL.md`](../agents/tp-software-lifecycle/SKILL.md) |
| 卡片展示调度 | `tp-card-display` | [打开](./agents/tp-card-display.md) | [`agents/tp-card-display/SKILL.md`](../agents/tp-card-display/SKILL.md) |
| tp-项目自治维护 | `tp-project-autonomy` | [打开](./agents/tp-project-autonomy.md) | [`agents/tp-project-autonomy/SKILL.md`](../agents/tp-project-autonomy/SKILL.md) |
| tp-基座维护 | `tp-base-maintenance` | [打开](./agents/tp-base-maintenance.md) | [`agents/tp-base-maintenance/SKILL.md`](../agents/tp-base-maintenance/SKILL.md) |
| tp-knowledge | `tp-knowledge` | [打开](./agents/tp-knowledge.md) | [`agents/tp-knowledge/SKILL.md`](../agents/tp-knowledge/SKILL.md) |
| tp-wiki | `tp-wiki` | [打开](./agents/tp-wiki.md) | [`agents/tp-wiki/SKILL.md`](../agents/tp-wiki/SKILL.md) |

<!-- TP-SPEC:AGENT-MAP-END -->

## 第一次安装与项目接入

人工安装、已有安装升级、Base/Wiki/Knowledge 路径配置、项目绑定和 doctor 流程统一见 [`GETTING_STARTED.md`](GETTING_STARTED.md)。机器路径属于安装配置，不应写进公共仓库文档或业务项目源码。

## 软件工程 Role 导航

软件研发任务先进入 [`tp-software-lifecycle`](agents/tp-software-lifecycle.md)。生命周期定义完整能力上限，实际任务按风险、上下文和工作流策略选择需要的 Role，不要求每个任务机械走完整流程。

## Wiki / Knowledge / Autonomy

- Wiki：[`tp-wiki`](agents/tp-wiki.md) 与 [`wiki/README.md`](../wiki/README.md)
- Knowledge：[`tp-knowledge`](agents/tp-knowledge.md) 与 [`knowledge/README.md`](../knowledge/README.md)
- 项目自治：[`tp-project-autonomy`](agents/tp-project-autonomy.md) 与 [`automation/autonomy/README.md`](../automation/autonomy/README.md)

## 架构、Runtime 与治理

Runtime 的任务状态、事件、Evidence 与工作流事实由 CLI/Runtime 自动维护。治理记录是执行副产物，不要求 AI 为日常工作手写大量状态文档。当前架构关系见 [`AGENTS_AND_SKILLS.md`](AGENTS_AND_SKILLS.md)。

## 维护、测试与发布

Base 维护入口见 [`tp-base-maintenance`](agents/tp-base-maintenance.md)。自动化总入口见 [`automation/README.md`](../automation/README.md)。发布时运行仓库既有 Full/Release 门禁，文档导航检查属于发布面检查，不参与 Runtime 路由。

## 历史与过程文档政策

当前发布面只保留仍可执行、仍需用户阅读的文档。临时设计、迁移调查、一次性实施计划和机器生成过程报告不作为长期文档入口；已发布变化由 [`CHANGELOG.md`](../CHANGELOG.md) 记录。
