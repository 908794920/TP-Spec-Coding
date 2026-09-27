---
name: tp-knowledge-task-convergence
display_name: Task 知识与记忆收敛
version: 5.3.5
description: 用于最终 Task 交付时消费可信 Knowledge Request，逐项评估输入、定向判重或维护 canonical，并记录 Knowledge Result 与项目 Memory 评估；不运行全库维护链。
---

# Task 知识与记忆收敛

## 入口与可信输入

集成交付工程师按每 Task 交付调用 [knowledge-capture](../../capabilities/knowledge-capture/SKILL.md) 提炼有效需求与各步骤材料，并通过正常 `delivery-converge` 为 L0–L3 创建或复用 `KNOWLEDGE_CONVERGENCE_REQUEST`；没有 knowledge signals 也要评估，不强制新增知识。先只读 `tp-spec knowledge task-inputs --task <TASK-ID> --task-dir <TASK-DIR> --db <DB>`，按清单逐项读取来源，再提交 `knowledge task-converge --assessment FILE|-`。`task-inputs` 本身不创建 Request、不查询 Knowledge，也不证明正文已读。

核对可信 Request、`request_current`、当前 READY、有效 Change Set、输入 digest 与实际适用的 Verification/Review。轻量任务不适用的前置为 0，不伪造 PASS。输入问题或最终候选失效时保持待处理，由原交付流程解决后重发或复用 Request；本能力不重裁软件验收，不手改 Runtime。完整字段、命令、复用、失败和历史兼容契约只在本类任务中读 [Task 知识与记忆收敛契约](../../../agents/tp-knowledge/references/task-convergence.md)，并以该原路径为权威。

## 逐项处置

- 覆盖所有真实输入；已替代或临时内容保留来源与分类，不升级为永久约束。只读已知工件和明确引用，不全盘递归扫描其他 Task、历史或 Vault。
- 仅在 current project + registered shared scopes 做最小 targeted search；该次收敛关闭 global fallback。每个候选保留实际 query、相关输入与具体判断，不以主题相似代替精确命中。
- `CREATED / UPDATED`：在获准范围内先写好 exact canonical，绑定本 Task 和该候选准确的文件、事件或 Work locator；正式命令读回内容/来源、局部 lint 并索引该条。`UPDATED` 还要有同一 canonical ID 的真实定向命中。
- `DUPLICATE`：实际搜索命中并读回已有 exact canonical，不复制第二份正文。`NO_DURABLE_INSIGHT`：同样实际阅读、执行非空定向 query，并记录来源和具体原因，不绑定伪目标。
- 一份 assessment 记录逐项 `coverage`、Knowledge 处置及 Memory 判断；混合结果以 `knowledge_results` 为准，不能把摘要 disposition 推断到全部候选。Result 保留检索、目标内容与适用的单条索引 receipt。

## 项目记忆与结果复用

使用 [tp-memory-capture](../../capabilities/tp-memory-capture/SKILL.md) 判断项目 Memory 正文及根 `AGENTS.md` 薄入口的可发现性；已评估与已持久化分开。保存或已覆盖需真实目标、片段和读回；可选项未保存要记 `NOT_PERSISTED`、责任与恢复条件，不能称已保存，也不把未持久化误称未评估。授权不清只停止对应写入；临时/已替代信息不升级为永久规则。

相同稳定输入、assessment、检索上下文和目标读回可复用原 Result；输入变化只重评受影响项，不重跑仍有效的技术检查。旧 Request 保留原参数兼容，旧终态不追补；采用旧 closeout 但缺当前学习 Request 的在途任务走正常 `delivery-converge`，不补造历史、Result 或 PASS。普通 FACT 不替代正式 Result；索引/telemetry 与 Runtime 不构成跨库原子事务，失败按实际 `external_effects` 和 journal/reconcile 恢复。

## 边界与交付

本能力不启动全库 scan、外部文档 ingest、Golden Set、audit、migration/normalization、安装或发布。最后由集成交付工程师核对 `task complete --check` 和实际 Result；本领域只报告逐项处置、Memory 评估/保存差异、receipt 与未解决条件。
