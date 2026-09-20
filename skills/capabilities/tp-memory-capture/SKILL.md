---
name: tp-memory-capture
display_name: 项目记忆捕获
version: 5.3.3
description: 内部按需沉淀能力；工作自然出现已确认稳定 Rule 或高价值经验时加载，区分根 AGENTS 自有规则、Task 临时事实与可选 Fact/Procedure，不扫描历史。
---

# tp-memory-capture

## 定位与触发
这是工作角色按需调用的**内部薄能力**，不对用户暴露，不进入 Workflow，不写 Runtime event/state，不主动扫描任务寻找经验。用户明确要求长期遵守的规则，或当前工作自然得到的已确认稳定约束，可以触发 Rule 归位；可选经验另过下方 Gate。任务很长、一次成功/失败或普通常识不构成沉淀理由。

## 落点先于记忆
- **Rule** → 对应业务项目根目录 `AGENTS.md` 自有区（Base 托管标记以外）；不是用户全局文件、TP-Spec 公共模板或另一项目。规则简短、来源明确，说明适用条件与不适用范围；只放不可遗漏的不变量，方法用短指针关联，不整体搬迁 Memory。
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
3. 写目标后读回，**确认目标已正确保存后**，才将源 PROJECT 重复规则换成必要引用或删除重复条目。保留非重复方法和证据，失败保留原规则；不维护两份规范，不建双向同步。
4. INDEX 只保留短触发/位置/status；已知目标直接读 Skill 或片段，目标未知且确需经验才查 INDEX。无关或缺失的可选 Memory 不读、不补全盘搜索，也不预加载 PROJECT、全部 Skills 或 Task 历史。
5. 一批相关内容合并必要小 patch，复用该批摘要，不逐条另建报告、事件或学习任务。未获准不得自动删除 `PROJECT.md`、迁入 `.agents/skills` 或批量整理其他项目；create-once 模板更新不改既有项目 Memory。

## Procedure 的验证边界
方法与**历史验收规模**分开：流程数、样本量、轮次及性能阈值只在当前获准范围需要时采用，命中 Skill 不构成编译、浏览器、部署、发布或全量回归授权。按实际 AC/Diff/调用方与风险选检查，不因轻量化忽略安全影响。获准持久回归脚本/夹具/基线是版本化资产，不按临时诊断清理；原有测试和临时产物 ownership 保护不变。

## 失败与回执
可选 INDEX/Memory/候选经验缺失、损坏或写入失败可 SKIP，**不得阻塞研发**；根 AGENTS 的重要 Rule 保存失败必须说明“未持久化”，保留原规则和来源。当前会话已明确的约束仍遵守，仅约束/权限无法可靠判断时停止受影响动作，不扩大成所有工作阻塞。回执区分已保存、未持久化和跳过；规则写入、宿主发现、Agent 实际遵守是不同结论，未实测不保证自动加载。
