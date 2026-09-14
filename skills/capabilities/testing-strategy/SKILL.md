---
name: testing-strategy
display_name: 分层测试
version: 5.3.3
description: Use to choose and execute risk-proportionate tests for code changes, mapping acceptance criteria to reproducible evidence without equating test count with confidence.
---

# 分层测试 — V5.3.3 Record-first

## 本轮范围
`workflow next` 的 `context.validation` 提供当前已绑定仓库的变更路径及 acceptance.md 候选，**不是覆盖证明**，不自动运行检查或授予权限。先从当前有效 AC、Diff、真实调用/引用和已有测试中选择本轮检查；候选列表可被截断，HEAD 到工作区不等于整个任务累计范围，不能因返回路径少就宣称没有其他影响。

优先复用/扩展已有测试；局部反馈只补有保留价值的检查点和一份批次摘要，不重写全面测试单。共享组件按真实消费方选择场景，一行身份/权限改动也要补专项风险验证；影响不明时定向调查或扩展有依据的检查，不盲猜无影响，也不默认全量构建/回归。编译、浏览器、部署和有副作用操作沿用已有授权；无权限时保持待验，不改写为 PASS。模块/整任务收敛仍核对完整有效范围及必要独立审查。

## 方法
1. 将每个关键 AC/风险映射到合适验证方式与 evidence；没有必要时不追求测试数量。
2. 新逻辑优先单元/组件测试；遗留逻辑优先行为保护、集成或回归验证；跨系统行为按真实边界补接口/端到端检查。
3. 涉及数据、权限、接口、消息、定时任务、缓存、配置、兼容或部署时补对应专项验证。
4. 开发自测与独立验收分开：验收角色不直接继承开发者“已通过”的结论，而是独立执行适用检查或核验可复现证据。
5. 记录命令、关键环境、结果与失败原因；无法执行的验证明确标记 NOT_RECORDED/PENDING/边界，不伪造 PASS。

## 数据与页面
production read 必须用户明确确认并最小权限；DML/DDL/生产写必须动作级授权、实际执行、结果核验和回滚/清理证据。页面模式为 human 时，未由 human 实测不能写 PASS；自动页面验证只在部署/刷新就绪且模式授权时执行。

存在 UI/页面 AC 时采用 **Diff-aware** 验证：先由当前 Change Set/Diff 推导受影响 route/page，再用真实浏览器检查声明视口、关键交互、页面状态、Console/Network 和横向滚动。源码 grep、DOM/CSS 字符串断言只能作为静态结构契约，不能单独构成视觉 PASS。稳定路径优先复用 Playwright Test TS，必要视觉才采用获准 Midscene 官方集成；报告采集不等于视觉/人验，动效必须看真实过程。具体执行与 Evidence 规则按需读取 [Visual QA](references/visual-qa.md)。

## 完成判定
PASS 的每个关键结论都能回到真实 evidence；验证 subject 实质变化后旧 PASS 不继续冒充当前 PASS，应重新验证或保持 `PASS_STALE`。
