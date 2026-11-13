---
name: tp-knowledge-maintenance
display_name: Knowledge 内容维护
version: 5.4.0
description: 用于已登记 source/canonical 的增量变化、定向正文维护、真相扫描、索引、验证与 baseline 推进；不把 Task 收敛扩成全库维护。
---

# Knowledge 内容维护

## 对象与准备

用共享 Content Systems Resolver 定位 `knowledge_physical_root`、registry、projection DB 和 meta root，复用仍适用的解析与诊断证据。首次接入或需核对健康缺口时使用 `tp-spec knowledge doctor --workspace-root <workspace>`，按本次动作读取相应规则。

项目正文处置仅覆盖获准的 source/canonical；先定向定位已有 canonical，优先更新可用条目。物理 Vault 的 `maintain` / `scan` 写共享 Change Set，索引更新、`verify`、`audit` / `audit-record` 和基线提交也有库级写入。执行这些写入须确认本次授权覆盖相应物理库和操作，项目正文授权本身不涵盖库级写入。仅处理项目内容时，继续获准的定向阅读、证据核对或正文修改，如实交代尚未更新的投影、验证和基线。

## 增量处理

库级维护按 [既有维护状态分支](../../../automation/knowledge/daily-maintenance.md#3-act-on-maintain-result) 接续，以实际 `maintain` 返回为准。其 Change Set 即使在 `NO_CHANGE` 时也已写入；此分支直接收口。`VALIDATE` 表示知识真相未变、投影当前但验证绑定需刷新，执行 `verify` 核对实际结果。下列顺序用于影响知识真相的维护。

```text
maintain → deterministic diff/classify → 必要时 AI targeted read/update
→ final truth scan（AI 写入后重新绑定）→ projection update
→ verify L1–L3 → 必要时 L4 → audit-record → snapshot-commit
```

- source/evidence 的语义变化由 AI 判断是否影响长期知识；cosmetic 或 index-only 变化不调用模型改正文，不每天全文重写。
- 删除、冲突、归属不明或 merge/split 不确定时 fail-closed，停在需要真实判断的对象；项目归属或破坏性处置不能由维护身份自行扩大授权。
- AI、canonical、evidence 和 disposition 最终写入后必须重新 `knowledge scan`。不能拿 AI UPDATE 前的 Change Set 做 L4、更新投影或推进 baseline。
- 当前 truth、verify、必要 L4 与 projection 绑定同一状态后才能推进 baseline；`audit-record` 和 `snapshot-commit` 依据实际结果执行，不把某一步成功冒充全链完成。
- canonical Markdown 与注册 evidence 是事实源，FTS/link/graph 是可重建投影；检索/读取日志仍是使用证据，不能因重建索引而直接删库。强断言需真实 evidence，新或实质更新优先用结构化 `evidence_refs`；不让模型编造验证日期、责任或来源。

## 范围与结果

内容判断围绕当前项目与注册 shared 的明确变化；其他 Task 仅凭显式 candidate/evidence 或获准维护范围进入，不扫描全部 Task 历史自动灌库。与最终 Task 的局部 Request 收敛分开，不能因 task-converge 自动运行本链。同一库有未解决的 staged 变化时保留旧 baseline。报告实际正文处置与库级结果，列出未完成步骤及原因。
