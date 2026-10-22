---
name: tp-wiki-audit
display_name: Wiki 质量与语义审计
version: 5.3.8
description: 用于 Wiki 确定性质量验证、覆盖率判断及必要的 L4 源码语义审计；区分首次全仓与增量受影响范围，实际执行结果才可报告 PASS。
---

# Wiki 质量与语义审计

## 核对输入

按 [Stable Source](../../../wiki/rules/stable-source.md)确认选定 repo、固定来源、当前计划、manifest/provenance 及实际受影响文档；不把旧回执当作当前状态，不自行切分支或使用 dirty 工作区替代固定来源。

执行与报告遵循 [质量门](../../../wiki/rules/quality-gates.md)：

| 层级 | 核验对象 |
|---|---|
| L1 Integrity | 事实与结构硬门。 |
| L2 Traceability | dependency/cite/source/topology 可追溯性；`wiki coverage` 的 `effective_wiki_coverage = trusted covered / wiki-eligible` 是真实文件覆盖率主指标。 |
| L3 Content Quality | 灌水、重复、依赖注水和低信息密度。 |
| L4 Semantic Audit | 模型回到同一固定源码，核对文档语义是否成立。 |

`verify PASS` 只证明确定性门通过，不能替代 L4。首次可信 baseline 的范围是 `initial-full-repo`；日常增量必须覆盖全部 affected documents，风险抽样不能替代 mandatory scope。

只有维护规则变化时，先按 [维护规则指纹](../../../wiki/rules/source-fingerprint.md)审查实际差异。正式 `wiki policy-review` 通过旧规则字节与当前配置重建旧摘要，核对当前规则和证据绑定后，才可复用仍适用的旧语义证据；它不记录新的 L4 PASS，也不豁免真实 source/subject 变化、repair、topology 或旧 FAIL。缺少旧完整身份时不能靠当前 anchors 推定旧成功 completion 的文档身份。

## 语义审计

用 `wiki source-read --path <repo-relative file>` 回读固定来源；需旧成功来源时使用 `--baseline`。按 [源码语义与内容写作](../tp-wiki-maintenance/references/semantic-writing.md)核对 Currentity、真实权威层、职责归因、阶段 owner、接口/Scope 精确性及邻近引用。重点检查是否误导当前主路径、责任归因错误或漏掉核心模块。

审计判断与 receipt 按正式协议记录，不手工改 hash/snapshot/机器 citations，不放宽门槛迁就产物，不靠 metadata-only `reference` dependency 刷覆盖率。确定性命令执行、语义检查与来源范围分别保留真实证据。

相同固定来源、文档字节与适用规则下的实际阅读证据可以复用，只补变化或缺失部分。确定性收口引用原审计时保留原时间、来源和限制；历史正式成功但明确无需 L4 的无审计状态继续记为 `LEGACY_L4_NOT_RECORDED`，不得补写虚构 PASS。

## 结论

逐项区分 PASS、FAIL、未执行和环境/来源阻塞，不能把抽样说成全量实测。必要更新未完成、质量 FAIL、UNCERTAIN、必要 L4 缺失/失败或来源/策略不一致时，不推进 baseline；修复只在相应获准范围内交给[增量维护](../tp-wiki-maintenance/SKILL.md)或[异常恢复](../tp-wiki-recovery/SKILL.md)。
