---
name: systematic-debugging
display_name: 系统化调试
version: 5.3.2
description: Use when a test, build, runtime behavior, integration, or verification fails. Drive evidence-based reproduction, hypotheses, root-cause confirmation, minimal repair, and regression prevention.
---

# 系统化调试 — V5.3.2 Record-first

## 修改前门禁：Tight Red Feedback Loop

面对 Bug、测试失败、运行异常、集成失败或性能回退时，**修改产品代码之前**必须先建立一个针对用户实际症状的反馈回路，并且已经实际执行至少一次、观察到当前失败。仅证明“命令能运行”“没有抛异常”或附近测试失败，不算捕获当前症状。

反馈回路必须尽量同时满足：

- **Red-capable**：能对用户报告的错误结果、错误状态、异常、性能指标或可观察行为给出明确失败判定；
- **Deterministic**：重复执行应得到一致判定；随机/并发问题至少记录可接受的高复现率与条件；
- **Fast**：足以支持多轮假设验证，优先秒级；
- **Agent-runnable**：无需持续人工点击即可重复执行；确需人工参与时使用结构化 HITL 并记录输入与结果。

按最小成本优先选择：

```text
已有失败测试
→ 新增最小回归测试
→ CLI/HTTP fixture
→ Headless Browser
→ Trace/Event replay
→ Throwaway harness
→ Property/Fuzz loop
→ Differential/Bisect loop
→ 结构化 HITL
```

可以跳过不适用项，但必须能说明选定回路为什么覆盖当前症状。若当前环境无法复现或无法建立可信回路，记录 `LOOP_UNAVAILABLE`、已尝试方法和缺失证据，请求可复现环境、脱敏日志/Trace/HAR/载荷，或增加临时诊断 instrumentation；不得把“无法复现”转换成无证据修改。

## 方法

1. 固定复现条件：环境、输入、步骤、实际/预期结果、日志或失败证据，并保存上面的已执行反馈回路。
2. 提出少量可证伪假设，优先收集能区分假设的最小证据；同一失败命令/盲改不要无变化重复。
3. 先确认根因，再做满足任务范围的最小修复；不要把“症状消失”直接当成根因被修复。
4. 修复完成前同时闭环：最小回归在修复前能够失败、修复后通过，并重新执行原始、未最小化的反馈回路确认用户症状已消失。
5. 删除或明确隔离临时诊断 instrumentation、Throwaway harness 和一次性 Artifact；若架构没有正确 test seam，记录缺口，不用错误的浅层测试制造信心。
6. 按风险补必要回归检查并说明仍未验证的边界与残余风险；只有有复用价值时才把调试过程整理进 implementation/verification/knowledge，不为每个尝试写流程事件。

## 边界

本门禁只强化故障、失败和性能回退类任务，不把所有普通开发任务强制改成 TDD。若修复需要改变需求、架构、数据语义、权限、安全边界、外部契约或执行高风险生产动作，停止局部调试并升级判断/授权；不要借故障修复静默扩大 scope。
