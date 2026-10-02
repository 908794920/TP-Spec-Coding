---
id: tp-wiki
name: tp-wiki
version: 5.3.7
status: active
type: human-owner-skill
tool_agnostic: Wiki 来源和写入根由 Content Systems Resolver 定位；能力按需读取，不依赖特定 IDE、模型或机器路径。
description: 代码理解 Wiki 薄领域入口；识别检索、增量维护、首次构建、语义审计、异常恢复和定时维护意图，按需选择能力，不拥有 workflow state。
---

# tp-wiki — 代码理解层

## 职责与范围

Wiki 是已选择稳定源码快照的结构化理解与导航层。入口只识别对象和意图、复用已知来源与授权、选择能力并汇总实际结果；具体方法由下列 SKILL 维护。Source Code 是当前技术事实，Task 是研发历史，Knowledge 是长期知识；Wiki 不替代三者。

## 意图路由

| 本次意图 | 按需加载 |
|---|---|
| 查找或读取已有 Wiki、确认实际采用 | [Wiki 检索与读取](../../skills/wiki/tp-wiki-retrieval/SKILL.md) |
| 选定稳定来源后的日常变更、增量更新与基线收敛 | [Wiki 增量维护](../../skills/wiki/tp-wiki-maintenance/SKILL.md) |
| 首次构建或全量重建一个 repo 的可信 Wiki | [Wiki 首次构建](../../skills/wiki/tp-wiki-initial-build/SKILL.md) |
| 确定性质量门、覆盖率或 L4 语义审计 | [Wiki 质量与语义审计](../../skills/wiki/tp-wiki-audit/SKILL.md) |
| Anchor、引用行号、来源或基线异常恢复 | [Wiki 异常恢复](../../skills/wiki/tp-wiki-recovery/SKILL.md) |
| 已配置 Wiki Scheduler 唤起的维护运行 | [Wiki 定时维护](../../skills/wiki/tp-wiki-scheduled-maintenance/SKILL.md) |

只加载本次命中的能力；复合工作按实际依赖接续，复用有效来源和验证，不预读全部方法。普通查阅不启动维护链；首次构建与增量维护的范围和验收条件分别处理。

## 共享边界与转交

- 通过 Content Systems Resolver 定位 System Root、Repo Registry 与物理项目根，保持 workspace/repo scope；不猜目录名、不依赖旧 Junction，不把工具复制到 Wiki 数据目录。
- 正式 Git Wiki 只使用用户指定、本地已有的远程跟踪 ref 固定 commit；不自行 fetch/pull、选择默认分支或纳入未推送工作。非 Git 使用文件 hash/stability 来源，不声称指定分支保证。
- 只写 resolved Wiki physical root 内的 Wiki/metadata，不改 source repo 或 canonical Knowledge。已有维护授权继续有效；新增范围、高风险取舍或缺失来源才交 human_owner。
- 不拥有 actor/workflow state，不触发 Task 状态、交接或结单；Wiki stale 通过独立维护链处理，不成为普通研发 Task Gate。首次构建/全量重建限一个 repo，已配置的日常协议可按 registry 顺序处理多个 repo。
- 外部方法按[选择与转交规则](../../docs/EXTERNAL_SKILLS.md#entry-handoff)按需发现，保留精确 ID、来源、状态和指纹；方法不是源码证据，不扩大 repo scope、写入权限或质量判断，也不自动记录 Wiki 采用。
- Base 接入/安装问题交[基座维护](../tp-base-maintenance/SKILL.md)，产品源码修改交[软件工程生命周期](../tp-software-lifecycle/SKILL.md)。

## 结果

分别报告实际来源、动作、确定性验证、语义审计、基线状态及未解决条件。不可读、未执行与 FAIL 保持真实区别；禁止手填 hash、snapshot 或 citations 过门，不以抽样冒充全量或以确定性 PASS 代替语义审计。
