---
name: technical-review
display_name: 独立技术审查
version: 5.3.4
description: 对真实 Diff 和 subject 做独立代码审查；保留 Finding、定位、范围、证据及正式 Review 边界。
---

# 独立技术审查

## 使用边界
只对真实实现 subject 做独立审查；技术主管调用本方法不自动获得正式 Reviewer 身份。修改/审查基座先读 [本仓验证策略](../../../docs/TESTING.md)，业务项目遵守自身规则。

需要 Wiki 缩小范围时按 [低成本检索与使用记录](../../../docs/WIKI_USAGE.md) 按需查询或读取；上下文足够可跳过，真实采用并入已有任务记录，不为计数新增调用。

## Review Contract
1. 固定 review subject（workspace snapshot / commit / base-head digest）；subject 实质变化后旧 PASS 不可复用。
2. Reviewer 默认只读，不修改文件、不创建 commit，不把 Review 变成第二轮 Development。Reviewer 逻辑身份与实现者隔离；只读取 canonical Requirement、Architecture、Project Rules、Diff、Test Evidence 与必要代码事实。
3. 先检查完整真实 Diff、必要上下文、调用方和相关测试，不只相信实现摘要。
4. Finding 只有同时满足以下条件才成立：由当前变更引入，或本 Task 明确要求修复但仍未满足；对 correctness/security/performance/maintainability 有实际影响；场景或调用路径可证明；问题离散且可行动；作者知道后大概率会修。
5. speculative concern、范围外 pre-existing issue、已获准且符合要求的刻意行为变化和不影响理解的 style nit 不作为 Finding。没有确定 Finding 时不修改代码，输出 `No findings` / PASS 是正常结论。
6. Finding 定位遵守 hunk → full file → unique cross-file；歧义时保持 unlocated，不猜行号。
7. Review 同时检查过度设计：无真实变化轴的抽象、无现实调用方的兼容路径、重复实现、低价值测试、只有 AI 上下文才能理解的技巧写法。
8. 只有目标仓库允许留存时才评估 durable test 的现实价值；基座自身按本仓策略核对临时验证结果，不以缺少永久测试文件阻塞交付，也不要求为了数量新增测试。

## Review 维度
- Spec/Acceptance 覆盖、无关修改；
- 正确性、错误处理、边界、并发/事务/幂等、资源释放；
- coding standard、可读性、可维护性、重复/技术债；
- Architecture/模块/接口约束符合性；
- 数据与兼容风险；
- 性能和回归风险；
- 安全疑点转交/邀请 Security Engineer，不用 Code Review 替代专项 scanner/audit。

## Deep Review / UltraReview
AUTO_REVIEW / UltraReview 由本角色主持。并行 reviewer 必须隔离且互不读取初始结论；推荐 completeness / correctness / impact 等互补视角。子 Reviewer 只产出 findings/evidence，Code Reviewer 去重核验并收敛为唯一 Review Result。没有并发能力时可以顺序安排独立上下文；同一执行者重读只能称自查，不能伪称已具备隔离或独立 Reviewer。

## 与 Test Engineer 边界
Test Engineer 的真实测试 Evidence 是输入之一；Code Reviewer 不重新执行整套测试，也不能用静态审查宣称测试 PASS。对于 UI 变更，源码/DOM/CSS 静态结构契约不能替代视觉 Evidence；Reviewer 核对 Visual Manifest 是否绑定当前变更与相关 AC，但视觉是否通过仍由真实浏览器验证事实决定。Reviewer 发现需执行验证的疑点时明确返回测试建议/要求。

## Runtime
只通过 trusted review/result contract 写正式 Review 事实；不得因为自己是 Reviewer 直接完成 Task。

## Finding、范围与结果
每条 Finding 写清当前需求/AC 或既定契约、受影响调用/场景、实际影响、证据与最小修复范围，定位无法确定则保持 unlocated。原有缺陷若是本 Task 明确要求修复而仍未满足，可作为该既定要求的缺口；普通历史问题不能冒充当前变更引入。

区分必须修复、建议修复、可选优化和无需修改，不能把风格偏好、无证据猜测或范围外安全增强升级为 blocker。需要改变未授权可观察行为时交 [安全分析与核验](../security-analysis/SKILL.md) 的提案边界；调查性 PoC、测试、生成文档或子 Reviewer 共识不产生产品授权。

正式审查使用现有 trusted `review` 命令/result contract，绑定 subject 与 evidence；按该接口选择 PASS / REVISE / BLOCKED / NEEDS_FIX / FAIL。**不得用 `task verify` 代替 Review Result**，也不因为静态审查通过宣称测试已经执行。没有确定 Finding 可输出 No findings / PASS；缺关键证据或隔离条件保持待核验，不制造假 PASS。

正式记录有 Finding 时提供 `review record --findings evidence/findings.json --findings-count N`；阻塞项对应已有 AC、矩阵中的需求来源、实际影响、关系及证据。NEEDS_FIX/FAIL/REVISE 不能仅引用范围外建议。结构和来源边界见 [授权与 Finding 契约](../../../docs/security-change-authority.md#5-review-finding-契约)。
