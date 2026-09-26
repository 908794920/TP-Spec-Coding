# TP-Spec-Coding 文档

这里是当前发布面的统一文档地图。内置执行契约以 [`governance/role-catalog.yaml`](../governance/role-catalog.yaml) 与对应 `SKILL.md` 为准；本文档只负责帮助用户选择入口，不复制第二套能力定义。

## 先看这里

- 第一次接触项目：先读根目录 [`README.md`](../README.md)。
- 安装、机器配置、项目接入和排错：读 [`GETTING_STARTED.md`](GETTING_STARTED.md)。
- 启动和开发本地工作台：读 [`WORKBENCH.md`](WORKBENCH.md)。
- 接入用户级标准／非标准 SKILL：读 [`EXTERNAL_SKILLS.md`](EXTERNAL_SKILLS.md)。
- 理解 Agent / Role / Skill / Runtime：读 [`AGENTS_AND_SKILLS.md`](AGENTS_AND_SKILLS.md)。
- 源码升级与在途 Task 的契约迁移：读 [`GETTING_STARTED.md`](GETTING_STARTED.md) 第 10 节「同版本源码升级与兼容」。

## 按 Agent 选择入口

<!-- TP-SPEC:AGENT-MAP-BEGIN -->
<!-- 由 scripts/check_document_navigation.py --write 根据 governance/role-catalog.yaml 生成。不要手工编辑本区块。 -->

| Domain Agent | ID | 导航 | 执行契约 |
| --- | --- | --- | --- |
| tp-软件工程生命周期 | `tp-software-lifecycle` | [打开](./agents/tp-software-lifecycle.md) | [`agents/tp-software-lifecycle/SKILL.md`](../agents/tp-software-lifecycle/SKILL.md) |
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

- Wiki：[`tp-wiki`](agents/tp-wiki.md)、[`wiki/README.md`](../wiki/README.md) 与 [检索、读取和使用分析](WIKI_USAGE.md)
- Knowledge：[`tp-knowledge`](agents/tp-knowledge.md)、[`knowledge/README.md`](../knowledge/README.md) 与 [知识库页面及使用口径](KNOWLEDGE_USAGE.md)
- 项目自治：[`tp-project-autonomy`](agents/tp-project-autonomy.md) 与 [`automation/autonomy/README.md`](../automation/autonomy/README.md)

## 架构、Runtime 与治理

Runtime 的任务状态、事件、Evidence 与工作流事实由 CLI/Runtime 自动维护。治理记录是执行副产物，不要求 AI 为日常工作手写大量状态文档。当前架构关系见 [`AGENTS_AND_SKILLS.md`](AGENTS_AND_SKILLS.md)。

安全行为的提案、人工来源、范围决定和入口约束见 [Security Change Authority](security-change-authority.md)。

## 维护、测试与发布

Base 维护入口见 [`tp-base-maintenance`](agents/tp-base-maintenance.md)。自动化总入口见 [`automation/README.md`](../automation/README.md)。本仓开发与交付按 [`TESTING.md`](TESTING.md) 选择当前改动的局部验证，不自动运行全量测试；内容清单和文档导航按对应变更核对，不参与 Runtime 路由。

## 历史与过程文档政策

当前发布面只保留仍可执行、仍需用户阅读的文档。临时设计、迁移调查、一次性实施计划和机器生成过程报告不作为长期文档入口；版本变化及需保留的批次验证记录由 [`CHANGELOG.md`](../CHANGELOG.md) 记录。当前说明不绑定某次补丁包的基线或日期，不复制历史测试数量为当前结论；历史记录保留原时间、输入、范围与限制，未记录的日期或验证不补造。

本政策由 [`check_document_navigation.py`](../scripts/check_document_navigation.py) 强制执行：**`docs/decisions/` 下的任何文件，以及文件名内嵌基座版本号的文档（如 `V531_*.md`、`MIGRATION_V529.md`），不得作为发布面文件引入**；增量 Patch 或人工提交带入时文档导航门禁直接失败。这类过程文档只在 Git 历史与 `CHANGELOG.md` 中保留，不复制进当前发布面，也不为它保留版本纯度白名单。
