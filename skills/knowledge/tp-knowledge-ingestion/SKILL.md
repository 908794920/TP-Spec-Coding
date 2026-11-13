---
name: tp-knowledge-ingestion
display_name: 外部文档接入
version: 5.4.0
description: 用于获准的外部文档命名批次接入或已登记批次重处理，涵盖注册、哈希核对、转换分流和有证据的 canonicalization；不把每份 source 自动变成 Knowledge 正文。
---

# 外部文档接入

## 适用与批次流程

用于获准的外部文档命名批次接入（含首次登记），或重处理已登记批次。按 [批次协议](../../../automation/knowledge/ingest-batch.md) 与 [接入标准](../../../knowledge/rules/ingestion-standard.md) 执行：

```text
REGISTER → MANIFEST/HASH → DEDUP → CONVERT/QUARANTINE
→ GROUP/TRIAGE → SEARCH EXISTING CANONICAL
→ AI READ/UPDATE/CREATE/MERGE → FINAL TRUTH SCAN → INDEX → VERIFY
→ L4（适用时）→ FINALIZE → SNAPSHOT-COMMIT
```

默认本地文档转换使用 Base 固定的 Microsoft MarkItDown 运行时，不重新实现 PDF/Office 解析器：

```text
tp-spec knowledge ingest register --workspace-root <workspace> --project <id> --batch <name> --source-root <path>
tp-spec knowledge ingest convert  --workspace-root <workspace> --batch <name>
```

`convert` 只对已登记且 hash 未漂移的本地 `convert_candidate` 生成 machine-owned Markdown intake。转换成功后来源仍为 `pending`，不自动成为 canonical truth；失败只隔离相应 source 为 `quarantined`，后续 disposition/canonicalization 仍须基于证据处理。

## 来源责任与授权

目标是 **Registered Source Accountability = 100%**，不是每份 Source 都生成一篇 Knowledge。允许 disposition：`pending / canonicalized / merged / source_only / duplicate / superseded / quarantined / excluded`。先定向搜索已有 canonical，优先适当更新或归并；正文断言和来源要能回到注册 source/evidence。

项目归属、原始文档删除、冲突 merge/split 和破坏性转换须由 human_owner 明确授权；无人值守定时会话不得擅自决定。批次登记不授权跨项目全库检索、自动删除原件或将外部方法包当文档接入。

## 结果

报告批次、注册与 hash 状态、转换/隔离与 disposition、canonical 精确目标及实际收口结果。按 [最终真相绑定](../../../automation/knowledge/ingest-batch.md#batch-finalization) 核对适用 L4、批次终结与基线提交各自结果，`pending` 或 `quarantined` 如实保留。
