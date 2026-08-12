# Wiki Quality Gates

## L1 — Integrity（硬门）

事实/结构损坏即 ERROR，典型包括：

- manifest/schema 不合法；
- document type、dependency role 非标准或重复路径；
- manifest 未覆盖磁盘 Wiki Markdown；
- 根/目录导航 `index.md` 缺失、本地 Wiki link 断裂；
- completed 文档缺失/空文件、document hash 不一致；
- dependency 源文件不存在、路径逃逸、双 hash 缺失/不匹配；
- cite 文件不存在、路径逃逸、行号越界或用近似整文件假区间冒充精确引用；
- manifest citation index 与正文 `<cite>` 不一致；
- source decode 为 `UNCERTAIN`；
- semantic/structural 变化没有当前 rebuild plan；
- Mass Change Guard 未显式复核；
- Mermaid 代码块未闭合。

任何 L1 ERROR 都禁止 `snapshot-commit`。

## L2 — Traceability

- completed content-doc/concept-card 至少有一条真实 source cite；

检查 source↔Wiki 的可追溯完整度：

- scanner-wide source dependency coverage（用于发现拓扑盲区）；
- Effective Wiki Coverage（真实 Wiki 文件覆盖率：trusted covered eligible / wiki-eligible）；
- citation line coverage（除单行 source 外默认必须达到配置阈值，当前 90%，不足为 L2 ERROR）；
- source topology backlog；
- 新增源码是否因旧 dependency graph 无 edge 而失踪；
- source/wiki 是否明显漂移。

默认 citation 行号覆盖目标 90%。首建/重建直接生成精确行号，不能把大规模事后补行号当正常流程。覆盖不足属于 L2 ERROR；真实引用不存在属于 L1 ERROR。

`TOPOLOGY_REVIEW_REQUIRED` 默认 WARN，因为 AI 的 L4 可以真实判断某个新增低层文件“不需要独立 Wiki 表达”；但 structural change 一定要求 L4 后才能推进 baseline。

## L3 — Content Quality

内容规则包括：

- `content-doc` 七段缺失、completed 段落空桩、TODO/待填属于 ERROR；
- 强灌水信号、逐字重复、依赖注水、低信息密度通常 WARN，要求 AI 阅读后决定是否返工；
- 单文档依赖异常膨胀（例如 >1000）提示注水风险；
- 不因过 Gate 而扩写没有源码价值的模板文字。

脚本只能发现结构和部分强信号，不能把“L3 没报错”解释成正文语义已经正确。

## L4 — Semantic Audit（模型）

由 `wiki audit` 先生成**确定性 audit scope**，再由 `tp-wiki`/AI 回源码核验：

- Wiki 的职责、流程、关系是否真的被源码支持；
- cite 指向的代码是否支撑正文推论，而不仅是路径存在；
- 本次 topology 新增/删除/移动是否需要改变 Wiki；
- 是否存在明显遗漏或幻觉。

日常增量必须审计**全部受影响文档**，再加少量高风险抽样；不得因为受影响文档多就截断成样本后推进 baseline。首次接管/首次建立可信 baseline 时执行 `initial-full-repo`，对 manifest 中全部 durable Wiki 文档做一次完整语义迁移审计。风险抽样只能补充，不能替代 mandatory scope。

若 audit plan 含 topology review，`audit-record PASS` 必须显式确认已逐项核查 topology；未做不得写 PASS。

L4 使用**对抗式语义检查**，不是把生成结果顺读一遍。首次 clean build 在进入 L4 前还必须通过独立的 `FIRST_BUILD_READINESS`：默认 Effective Wiki Coverage ≥95%；这不是 L1-L3 coverage Gate，也不要求日常维护永远 95%+，只是防止首次半成品被当作可信 baseline。

对每篇 mandatory 文档，在相关时至少挑战以下问题：

1. 文档声明的 `CURRENT` 主路径是什么？源码是否还存在竞争/旧路径；如果存在，为什么它不是 CURRENT？
2. 是否把“代码存在/函数可调用/状态兼容”误写成“当前权威/推荐/日常主链”？
3. 每个“负责、保证、决定、唯一、强制”断言由哪一层真正 enforce？cite 是否直接支持这个归因？
4. 流水线中的 discovery / classification / eligibility / planning / verification 等阶段 owner 是否写对，有没有把相邻模块职责合并错？每个被声称的 stage owner 都应回到具体 function/entrypoint 核验，不能仅凭模块名或“数据经过这里”推断 owner。
5. current version、活动配置、runtime entrypoint、router/dispatch 与正文描述是否一致？
6. cite 是否只证明“相关代码存在”，却不足以证明正文更强的产品/架构结论？关键 cite 是否实际位于承载该断言的正文 section，而不是全部堆在“溯源/参考/证据”中？
7. 文档声明的 command/CLI option/config key/threshold/default/mandatory step/scope 是否由实际 parser/schema/config/canonical protocol 或 runtime entrypoint 精确证明？尤其检查是否虚构参数、把建议写成必须、把首次 clean build readiness 泛化成日常 Gate；若 current 与 legacy 同时出现在流程图，是否已显式分叉/标注而非无标签合流？

不适用的问题可以略过；适用但无法从源码判定时必须报告不确定，不能凭生成阶段的原解释自证 PASS。

## Baseline Rule

```text
SCAN → PLAN → AI UPDATE(if needed)
→ MANIFEST REFRESH
→ L1/L2/L3 VERIFY PASS
→ L4 PASS(if required)
→ SNAPSHOT COMMIT
```

失败、中断、UNCERTAIN、Mass Change 未复核、AI 未实际更新、Wiki 在 verify 后变化或 source 在 scan 后再次变化，都不得推进 baseline。


## Effective Wiki Coverage

主覆盖率不是“dependency 数 / 全部扫描文件数”，而是：

```text
Effective Wiki Coverage
= trusted covered wiki-eligible files
  / all wiki-eligible source files
```

`wiki-eligible` 会排除已知没有独立 Wiki 价值的低层/生成型文件（例如 MyBatis `*Mapper.xml`、JeeSite 模板 XML、样式资产、普通 README/docs）；每个排除项都必须带 reason 并可通过配置覆盖。

文件只有在 **Wiki 侧与源码侧 provenance 都是当前的** 时才有资格计为 covered：当前 Wiki 文档字节 hash 必须与 manifest 的 `content_hash` 一致，同时 source `normalized_hash` 必须与 manifest dependency provenance 一致。在此前提下满足至少一项：

1. 正文存在真实 `<cite>` 指向该文件；
2. 是 completed Wiki 文档的 `primary/context` dependency，且 dependency 至少绑定一个当前仍存在的正文 section。

仅有未引用的 `reference` dependency 不计入 headline coverage；空/nonexistent section 的 `primary/context` 也不能单独计数，避免通过 metadata 注水。源码已变化、Wiki 文档未 refresh、dependency hash 未验证等情况都不计入覆盖。

同时保留 `source_dependency_coverage` 作为扫描/拓扑诊断指标，但不得称为“真实 Wiki 覆盖率”。报告还必须拆出 `citation_evidence_files / primary_context_files / dual_evidence_files / citation_only_covered_files / semantic_only_covered_files`，让 100% headline 能解释为多少文件由直接 cite 支撑、多少文件仅由当前章节语义承载，而不是只给一个好看的百分比。


### Standalone full semantic audit

When a human or scheduled quality audit explicitly needs a full semantic re-check without a pending source change set, run `wiki audit --full`. The deterministic plan uses `audit_scope=standalone-full-repo`; `audit-record PASS` must cover every durable manifest document. This is distinct from daily incremental `all-affected` review.
