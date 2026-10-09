---
name: tp-wiki-maintenance
display_name: Wiki 增量维护
version: 5.3.8
description: 用于已选稳定源码的 Wiki 日常增量维护、变更分类和可信基线收敛；复用成功基线快路径，NO_CHANGE 不启动模型重写。
---

# Wiki 增量维护

## 来源与写入根

先通过 Content Systems Resolver 定位 Wiki System Root、Repo Registry 与当前 workspace/repo 的物理根；用户 Installation、项目 override 或零配置本地默认按实际解析结果使用，不硬编码路径、不依赖 `.tp-spec/wiki` Junction。Wiki 数据目录不携带 `tools/`。使用正式 `tp-spec wiki doctor --workspace-root <workspace>` 核对当前接入条件。

来源选择和快路径按 [Stable Source](../../../wiki/rules/stable-source.md)。Git 只固定用户明确指定、本地已有的 `refs/remotes/<remote>/<branch>` commit，排除工作区和本地未推送提交；不自行 fetch/pull 或猜默认分支。非 Git 保留实际文件 hash/stability 来源。来源不足时停止受影响动作。

## 按变化处理

先固定来源并执行成功基线快路径；`NO_CHANGE` 直接结束，不启动模型维护。需要处理时沿当前工具的真实结果接续：

```text
SCAN → CLASSIFY → TOPOLOGY → PLAN → AI UPDATE
→ manifest-refresh → VERIFY → L4 AUDIT（必要时）→ snapshot-commit
```

路径、枚举、raw/normalized fingerprint、encoding、分类、Source Topology Diff、rebuild plan、manifest machine fields、L1–L3 和 snapshot baseline 由确定性工具负责。AI 只判断语义/结构影响并更新确实受影响的章节、模块和索引。

| 真实变化 | 方法 |
|---|---|
| TOUCHED_ONLY | 不改正文。 |
| COSMETIC | 仅更新 provenance，不调用模型重写。 |
| SEMANTIC | 更新真实受影响文档/章节；扩大范围需源码依据。 |
| STRUCTURAL | 结合 Source Topology 新增、合并或调整文档和 index；旧依赖图没边不代表新核心文件可忽略。 |
| DELETED | 移除或改写失效的解释和引用。 |
| UNCERTAIN | 先查编码与文件事实，不猜测、不推进 baseline。 |
| MASS_CHANGE_REVIEW_REQUIRED | 先判断重新下载、换行、编码、formatter、include/exclude 漂移或真实迁移；不凭一次重下载全量重写。 |

进入正文更新时读[源码语义与内容写作](references/semantic-writing.md)，用 `wiki source-read --path <repo-relative file>` 回读同一份固定来源；需要旧成功来源时用 `--baseline`，不引用 dirty 工作区行号。文档按能力/子系统组织，一个源码文件不等于一篇 Wiki。

## 质量与基线

需要确定性验证或 L4 时读 [Wiki 质量与语义审计](../tp-wiki-audit/SKILL.md)。首次构建/全量重建交[首次构建](../tp-wiki-initial-build/SKILL.md)，Anchor 异常按[异常恢复](../tp-wiki-recovery/SKILL.md)处理，不借增量维护降低门槛。

必要语义更新未完成、质量 FAIL、UNCERTAIN 未解、必要 L4 未做/失败、来源/策略不一致或提交前 FILESYSTEM 字节改变，都禁止推进 baseline。Git follow-up 始终用 staged SHA，stable_ref 后续推进留给下次，不能换成工作区。不得手填 hash、snapshot、机器 citations 或无证据扩大删除。

只写 resolved Wiki physical root 内的 Wiki/metadata，不改 source repo 或 canonical Knowledge。分别报告 NO_CHANGE、实际更新、验证/审计和 baseline 是否提交；临时收据清理失败与基线提交结果分开说明。
