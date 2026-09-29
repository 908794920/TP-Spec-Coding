---
name: tp-knowledge-maintenance
display_name: Knowledge 内容维护
version: 5.3.6
description: 用于已登记 source/canonical 的增量变化、定向正文维护、真相扫描、索引、验证与 baseline 推进；不把 Task 收敛扩成全库维护。
---

# Knowledge 内容维护

## 对象与准备

只处理本次获准范围内已有 source/canonical 的真实变化。用共享 Content Systems Resolver 解析 `knowledge_physical_root`、registry、projection DB 和 meta root，不硬编码 Vault 路径或依赖 `.tp-spec/knowledge` Junction。读取当前 Base 的 `knowledge/README.md` 与适用的 `knowledge/rules/*`；先运行 `tp-spec knowledge doctor --workspace-root <workspace>`，需要内容变更时再运行 `knowledge maintain`。检索先定向找已有 canonical，更新已有条目优先于新增，不为覆盖率制造低价值正文。

## 增量处理

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

默认围绕当前项目与注册 shared 的明确变化；其他 Task 仅凭显式 candidate/evidence 或获准维护范围进入，不扫描全部 Task 历史自动灌库。与最终 Task 的局部 Request 收敛分开，不能因 task-converge 自动运行本链。报告变更分类、实际正文处置、final scan/索引/各级验证、audit 与 baseline 状态；未完成的步骤和阻塞分别说明。
