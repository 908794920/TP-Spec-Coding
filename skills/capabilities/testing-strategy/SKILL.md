---
name: testing-strategy
display_name: 分层测试
version: 5.3.4
description: Use to choose and execute risk-proportionate tests for code changes, mapping acceptance criteria to reproducible evidence without equating test count with confidence.
---

# 分层测试 — Record-first

## 本轮范围
修改 TP-Spec-Coding 自身源码时以 [本仓验证策略](../../../docs/TESTING.md) 为准，当前功能的临时验证执行后清理；可复用交互脚本按下方 Visual QA 方法保存在对应项目 `.tp-spec/memory/`，属于明确保留的长期资产，包含本仓自身。其他测试留存遵守目标仓库规则，不因通用方法、风险等级或最终交付自动全量回归。

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

存在 UI/页面 AC 时采用 **Diff-aware** 验证：先由当前 Change Set/Diff 推导受影响 route/page，再用真实浏览器检查声明视口、关键交互、页面状态、Console/Network 和横向滚动。源码 grep、DOM/CSS 字符串断言只能作为静态结构契约，不能单独构成视觉 PASS。稳定路径优先复用 Playwright Test TS，必要视觉才采用获准 Midscene 官方集成；报告采集不等于视觉/人验，动效必须看真实过程。测试时主动完成已有脚本复用、稳定场景提炼、带断言的真实回放和项目 Memory 保存评估；不等用户逐次提醒，不为每次点击留一份脚本。具体闭环与 Evidence 规则按需读取 [Visual QA](references/visual-qa.md)。

## 完成判定
PASS 的每个关键结论都能回到真实 evidence；验证 subject 实质变化后旧 PASS 不继续冒充当前 PASS，应重新验证或保持 `PASS_STALE`。


## 独立核验与缺陷
不要只相信开发摘要；按当前 AC 核对真实代码、调用/配置和可复验证据，包含适用的错误/资源释放/恢复、事务并发幂等、数据迁移/批量一致性、消息/定时/缓存及运行兼容。安全专项由安全工程师主持，测试仍覆盖已声明的安全 AC；不自行增加需求外强制回归。

NEEDS_FIX 表示范围内可最小修复，FAIL 表示较大实现问题或未满足既定要求；在父 Task 内创建/复用对应 Fix Work，父步骤等待后原位复验。LOCAL_REWORK 不新增需求、架构、权限或数据语义；这些变化交正式责任角色与 human_owner。保留原完成历史，subject 实质变化使受影响 PASS_STALE，不能复用旧结果。

## 执行、临时工件与正式记账
临时诊断用登记的系统 Temp，不在项目工作区造 .tmp。用户原件可只读复制，不修改、移动、覆盖或删除；intake、正式 Task 工件、Evidence 和业务仓库获准的持久回归均不是临时清理对象。按 ownership 和授权清理自己的资产，残留只报告；CLEANUP_PENDING 不是 Task 状态，不逆改已提交事实。

需要临时根登记、工作段收口或已知中断恢复时，定向读 [生命周期操作参考](../../../docs/agents/tp-software-lifecycle.md)；匹配 task/role/agent 的正常、失败或暂停边界记录 work end，强制中断未知时不补造 END。不因加载测试角色就逐条执行清理。

结束一次真实测试通过 `task verify --decision PASS|FAIL|NEEDS_FIX` 留证，PASS 至少绑定真实 evidence；未执行的人验保持待验，只有 human_owner 能按官方 acceptance-override 对已核验范围确认。仅在获准指定 pytest 用例时使用 task run-pytest；已有输出用 checkpoint --result-report，不为记账重跑。采集不等于签 PASS，协调者汇合用 --recorded-result，不代签独立角色。测试角色不自行 task complete，继续交生命周期解析 Review/Delivery。

涉及安全提案时按 [授权与调查证据契约](../../../docs/security-change-authority.md) 声明本次行为范围。调查 PoC 用 read_only/isolated_poc 并登记真实来源，不能作为正式 failing regression。`task run-pytest`/`verify` 的 `--security-change`、`--scope-path`、`--scope-ac` 是范围声明，不是工具许可；正式结果使用前重查当前批准及原始证据。
