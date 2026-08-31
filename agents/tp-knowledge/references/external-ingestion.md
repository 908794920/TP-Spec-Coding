# 外部文档接入

适用条件：接入或重新处理已登记的外部文档批次时读取。


按 `automation/knowledge/ingest-batch.md` 与 `knowledge/rules/ingestion-standard.md` 执行：

```text
REGISTER → MANIFEST/HASH → DEDUP → CONVERT/QUARANTINE
→ GROUP/TRIAGE → SEARCH EXISTING CANONICAL
→ AI READ/UPDATE/CREATE/MERGE → FINAL TRUTH SCAN → INDEX → VERIFY → AUDIT → FINALIZE
```

默认本地文档转换直接使用 Base 固定的 Microsoft MarkItDown 运行时，不重复实现 PDF/Office 解析器：

```text
tp-spec knowledge ingest register --workspace-root <workspace> --project <id> --batch <name> --source-root <path>
tp-spec knowledge ingest convert  --workspace-root <workspace> --batch <name>
```

`convert` 只对已登记、hash 未漂移的本地 `convert_candidate` 生成 machine-owned Markdown intake；成功后来源仍保持 `pending`，不会自动升级成 canonical truth。转换失败只隔离对应 source 为 `quarantined`，后续 disposition / canonicalization 仍由本 Domain 按证据处理。

目标不是“每份 Source 都生成一篇 Knowledge”，而是 **Registered Source Accountability = 100%**。允许 disposition：

`pending / canonicalized / merged / source_only / duplicate / superseded / quarantined / excluded`。

项目归属、原始文档删除、冲突 merge/split、破坏性转换必须由 human_owner 明确授权；无人值守定时会话不得擅自决定。
