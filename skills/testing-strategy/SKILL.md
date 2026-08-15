---
name: testing-strategy
version: 5.2.2
description: Use to choose and execute risk-proportionate tests for code changes, mapping acceptance criteria to reproducible evidence without equating test count with confidence.
---

# 分层测试 — V5.2.2 Record-first

## 方法
1. 将每个关键 AC/风险映射到合适验证方式与 evidence；没有必要时不追求测试数量。
2. 新逻辑优先单元/组件测试；遗留逻辑优先行为保护、集成或回归验证；跨系统行为按真实边界补接口/端到端检查。
3. 涉及数据、权限、接口、消息、定时任务、缓存、配置、兼容或部署时补对应专项验证。
4. 开发自测与独立验收分开：验收角色不直接继承开发者“已通过”的结论，而是独立执行适用检查或核验可复现证据。
5. 记录命令、关键环境、结果与失败原因；无法执行的验证明确标记 NOT_RECORDED/PENDING/边界，不伪造 PASS。

## 数据与页面
production read 必须用户明确确认并最小权限；DML/DDL/生产写必须动作级授权、实际执行、结果核验和回滚/清理证据。页面模式为 human 时，未由 human 实测不能写 PASS；自动页面验证只在部署/刷新就绪且模式授权时执行。

## 完成判定
PASS 的每个关键结论都能回到真实 evidence；验证 subject 实质变化后旧 PASS 不继续冒充当前 PASS，应重新验证或保持 `PASS_STALE`。
