# TP-Spec-Coding V5.2.0 生命周期

V5.2.0 的目标是 **完成开发任务 + 任务溯源**。Runtime 是黑匣子记录器，不是研发流程收费站。

## 公开状态

`NEW → ACTIVE → COMPLETED`

异常分支仅有：`ACTIVE/NEW → BLOCKED → ACTIVE`，以及 `NEW/ACTIVE/BLOCKED → CANCELLED`。

研发过程用 `current_phase` 记录：`intake / requirement / product / architecture / discovery / development / verification / delivery / other`。phase 只是查询事实，不是状态门禁。

## 日常记录

- 有 Task 后，角色在一个**有意义的阶段结果**完成时最多记录一次 `task checkpoint`；不要记录微步骤。
- 技术验收使用一次 `task verify`。PASS 必须有真实 `evidence/*`；FAIL/NEEDS_FIX 必须如实记录。
- 真实 blocker 才使用 `task block`，解除后 `task resume`。
- 工作结束使用 `task complete`；Runtime 自动更新 `status.yaml / events.jsonl / generated/*`。
- 正常角色不得调用 `commit --refresh`、手写 generated、手写 stage_handoff 或为了门禁补空工件。

## 硬阻塞范围

仅限：账本/SQLite 完整性不确定；明确 blocker 未解除；高风险动作未授权；试图伪造 PASS/人工验收事实。

设计文档、架构评审、knowledge retrieval、refs、test guide、quality-and-knowledge 等缺失默认是 WARN/按需事实，不阻止正常开发或结单。

## Architecture Review

默认可选。高风险/跨系统/数据库或安全架构变化、多条实质方案、高不确定性、用户明确要求时触发。没有独立评审不能自动解释成“方案错误”，也不能成为普通任务的开发门禁。

## COMPLETED 语义

COMPLETED 表示任务工作已结束，**不等于所有推荐动作均 PASS**。`generated/final-result.md` 必须展示实际验证事实，例如 PASS / FAIL / NEEDS_FIX / NOT_RECORDED，以及真实 defer/waive 与残余风险。历史完成任务不可回写伪造新事实。
