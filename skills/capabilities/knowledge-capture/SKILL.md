---
name: knowledge-capture
display_name: 知识提炼
version: 5.3.2
description: Use when a completed or maturing task produced verified, reusable project knowledge and a candidate needs to be identified for tp-knowledge.
---

# 知识提炼 — V5.3.2 Record-first

## 目的
只沉淀未来仍有复用价值的事实，不把任务过程日志、聊天、临时 workaround 或未验证推测升级成长期知识。

## 方法
1. 提取已验证的业务规则、技术决策、接口约定、数据语义、风险模式、根因、运维经验或回归场景。
2. 标注来源任务/证据、适用范围、失效条件；与已有 canonical 冲突时显式保留冲突，不静默覆盖。
3. 只有合法、确认的 `knowledge_target` 才形成 Knowledge candidate；候选应包含 project/kind、拟沉淀事实、Task/evidence、适用范围和失效条件。**不得直接写 Knowledge Vault 的 canonical/`90-sources`**；canonical update/create/merge、source registry、index、L1-L4 与 baseline 统一由 `tp-knowledge` 执行。
4. 内容不稳定、目标不明确、证据不足或复用价值低时，不把它升级为长期知识候选，也不直接写最终 Knowledge disposition；若 Runtime 已存在可信 `KNOWLEDGE_CONVERGENCE_REQUEST`，最终由 `tp-knowledge` 完成 targeted search 后写 `NO_DURABLE_INSIGHT` 或其他可信 Result。
5. 重复出现的稳定模式可升级为公共 Skill、Review 检查项或回归测试，但必须基于真实重复证据。

## 边界
知识整理不重新判定技术 PASS，不替代 human acceptance，也不要求为每个任务生成 `quality-and-knowledge.md` 或独立结单阶段。没有可信 Request 时不制造 `NOT_RUN` 或伪 Result；有 Request 时只向 `tp-knowledge` 提供候选与来源，不代替其检索和最终判断。
