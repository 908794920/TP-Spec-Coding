# TP-Spec-Coding Wiki Subsystem (V5.2.0)

Wiki 是 TP-Spec-Coding 的**代码理解层**：它把当前源码事实压缩成可导航、可引用、可增量维护的结构化地图，供人和 Agent 快速定位代码，但**源码始终是最终事实源**。

职责分离：

```text
Source Code = 当前技术事实
Wiki        = 当前技术事实的结构化理解/导航
Task        = 一次研发行为的历史记录
Knowledge   = 跨任务长期有效的业务/经验知识
```

Wiki 不参与 Task 工作流状态机，不替代源码核验，也不与 Knowledge canonical 数据混写。

## 标准维护链

```text
SCAN
→ CLASSIFY
→ SOURCE TOPOLOGY DIFF
→ PLAN
→ AI UPDATE (仅需要语义维护时)
→ MANIFEST REFRESH
→ L1/L2/L3 VERIFY
→ L4 SEMANTIC AUDIT（需要时）
→ SNAPSHOT COMMIT
```

只有当前 change-set 的确定性验证 PASS，且需要 L4 时已有真实语义审计 PASS，才允许推进源码 Snapshot baseline。

## 数据与工具分离

Wiki physical project root（由 Wiki System Root + Repo Registry 解析）只保存 Wiki 文档和 `meta/` 状态；zero-config 时才回退到 `.ai-work/wiki`。历史中央 Wiki `tools/` 不再是 Wiki 数据目录的一部分。确定性能力由 TP-Spec-Coding `cli/wiki/` 提供。

## 路径

路径按“Base 默认 → 用户 `~/.ai-work/installation.yaml` → 可选项目 `.ai-work/config/content-systems.yaml` override”解析：

- `wiki.root` 表示 Wiki **System Root**；中央布局再由 Repo Registry 解析当前 workspace/repository scope；
- `knowledge.root` 表示 Knowledge System Root，与 Wiki project scope 是不同系统；
- 空 root 仍保留 zero-config fallback；
- Junction 仅为 legacy 兼容/浏览入口，Runtime 不依赖 Junction 才能解析项目 physical root。

## CLI

项目侧/AI Scheduler 使用已安装 `ai-work` 命令，或直接调用 `<BaseRoot>/scripts/Invoke-AiWorkCli.ps1 wiki ...`。BaseRoot 由用户 Installation/环境变量解析；不得把 `.ai-work/scripts` Junction 当成稳定入口。下面列出逻辑命令：

```text
ai-work wiki doctor
ai-work wiki init
ai-work wiki build
ai-work wiki scan
ai-work wiki plan
ai-work wiki maintain
ai-work wiki manifest-refresh
ai-work wiki verify
ai-work wiki coverage
ai-work wiki audit
ai-work wiki audit-record
ai-work wiki snapshot-commit
ai-work wiki status
```

AI 定时维护应读取 `automation/wiki/daily-maintenance.md`，不得靠长期保存的一段自由提示词自行发明流程。

## 标准文档

- 配置与路径：`wiki/rules/configuration.md`
- Source Fingerprint / 编码 / Mass Change Guard / cite 行号漂移：`wiki/rules/source-fingerprint.md`
- L1-L4 质量门：`wiki/rules/quality-gates.md`
- Wiki 内容类型与引用规范：`wiki/rules/content-standard.md`


## 覆盖率

`wiki coverage` 同时报告两个不同目的的指标，禁止混为一个数字：

- `source_dependency_coverage`：扫描器看到的全部 source 中，有多少出现在 manifest dependency；用于发现 topology/source-discovery 盲区，不代表 Wiki 真正覆盖率。
- `effective_wiki_coverage`：**Wiki 有效覆盖率（主指标）**。分母只包含有长期代码理解价值的 `wiki-eligible` source；分子只统计当前 normalized hash 仍匹配，并且被 `primary/context` dependency 或真实 `<cite>` 实质表达的文件。

`reference` metadata 单独存在而正文没有 cite 时不计入有效覆盖，避免通过批量塞 dependency 刷高比例。报告同时输出 eligible / excluded / covered / uncovered 数量和排除原因；跨仓总覆盖率按“总 covered / 总 eligible”计算，不平均各仓百分比。


For an explicit full semantic quality audit with no pending source change set, use `wiki audit --full`; its PASS receipt must cover every durable manifest Wiki document.

## 覆盖率真实性

Effective Wiki Coverage 只统计 wiki-eligible 文件；covered 必须同时满足 Wiki 文档自身的 content_hash 当前、源码 normalized_hash 当前，并由真实 cite 或绑定到现存章节的 primary/context 语义关系承载。reference-only、空 section 关系、stale Wiki/source provenance 均不计覆盖。
