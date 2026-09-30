---
name: delivery-convergence
display_name: 交付收敛
version: 5.3.7
description: 每个 Task 最终交付时核对范围、候选、验收与知识记忆；复用有效结果，不代签或补造事实。
---

# 交付收敛

## 责任与触发
每个 Task（L0–L3）最终交付时读取；L0/L1 可紧凑核对，不复制 L2/L3 全部阶段。不是每次 checkpoint 都重跑。项目经理精确接收各 Work、组织依赖与最终交付；集成交付工程师执行已获准的实际 apply、冲突处置和专业收敛，不代签测试/审查/人验，也不借集成顺手修产品 Finding。

## 完整范围与事实
最终核对 canonical 完整有效范围、所有必要 AC 与已登记仓库，不能用最后一次局部 checkpoint 代替早期后端/身份变更；缺口保持未完成，排除项保留 owner 来源。具体接口按需读 [完整仓库范围与最终交付](../../../docs/agents/tp-software-lifecycle.md#完整仓库范围与最终交付)。

应尽量记录确定性 Git snapshot：before_head / after_head / merge_commit（适用时），绑定最新 Test/Review subject，避免“AI 说已经合并”替代仓库事实。

所有必要 Work 的结果/依赖、仓库、最终集成候选、适用 Verification/Review、AC/Owner Acceptance、数据库/迁移/操作处置和遗留风险一起核对。Work PASS 的相加不是 Task 集成通过。实际接收、冲突处置、中间/最终候选按 [Work 结果契约](../../../docs/WORK_UNITS.md)登记；中间候选不取消剩余 Work 与最终验收义务。Git branch/commit 适用时记录；否则保留明确的工作区 snapshot/Patch 与内容身份，不强求 Work commit。apply/merge/rebase/push/清理/发布/重启均依当次授权，不从计划推断权限。

发生实际集成时，由集成交付角色提交本角色/实际执行者归属的输出及冲突处置依据；项目经理按精确结果事件接收，由已记录 coordinator 登记 record-only candidate。候选权限仍校验原 coordinator，不因集成角色身份默认开放。Work 提交、接收、候选、步骤完成、专业 PASS、业务验收与 Task complete 不是同一事实；步骤完成保留适用参与者/coordinator 规则，不增项目经理独占门禁。

## 稳定收敛顺序
1. 先调用现有只读 `task complete --check`，核对所有已知缺口和未知项，而非反复正式 complete 探路；Runtime 没返回的项目按上述范围核对，不能声称旧接口已完整汇总。已发生的人验/授权核验来源，未发生仍按适用流程完成。
2. 先处理会影响绑定的有效 AC、数据库/迁移/操作声明、真实步骤记录和交付物；不补造过去阶段、时间或验收。UI 确认不能推断数据库已执行，部分 AC 确认不能外推全 PASS。
3. 固定最终产品 subject；只复用仍适用的测试/审查，源码/交付物、AC 实质或证据变化只补受影响复验。普通摘要/checkpoint 不能假装是新产品，也不能把产品规则文件藏作 metadata。
4. 完成集成交付检查、证据收集和清理后，先结束这段真实参与，再以稳定输入记录 Delivery 并执行下方知识/记忆收敛；不得提前假结束未完成工作。之后新增真实输入时，按现有 Request/Result 机制刷新并仅重评受影响项，复用仍适用的技术结果，不因记账重跑未变业务。必要沉淀文件若属于产品交付物仍纳入 subject 及适用验证。
5. 再预检，事实齐备后由生命周期协调正式 complete，只读核对终态与接续。稳定输入复用请求/结果，不重复 Delivery/checkpoint/知识请求；CLI 不支持时报告缺口，不手改账本或伪造幂等。

## 缺陷、等待与工件
Integration 发现当前范围内真实产品 Finding 交父 Task 下的 Fix Work，父交付步骤等待结果并复验；缺权限、环境或证据则明确等待和恢复条件，不无条件派返工。实际 apply 与已获准冲突处置不等于自行改变业务语义；冲突需要新产品判断或额外修复时交相关专业角色，不能借 Delivery 修改代码、CSS、SQL 或测试扩大范围。产品源码、正式交付物、AC 实质或影响结论的证据变化会改变相关 subject；只补失效/缺失且适用的 Verification/Code Review，普通元数据不无条件触发全链重跑。

交付前检查并报告由本 Task 制造的临时 Mock、登录绕过、调试日志、一次性脚本、临时依赖和受控 Temp 状态；业务项目已获准保留的正式回归测试，以及对应项目 `.tp-spec/memory/` 中的可复用交互脚本（含基座自身）不是清理对象；其他基座临时用例按本仓策略清理。Delivery READY 遇到已登记的 `TEMP_ARTIFACT_ACTIVE` / `TEMP_ARTIFACT_CLEANUP_PENDING` 必须停止收敛；只处理 TP-Spec ownership manifest 管理的 Temp，不按文件名删除未托管内容。视觉任务若使用临时登录绕过，其清理 Evidence 必须仍然有效。

## 每 Task 知识与项目记忆
每次交付都由集成交付工程师通过 [knowledge-capture](../knowledge-capture/SKILL.md) 实际阅读本任务当前有效需求与实际步骤材料，整理候选并核对输入覆盖；knowledge_signals 是线索，无 signals 也不能跳过评估。经可信 Request 把候选交 [tp-knowledge](../../../agents/tp-knowledge/SKILL.md) 定向检索、判重/维护 canonical 及正式 Result；Integration 不检索全库、不签 DUPLICATE/NO_DURABLE_INSIGHT，不维护第二份 canonical。项目经理跟踪实际结果，不以接收回执冒充专业评估。

同时调用唯一 [tp-memory-capture](../tp-memory-capture/SKILL.md) 判断各步骤稳定 Rule/Fact/Procedure、临时与已替代内容的归位，并核对值得沉淀的问题是否需要新增/更新 AGENTS 触发入口及其可发现性。正文保存、入口保存/已覆盖/无需新增及失败分别记录，不能用 Memory 已保存代替入口核对。必做的是阅读、判断和处置，不是强制新建条目或修改所有 Memory 文件。Work 只提供紧凑结果供父 Task 汇总，不每个 Work 再跑全套收敛。

存在交互测试时，按 [Visual QA](../testing-strategy/references/visual-qa.md) 核对脚本保存/更新/已覆盖/不保留的实际处置、目标导航与回放状态；未回放不得报可稳定复用，不因交付重复运行有效测试。

复用既有交付事实记录实际输入覆盖、处置、目标链接、未保存事项/原因，不另造学习、知识、记忆、归档四套报告；同稳定输入复用有效结果，变化只重评受影响部分。未执行不得写已收敛；必要 Knowledge 环境/Request/Result 缺失保持待处理，可选 Memory 写失败按该方法披露，不虚构成功或无关阻塞。

## Runtime 接入边界
新 READY 通过现有 delivery-converge 为 L0–L3 创建或复用 `KNOWLEDGE_CONVERGENCE_REQUEST`，
带 `learning_schema=tp-spec.task-learning/v1` 与当前输入索引。先只读 `knowledge task-inputs`，
实际提炼后由 tp-knowledge 用 `task-converge --assessment FILE|-` 生成一个 Result，
包含各候选检索/目标与共享 Memory 方法的处置。详细格式按需读
[Task 收敛契约](../../../agents/tp-knowledge/references/task-convergence.md)。

再次预检可区分输入过期、结果缺失和已评估但未持久化；不能把 receipt 当成自动理解或保存成功。
只有学习输入变化且技术结果仍有效时，刷新交付请求并局部重评；不重跑无关测试。
旧 markerless Delivery 的 NOT_REQUIRED 只说明历史未记录；已终态不追补，
在途新契约通过正式 delivery-converge 接续，不写假信号或直接改事件。

## 验证与效果
修改/交付基座按 [本仓验证策略](../../../docs/TESTING.md) 核对必要局部结果和 Patch，不因提交/批次追加全量测试；业务仓库按自身留存规则。Readiness/inspection 的 effects=[]，实际 Git 写仍需 repo_mutation 与 human/Autonomy Execution Envelope。
