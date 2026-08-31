# Legacy Knowledge 标准化

适用条件：迁移或标准化已有 Knowledge Vault 时读取。


已有 Vault 迁移先执行 deterministic normalization，再让模型处理语义歧义：

```text
knowledge migrate-plan
→ knowledge migrate-normalize           # dry-run
→ knowledge migrate-normalize --apply  # 仅 safe changes
→ knowledge lint
→ targeted AI review
```

自动层只允许结构/别名/稳定 ID 可证明的兼容变换；`implemented_by/evolves_into`、缺失 evidence、缺失真实 verification date 等必须留给 targeted review。不得让模型为了 lint PASS 批量发明 evidence/date/关系。详见 `knowledge/rules/migration-standard.md`。
