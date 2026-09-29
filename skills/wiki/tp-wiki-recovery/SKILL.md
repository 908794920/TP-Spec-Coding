---
name: tp-wiki-recovery
display_name: Wiki 异常恢复
version: 5.3.6
description: 用于 Wiki Anchor、引用行号、来源或基线异常的定向诊断与获准恢复；只在 repairable 条件成立时修复，不手改指纹或虚构旧源码。
---

# Wiki 异常恢复

## 先定位原因

核对 Content Systems Resolver 的 workspace/repo、Wiki physical root 及选定源码；来源选择、迁移与失败分支按 [Stable Source](../../../wiki/rules/stable-source.md)处理。缺旧对象、来源或权限时如实停止相应动作，不换用当前工作区去冒充旧 baseline。

Anchor baseline 异常或 cite line 无法恢复时，先使用正式 `wiki anchors-doctor`。只有实际结果 `repairable=true`，且当前请求覆盖修复时，才使用 `wiki anchors-repair --apply`。

- Git 从 committed SHA 读取旧源码，不受 dirty 工作区或 ref 前移影响；旧对象缺失时报告缺失，不自动 fetch/pull。
- FILESYSTEM 实际字节已偏离 baseline 时，不能从 hash 还原旧签名；需要重新验证或获准 full-rebuild，不能直接把 hash 改成新值。
- 不手改 `wiki-cite-anchors.json`、hash、snapshot_id 或 cite line，不因为元数据能被读取就报告恢复成功。
- `UNCERTAIN` 或大批变化先查编码、换行、下载及策略事实，不以无证据全量重写代替排错。

## 恢复后

只写 resolved Wiki physical root 内的必要数据，保留真实源码和其他项目。复验受影响引用、质量门和适用的[语义审计](../tp-wiki-audit/SKILL.md)；仍未满足来源/质量/审计条件则不推进 baseline。报告实际修复、恢复证据和剩余条件，清理失败与 baseline 提交状态分开说明。
