---
name: technical-review
version: 5.2.3
description: Use for independent implementation review. Check real code/diff, traceability, engineering risks, and evidence without letting the implementer self-approve or requiring workflow bookkeeping.
---

# 独立技术审查 — V5.2.3 Record-first

## 原则
独立验收不能只复述 implementation 摘要。必须检查适用的真实代码/diff/配置、测试和 evidence，并明确哪些结论是已验证、哪些只是未覆盖边界。

## 检查矩阵
1. 需求/AC 覆盖、范围偏差和无关修改。
2. 错误处理、边界、并发、事务、幂等、资源释放和失败恢复。
3. 权限/安全/隐私/敏感数据、密钥与意外生成物。
4. 数据查询/写入、迁移/回滚、环境和授权证据。
5. 接口兼容、配置、消息、定时任务、缓存、部署/运维影响。
6. 测试质量、证据可复现性、文档与真实实现一致性。

## 结论
- `PASS`：适用验证真实通过，且必须有可定位 evidence。
- `NEEDS_FIX`：范围内明确缺陷可最小修复并复验。
- `FAIL`：实现不满足需求或存在需要较大返工的问题。

局部修复不得引入新需求/架构/数据语义或未授权生产动作。Review 结束后可直接由 Runtime 记录 verification；不需要额外交接/结单 bookkeeping 才使结论可信。
