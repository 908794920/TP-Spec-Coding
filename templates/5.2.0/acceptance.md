# 验收条件与证据矩阵

| 编号 | 验收条件 | 来源 | 风险等级 | 验证方式 | 证据路径 | 见证等级 | 结论 |
|---|---|---|---|---|---|---|---|
| AC-01 |  | `task.md` / `requirement-test-guide.md` |  |  |  |  | PENDING |

结论列取值：`PASS` / `NOT_REQUIRED` / `PENDING` / `BLOCKED` / `DEFERRED_ACCEPTED` / `OWNER_WAIVED`，可在取值后用“：”补充说明。
`COMPLETED` 不会把 `PENDING`/`BLOCKED` 自动改写为 PASS；真实未执行项必须保持原事实或由 human_owner defer/waive。`DEFERRED_ACCEPTED` 表示 human_owner 明确将测试后置，`OWNER_WAIVED` 表示 human_owner 明确跳过该项；两者都不得伪装成 PASS，且必须由官方 `task acceptance-override` 产生可信账本事件。

## 测试指南对照（requirement-test-guide.md）

存在 `requirement-test-guide.md` 时按其执行；没有该工件不构成默认流程门禁。验证范围以真实需求、代码变更和风险为准。

## 页面验证声明

```yaml
page_verification:
  mode: NOT_REQUIRED # NOT_REQUIRED | human | verification | architecture（NOT_REQUIRED=无需页面验证，亦可缺省整块）
  human_witness: pending # pending | confirmed
  witness_evidence: ""
```

`mode: human` 时，见证等级为 human 的验收项在 `human_witness: confirmed` 前不得 `PASS`；
需要带风险结单时，human_owner 可通过官方 `task acceptance-override --mode defer|waive` 将人工项记为 `DEFERRED_ACCEPTED` 或 `OWNER_WAIVED`；不得由 AI 自行改写。

## 延期验收记录

```yaml
deferred_acceptance: []
# - ac: "AC-XX"
#   recorded_at: ""       # ISO 8601 时间
#   residual_risk: ""        # 残余风险
#   reverify_owner: ""       # 补验证责任方
#   trigger: ""              # 触发补验证的条件
```


## Owner 跳过记录

```yaml
owner_waivers: []
# - ac: "AC-XX"
#   recorded_at: ""       # ISO 8601 时间
#   reason: ""            # human_owner 明确理由
#   residual_risk: ""     # 已知残余风险
#   actor: human_owner
```

## 数据库验证声明

```yaml
database_verification:
  action: NONE # NONE | READ | DDL | DML
  environment: ""
  authorized_by: ""
  execution_evidence: ""
  expected_result: ""
  rollback_or_cleanup: ""
  dml_execution: pending
  dml_residual_risk: ""
```

`action: DML` 必须有实际执行、结果核验和回滚/清理证据；只读证据不能替代。
