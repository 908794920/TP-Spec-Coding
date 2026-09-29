---
name: tp-knowledge-normalization
display_name: Legacy Knowledge 标准化
version: 5.3.6
description: 用于明确授权的旧 Knowledge Vault 迁移与结构标准化，先做确定性 safe changes，再将语义歧义交定向人工判断。
---

# Legacy Knowledge 标准化

仅在迁移或标准化已有 Knowledge Vault 时使用；不因普通检索、最终 Task 收敛或日常增量维护自动启动。先通过 Resolver 确认实际 Vault、项目身份与授权范围，按 [迁移标准](../../../knowledge/rules/migration-standard.md) 处理：

```text
knowledge migrate-plan
→ knowledge migrate-normalize           # dry-run
→ knowledge migrate-normalize --apply   # 仅 safe changes
→ knowledge lint
→ targeted AI review
```

自动层仅处理结构、别名与稳定 ID 可证明的兼容变换。`implemented_by/evolves_into`、缺失 evidence、缺失真实 verification date 等语义歧义留给 targeted review；不得为了 lint PASS 批量发明证据、日期或关系。`--apply` 只覆盖已获准的 safe changes，冲突或归属不明时保持待处理。

报告 dry-run 与实际应用差异、lint 结果、待人工判断对象及未解决风险；通过结构标准化不等于正文事实已获验证。
