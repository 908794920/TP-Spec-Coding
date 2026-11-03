---
name: tp-wiki-recovery
display_name: Wiki 异常恢复
version: 5.3.8
description: 用于 Wiki Anchor、引用行号、来源或基线异常的定向诊断与获准恢复；只在 repairable 条件成立时修复，不手改指纹或虚构旧源码。
---

# Wiki 异常恢复

## 先定位原因

核对 Content Systems Resolver 的 workspace/repo、Wiki physical root 及选定源码；来源选择、迁移与失败分支按 [Stable Source](../../../wiki/rules/stable-source.md)处理。缺旧对象、来源或权限时如实停止相应动作，不换用当前工作区去冒充旧 baseline。

维护失败/中断先区分正式成功 Wiki 与隔离 candidate。`maintain/build/scan` 返回的 `candidate_wiki_repo_root` 是本轮 AI 唯一写入根；后续计划、manifest、verify、coverage、audit、audit-record 和普通 source-read 自动路由该 candidate。失败草稿不作为正式正文或下一轮成功输入；重新 `maintain` 隔离旧 draft，从正式 Wiki 建立新 candidate。`NO_CHANGE` 不建立 candidate，不手工搬运草稿或半套 metadata 恢复。

候选保留清理使用 `wiki candidate-cleanup`（默认只读计划，`--apply` 才写入）。活动 candidate、publishing 现场、修改过的 previous/退役树、无归属记录的目录均保留；只有当前正式树仍匹配发布身份且 previous 匹配原 old_tree 时才能清理 previous。旧 draft 还需已有 maintain 丢弃回执及无独有 durable 字节的核对；不手工补造退役摘要来删除未知目录。Git 隔离只覆盖候选目录，不替代实际清理，也不隐藏正式文档回执。

`WIKI_SUBJECT_SCOPE_UNPROVEN` 需要实际差异范围或确切成功原字节：成功 durable 分项能重现完整旧 subject 时才按文档差集缩小复核，源码依赖/topology、initial、repair、旧 FAIL、UNCERTAIN 与必要 L4 继续适用。缺旧分项、未知/全局变动不等于全库正文已错，不自动全库重写，也不拿当前 anchors 伪造历史身份。`policy-review` 在正式 Wiki 上核对旧规则和配置，准确登记后重跑 `maintain`；scope 无法重现摘要时保持拒绝，不自动换 scope。

Anchor baseline 异常或 cite line 无法恢复时，先使用正式 `wiki anchors-doctor`。只有实际结果 `repairable=true`，且当前请求覆盖修复时，才使用 `wiki anchors-repair --apply`。

- Git 从 committed SHA 读取旧源码，不受 dirty 工作区或 ref 前移影响；旧对象缺失时报告缺失，不自动 fetch/pull。
- FILESYSTEM 实际字节已偏离 baseline 时，不能从 hash 还原旧签名；需要重新验证或获准 full-rebuild，不能直接把 hash 改成新值。
- 不手改 `wiki-cite-anchors.json`、hash、snapshot_id 或 cite line，不因为元数据能被读取就报告恢复成功。
- `UNCERTAIN` 或大批变化先查编码、换行、下载及策略事实，不以无证据全量重写代替排错。

## 恢复后

正文修复只写当前返回的 candidate，Anchor 等工具恢复遵守各命令实际返回的对象与 repairable 条件，保留真实源码和其他项目。复验受影响引用、质量门和适用的[语义审计](../tp-wiki-audit/SKILL.md)；仍未满足来源/质量/审计条件则不推进 baseline。`snapshot-commit` 通过 candidate 门禁并确认正式 Wiki 起点身份仍一致（CAS）后才提升；冲突时保留现场并重新 `maintain`。报告实际修复、恢复证据和剩余条件，清理失败与正式提交状态分开说明。
