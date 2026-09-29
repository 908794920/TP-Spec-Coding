---
name: tp-wiki-initial-build
display_name: Wiki 首次构建
version: 5.3.6
description: 用于首次构建或获准全量重建单个 repo 的可信 Wiki baseline；处理语义聚类、首次覆盖阈值和全仓语义审计，不将日常增量扩大成全量重建。
---

# Wiki 首次构建

## 适用与来源

仅用于明确的首次构建或全量重建请求，一次处理一个 repo。通过 Content Systems Resolver 定位并执行正式 doctor，来源固定规则按 [Stable Source](../../../wiki/rules/stable-source.md)：Git 只用用户指定、本地已有的远程跟踪 ref commit，不自行 fetch/pull，不纳入未推送提交/工作区；非 Git 用真实 hash/stability，不提供分支保证。

## 文档组织

先将 Wiki-eligible source 按能力/子系统语义聚类，再设计文档拓扑；一个源码文件不等于一篇 Wiki。按 [源码语义与内容写作](../tp-wiki-maintenance/references/semantic-writing.md)回读固定来源、区分当前与兼容路径、明确职责与引用。

`quality.initial_build_effective_coverage_min` 是首次可信 baseline 的就绪阈值（默认 0.95），与日常 `effective_wiki_coverage_warn` 分离。低于阈值必须继续处理 uncovered，不能把“verify 没有 coverage ERROR”当作可以结束。对剩余 uncovered 逐项判断补进现有/聚合 Wiki，或确应排除且提供真实 reason；不得为 100% 调整分母。

## 收敛条件

确定性源码枚举、hash、topology、plan、manifest/provenance 由正式工具维护。完成受影响内容后按 [质量与语义审计](../tp-wiki-audit/SKILL.md)验证：首次可信 baseline 的 L4 范围是 `initial-full-repo`，不能以抽样或单独 verify PASS 替代。

只有必要语义更新、覆盖要求、确定性质量门、L4 和来源/策略一致性都成立才允许推进 baseline；FILESYSTEM 提交前字节变化时重新核对，Git follow-up 保持 staged SHA，不改用 dirty 工作区。不修改 source repo，只写 resolved Wiki physical root。分别报告构建产物、未覆盖处置、质量与审计结果和最终 baseline。
