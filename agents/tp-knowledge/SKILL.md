---
id: tp-knowledge
name: tp-knowledge
display_name: tp-knowledge
version: 5.3.6
status: active
type: human-owner-skill
tool_agnostic: Knowledge 根与项目身份由 Resolver 定位；不依赖特定 IDE、账号、插件或用户目录绝对路径。
description: Knowledge 长期知识领域薄入口；按检索、Task 收敛、内容维护、外部接入、标准化或定时维护意图选择内置能力，不负责 Base 健康或软件交付裁决。
---

# tp-knowledge — 长期知识领域

## 职责与范围

Knowledge 保存跨 Task 可复用的业务规则、稳定架构/接口/数据事实、历史决策与有证据的经验。Source Code 是当前技术事实，Wiki 是代码理解与导航，Task Runtime 记录一次研发过程；Knowledge 的 canonical Markdown 与注册 evidence 是长期事实源，FTS/link/graph 是可重建投影。入口只识别本次意图、复用已知项目身份和授权、选择能力并汇总结果，不拥有 workflow state 或固定生命周期阶段。

## 意图路由

| 本次意图 | 按需加载 |
|---|---|
| 查找、读取已有知识及核对证据、搜索效果 | [知识检索与证据读取](../../skills/knowledge/tp-knowledge-retrieval/SKILL.md) |
| 最终 Task 的可信 Request、候选判断、Knowledge/Memory Result | [Task 知识与记忆收敛](../../skills/knowledge/tp-knowledge-task-convergence/SKILL.md) |
| 已有 source/canonical 增量变化、验证、索引与 baseline | [Knowledge 内容维护](../../skills/knowledge/tp-knowledge-maintenance/SKILL.md) |
| 已登记的外部文档批次接入或重处理 | [外部文档接入](../../skills/knowledge/tp-knowledge-ingestion/SKILL.md) |
| 旧 Vault 的迁移或结构标准化 | [Legacy Knowledge 标准化](../../skills/knowledge/tp-knowledge-normalization/SKILL.md) |
| human_owner 已配置的 Knowledge Scheduler 唤起 | [Knowledge 定时维护](../../skills/knowledge/tp-knowledge-scheduled-maintenance/SKILL.md) |

只加载匹配的能力；复合任务按实际依赖接续，复用 Resolver 与已有证据，不默认运行全库 scan、ingest、eval、audit 或所有能力。最终 Task 收敛是交付责任链的一部分，由集成交付工程师触发并核对；它不自动变成日常维护链。

## 共享边界与转交

- 当前项目、注册 shared scope、Knowledge 物理根与投影位置由 Binding/Resolver 确认，不依赖 `.tp-spec/knowledge` 兼容 Junction 或硬编码路径。默认检索当前项目 + registered shared；只有明确跨项目任务才用 global。
- 内容写入受本次真实范围和授权约束。强断言回到 source/task/code/external evidence；不把模型推断、未本地复验的 Task 引用或检索投影当成事实。检索和维护能力各自说明所需的读写检查。
- 新交付使用可信 `KNOWLEDGE_CONVERGENCE_REQUEST`、当前 READY 与有效 Change Set；集成交付工程师用 [knowledge-capture](../../skills/capabilities/knowledge-capture/SKILL.md) 提炼有效需求与步骤材料，本领域定向判重、处置，不代替软件 Verification/Review/Delivery，也不因无知识信号跳过必做评估。完整契约按需由 Task 收敛能力加载。
- Base VERSION、Junction、项目受管块与安装健康交 [tp-base-maintenance](../tp-base-maintenance/SKILL.md)。外部方法承接精确 ID、来源、状态与指纹；直接调用时按 [外部能力选择与转交](../../docs/EXTERNAL_SKILLS.md#entry-handoff) 发现并读取。阅读外部方法不自动将其 ingest 为 Knowledge、项目 Memory 或采用记录，也不扩大 scope 或写入权限。

## 结果

按实际能力报告对象、scope、来源与证据、执行动作、检索或验证 receipt、未解决条件。Task 的正式 Result 与 Memory 持久化分开；内容可读、投影命中或索引完成都不能冒充业务裁决、知识已采用或宿主已加载。
