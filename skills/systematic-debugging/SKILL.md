---
name: systematic-debugging
version: 5.2.3
description: Use when a test, build, runtime behavior, integration, or verification fails. Drive evidence-based reproduction, hypotheses, root-cause confirmation, minimal repair, and regression prevention.
---

# 系统化调试 — V5.2.3 Record-first

## 方法
1. 固定复现条件：环境、输入、步骤、实际/预期结果、日志或失败证据。
2. 提出少量可证伪假设，优先收集能区分假设的最小证据；同一失败命令/盲改不要无变化重复。
3. 先确认根因，再做满足任务范围的最小修复；不要把“症状消失”直接当成根因被修复。
4. 重跑直接受影响验证，并按风险补防回归测试或检查；说明仍未验证的边界与残余风险。
5. 只有有复用价值时才把调试过程整理进 implementation/verification/knowledge；不为每个尝试写流程事件。

## 边界
若修复需要改变需求、架构、数据语义、权限、安全边界、外部契约或执行高风险生产动作，停止局部调试并升级判断/授权；不要借故障修复静默扩大 scope。
