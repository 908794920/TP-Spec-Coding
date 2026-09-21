---
name: tp-memory-capture
display_name: 项目记忆捕获
version: 5.3.4
description: 日常按需、每 Task 交付必评估的共享归位方法；区分短规则、详细规则/方法、事实线索与临时内容，不扫描其他任务。
---

# tp-memory-capture

## 定位与触发
这是所有角色共享的一份内部方法：日常按需，每个 Task 交付由集成交付工程师基于有效需求与各步骤材料必做一次评估。不新增 Workflow 阶段或独立 event/state，处置嵌入既有 Knowledge Convergence Result，由集成交付工程师核对；不扫描其他任务找经验。必评估不等于必新增条目，同稳定输入复用已有判断，输入变化只处理受影响部分。用户明确要求长期遵守的规则，或当前工作自然得到的已确认稳定约束，可以触发 Rule 归位；可选经验另过下方 Gate。任务很长、一次成功/失败或普通常识不构成沉淀理由。

## 落点先于记忆
- **Rule** → 每会话不可遗漏的稳定授权/范围不变量放对应项目根 `AGENTS.md` 自有区的短句与触发指针；详细长期规则归项目 Memory 的相关规则段（如 `PROJECT.md#rules`），可复用方法归项目 Skill。来源、范围、条件和写入授权必须保留，不写用户全局文件、公共模板或另一项目，不把全部规则搬入 AGENTS。
- **Task** → 当前 canonical Task/Requirement：临时基线、进度、等待、本次验收与授权决定。必要例外须有有效来源及授权，不把临时决定升级为永久规则。
- **Fact** → `.tp-spec/memory/PROJECT.md` 命中段：有来源的可复用线索，相关时核实；完整长期知识仍归 Knowledge，Memory 不是真源。
- **Procedure** → 既有 `.tp-spec/memory/skills/<id>/SKILL.md`：`UPDATE existing > CREATE new`，只保留 `When / Steps / Verify` 与资产/证据指针，不复制脚本。新建默认 `status: candidate`；换位置、一次成功或模型推测不自动升级候选为 active。
- 当前机器路径、端口、PID、会话信息 → 既有本机配置/Resolver/获准运行上下文，不进共享规则。密码、Token、密钥、Cookie、认证状态及敏感业务资料不得写入 AGENTS／Memory／Skill。

## Gate — No Evidence, No Memory
Rule 需要明确来源、稳定适用范围及写入授权，**不受重发现成本限制**；用户已经明确的长期决定不重复提问。Fact/Procedure 才需同时满足：
1. **Evidence-backed**：有用户确认、当前代码/配置、真实执行或正式证据；模型猜测不是依据。
2. **Non-volatile**：不是临时状态或当前机器信息。
3. **Reusable**：对本项目未来同类工作有实际价值。
4. **Costly to rediscover**：不是少量读取/探测即可低成本重建。

可选经验任一不满足即 SKIP。口径冲突、来源不足或范围不明时定向查证，不能按最新文本选最方便解释、将 candidate 升格或静默扩大授权；业务取舍才交用户决定。

## 最小 patch 与去重
1. 先核对实际业务根、当前文件与用户新增内容；精确使用 `AGENTS.md`，不创建大小写并存副本或默认新增模块级 AGENTS。只读相关段及来源，保护托管标记；标记损坏、文件名冲突或归属不明时不猜测覆盖。
2. **patch > rewrite**：等价规则合并到已有分节；冲突未经核实不作为重复删除。通用接入只改 Base 的托管模板，项目经验只改自有区；同步工具不替用户整理项目规则。
3. 写目标后读回，**确认目标已正确保存后**，才精简源 AGENTS/PROJECT 的重复正文为短规则/触发引用或删除重复条目。迁往 Memory/Skill 的详细规则先读回确认，关键授权/范围不变量仍留根 AGENTS。保留非重复方法和证据，失败保留原规则；不维护两份规范，不建双向同步。
4. INDEX 只保留短触发/位置/status；已知目标直接读 Skill 或片段，目标未知且确需经验才查 INDEX。无关或缺失的可选 Memory 不读、不补全盘搜索，也不预加载 PROJECT、全部 Skills 或 Task 历史。
5. 一批相关内容合并必要小 patch，复用该批摘要，不逐条另建报告、事件或学习任务。未获准不得自动删除 `PROJECT.md`、迁入 `.agents/skills` 或批量整理其他项目；create-once 模板更新不改既有项目 Memory。

交互测试脚本是 Procedure 的可执行资产，按 [Visual QA](../testing-strategy/references/visual-qa.md) 保存到对应项目 Memory 的交互测试目录；上面的“不复制脚本”指方法正文仅链接单一脚本源，不禁止该目录承载脚本。已有项目测试原位引用，不批量搬迁；实际回放通过与方法 candidate/active 分开记录，一次成功不自动升格。

## Procedure 的验证边界
方法与**历史验收规模**分开：流程数、样本量、轮次及性能阈值只在当前获准范围需要时采用，命中 Skill 不构成编译、浏览器、部署、发布或全量回归授权。按实际 AC/Diff/调用方与风险选检查，不因轻量化忽略安全影响。获准持久回归脚本/夹具/基线是版本化资产，不按临时诊断清理；原有测试和临时产物 ownership 保护不变。

## 交付时的逐项处置
基于本 Task 有效需求、各步骤候选及必要来源逐项判断 Rule/Fact/Procedure/临时/已替代内容；已有等价目标优先更新或引用，冲突先核实，临时进度/验收/授权不永久化。没有可沉淀项也需真实阅读后的理由，不以“未触碰 Memory：0 动作”跳过交付评估。不强制新文件、全索引搜索或每个 Work 单独完整收敛。

只读案例验证：定时开关有既有项目 Skill 则直接导航；通知变量、JDK/Maven/POI、Eclipse/Tomcat 日志和发布步骤按稳定性/价值归 Fact 或 Procedure；机器 JDK 路径留配置/Resolver。分支及授权不变量保留根短句，旧 compile/发布说明不覆盖用户当前构建/执行授权。本例不是修改 IDC 原件或运行这些命令的授权。

## 失败与回执

正式 Task Result 的 `memory` 输入必须有实际评估摘要和逐项处置；无候选也需理由。
`SAVED/COVERED` 提供项目相对目标、片段、范围和来源，由命令读回；命令不代写、不证明人工身份。
`NOT_PERSISTED` 与保存目标变化单独披露，不把保存失败伪装成评估未执行。具体字段与
指纹约束的旧 Memory 单项复用按需读 [Task 收敛契约](../../../agents/tp-knowledge/references/task-convergence.md)。
可选 INDEX/Memory/候选经验缺失、损坏或写入失败可 SKIP，**不得阻塞研发**；根 AGENTS 的重要 Rule 保存失败必须说明“未持久化”，保留原规则和来源。当前会话已明确的约束仍遵守，仅约束/权限无法可靠判断时停止受影响动作，不扩大成所有工作阻塞。回执区分已评估、已保存、未持久化和有理由跳过；必要知识环境/Result 缺失不能用可选 Memory 的跳过规则消解。重要规则未保存写清责任和恢复条件。规则写入、宿主发现、Agent 实际遵守是不同结论，未实测不保证自动加载。
