# 验收条件与证据矩阵

| 编号 | 验收条件 | 来源 | 风险等级 | 验证方式 | 证据路径 | 见证等级 | 结论 |
|---|---|---|---|---|---|---|---|
| AC-01 |  | `task.md` / `requirement-test-guide.md` |  |  |  |  | PENDING |

结论列取值：`PASS` / `NOT_REQUIRED` / `N/A` / `PENDING` / `BLOCKED` / `DEFERRED_ACCEPTED` / `OWNER_WAIVED`，可在取值后用“：”补充说明。
`COMPLETED` 前每个 AC 必须得到明确处置；`PENDING`/`BLOCKED` 不得直接结单。真实未执行项必须保持原事实，或由 human_owner defer/waive。`DEFERRED_ACCEPTED` 表示 human_owner 明确将测试后置，`OWNER_WAIVED` 表示 human_owner 明确跳过该项；两者都不得伪装成 PASS，且必须由官方 `task acceptance-override` 产生可信账本事件。

## 测试指南对照（requirement-test-guide.md）

存在 `requirement-test-guide.md` 时按其执行；没有该工件不构成默认流程门禁。验证范围以真实需求、代码变更和风险为准。

## 页面验证声明

```yaml
page_verification:
  mode: NOT_REQUIRED # NOT_REQUIRED | human | verification | architecture（NOT_REQUIRED=无需页面验证，亦可缺省整块）
  human_witness: pending # pending | confirmed
  witness_evidence: ""
  visual:
    required: false
    viewports: [] # 例："375x812"
    routes: []
    reference_assets: []
    required_states: [] # normal / loading / empty / error / long-text
    evidence_manifest: "" # required=true 时填写 evidence/visual/manifest.json
```

`mode: human` 时，见证等级为 human 的验收项在 `human_witness: confirmed` 前不得 `PASS`；
需要带风险结单时，human_owner 可通过官方 `task acceptance-override --mode defer|waive` 将人工项记为 `DEFERRED_ACCEPTED` 或 `OWNER_WAIVED`；不得由 AI 自行改写。

`visual.required: true` 时，Verification PASS 必须提供绑定当前 `change_set_id` 的真实 Visual Manifest；静态 DOM/CSS/源码结构契约不能单独满足视觉 AC。Visual Evidence 统一放在 `evidence/visual/`，可通过 `task artifact-path --kind visual-evidence --ensure` 获取规范目录。

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

## 数据库操作声明

```yaml
database_operations: []
# - id: DB-01
#   type: DML # READ | DML | DDL
#   acceptance_refs: [AC-XX]
#   environment: development
#   status: EXECUTED # PLANNED | EXECUTED | NOT_EXECUTED | NOT_REQUIRED
#   authorized_by: human_owner
#   artifact_ref: evidence/sql/db-01-statement.sql
#   execution_evidence: evidence/sql/db-01-result.md
#   expected_result: ""
#   rollback_or_cleanup: evidence/sql/db-01-rollback.md
#   residual_risk: ""
```

- `EXECUTED` DML/DDL 必须有 human_owner 授权、SQL 工件、真实执行证据和回滚/清理说明；`EXECUTED` READ 至少需要执行证据。
- `NOT_EXECUTED` 不得填写伪执行证据；`PLANNED`/`NOT_EXECUTED` 在结单前必须由关联 AC 的 `NOT_REQUIRED` / `N/A` / `DEFERRED_ACCEPTED` / `OWNER_WAIVED` 明确处置。
- 旧 `database_verification` 仅作为历史/迁移输入，新任务不再生成。
