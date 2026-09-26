---
artifact: requirement
task_id: "TASK-YYYYMMDD-XXX"
artifact_contract:
  version: "5.3.5"
status: ready
source_refs: []
---

# Requirement

<!-- 本工件承担当前范围时，Task 只引用这里，不复制维护同一有效区。 -->
<!-- tp-spec:current:start -->

## Goal

<!-- 明确用户/客户最终要实现的结果。 -->

## Scope

<!-- 只记录真实范围；没有额外范围时保持简洁。 -->

## Business Rules

<!-- 记录会影响实现与验收的业务规则。 -->

## Acceptance Criteria

<!-- 记录足以判断 Requirement Ready 的验收条件。 -->

## Constraints / Open Questions

<!-- 仅在真实存在约束或未决问题时填写；不要为模板完整制造空问题。 -->

## 当前有效决定与来源

<!-- 写明来源、适用范围、待核实假设、验收和操作边界；不是将推荐或最新文本升级为授权。 -->

<!-- tp-spec:current:end -->

## 历史决策 / 备注

<!-- 保留 SUPERSEDED、继任结论及依据；复杂决定按需引用已有 requirement-decisions.md，不复制完整历史到当前区。 -->

## Decision Dependencies / Current Frontier（仅复杂 L2/L3，按需）

只有多个关键决策存在前置依赖时才保留本节；没有依赖决策时删除本节，继续使用最小澄清路径。

- Decision dependencies：列出当前需求实际相关的 `decision_id → prerequisites`，详细记录放入按需的 `requirement-decisions.md`。
- Current Frontier：列出所有前置条件已解决、技术事实已调查且现在可以决定的未决 decision；实际只询问其中真正 blocking 的问题，或组成最小 coherent batch。尚待事实调查或前置 decision 的问题不得提前询问。
- Requirement Ready：`blocking_open == 0`，且关键数据、权限、安全、生产和核心业务未知均已明确处理。
