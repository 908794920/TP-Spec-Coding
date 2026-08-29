# 实现反模式与反合理化参考

## 顺手重构一下
**Bad：** 当前需求已满足，再把相邻模块“顺便整理”。
**Why：** 扩大 Diff 与回归面，Review 无法区分需求改动和偏好改动。
**Better：** 只清理本次改动直接制造的 orphan；历史问题另记 Finding/Task。

## 为了以后扩展先抽象
**Bad：** 单一当前实现提前增加 Strategy/Factory/接口层。
**Why：** 没有真实变化轴，抽象只增加理解和维护成本。
**Better：** 保持直接实现；第二个真实变体出现时再抽象。

## 保留新旧两条路径更安全
**Bad：** 新实现已经替代旧实现，但继续保留无真实调用方的旧路径。
**Why：** 双路径会漂移并增加测试矩阵。
**Better：** 完成 Usage Footprint 后删除被本次变更明确替代且无兼容需求的路径。

## 多写几个测试更保险
**Bad：** 已有行为测试覆盖，再新增大量源码字符串/常量测试。
**Why：** 测试数量增加但故障发现能力没有增加。
**Better：** 只补真实 regression gap；一次性诊断放 Temp。

## 没找到静态调用所以可以直接删
**Bad：** `rg` 无结果后直接删除方法。
**Why：** Spring、反射、MyBatis XML、JSP、配置、消息/定时任务、SPI、外部 API 都可能形成非静态调用。
**Better：** 完成 Usage Footprint 后再修改/删除。

## Delivery 中只改一行不用回开发
**Bad：** Integration Engineer 发现产品问题后直接修改代码并沿用旧 PASS。
**Why：** 交付角色越界，旧 Verification/Review 不再对应当前内容。
**Better：** 记录 Finding，返回 Development，修复后重新验证和 Review。

## 静态页面契约全绿所以视觉通过
**Bad：** DOM/CSS 字符串断言通过就宣布 UI PASS。
**Why：** 无法发现遮挡、错位、真实交互、长文本、加载状态和运行时错误。
**Better：** 保留静态契约作为辅助，并执行真实浏览器视觉/交互验证。
