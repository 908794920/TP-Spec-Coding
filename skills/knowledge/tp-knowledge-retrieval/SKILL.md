---
name: tp-knowledge-retrieval
display_name: 知识检索与证据读取
version: 5.3.5
description: 用于在已解析的项目和注册 shared 范围内检索、读取 Knowledge canonical/source 及核对证据与搜索效果；不触发内容维护或全局检索。
---

# 知识检索与证据读取

## 定位与来源

用共享 Content Systems Resolver 确认 `knowledge_physical_root`、项目身份、注册 shared scope 与投影 DB；`.tp-spec/knowledge` Junction 只是兼容浏览入口。Source Code 是当前技术事实，Wiki 是导航；Knowledge 的 canonical Markdown 加注册 evidence 是长期事实源。FTS/link/graph 可重建，同库检索/读取日志是使用证据，重建时保留，不直接删数据库。

## 定向检索

1. 默认范围是当前项目 + registered shared scopes。只有用户明确要求跨项目，才用 `--scope global`；全局 SQLite 投影不等于默认全局搜索。
2. 先用 `tp-spec knowledge search -q ...` 做 **canonical-first FTS5 → source fallback**，再按实际命中定向核对 source/evidence。不要先扫全库 Markdown 猜重复项。Graph 是可选投影；历史 Embedding/vector 评测收益不足，兼容表存在不表示已启用。
3. 正文按需用 `tp-spec knowledge read --document-id <document_key>` 读取。普通文件工具读取不进入 Knowledge 采集日志；页面候选数、摘要/预览界限与只读边界按 [Knowledge 使用说明](../../../docs/KNOWLEDGE_USAGE.md) 执行。
4. 兼容旧 `source_refs`；新或实质更新内容优先以结构化 `evidence_refs` 表达 `source/task/code/external`。对当前入口、必须、唯一、数值、配置项或责任层等强断言，读回真实 evidence。没有本地 Task evidence root 时，`TASK-*` 只能称为已登记或可外部解析，不称本地复验。

标准搜索只记录 query hash、模式、候选/结果数、fallback 与耗时等轻量 telemetry，不保存原始 query 正文。关注 canonical hit、source fallback、no-result、latency；检索策略改变前用当前 Golden Set 跑 `tp-spec knowledge eval`，不因旧 DB 留有 vector 表就恢复 Embedding，也不以文档数代替使用效果。

## 结果

报告真实查询、scope、命中或 fallback、读回证据与限制；未读到的来源不写成已验证。纯检索不创建 canonical、不做 index/scan/maintain，也不把命中当成 Task 的正式 Knowledge Result。
