---
name: knowledge-capture
display_name: 知识提炼
version: 5.3.5
description: 每个 Task 交付时覆盖有效需求及各步骤材料，按价值形成候选，由 tp-knowledge 定向判重与维护。
---

# 知识提炼

## 责任与触发
每个 Task（L0–L3）交付由集成交付工程师调用，即使没有 knowledge_signals；日常也可在自然出现高价值内容时使用。本能力提炼候选，不创建公共 Knowledge 阶段、不代签技术或人工验收。必做的是评估，不是强制新增 canonical/报告。

## 有效输入覆盖
先只读 `knowledge task-inputs` 获取当前请求、输入 digest、逐项指纹/引用与增量，再从当前 Task 的 canonical 需求、计划/索引和正式事件定位有效材料，定向读取需求、决定、设计/实现、测试/审查、返修 Work、交付及各步骤记忆候选；不能只读最后摘要或检查 signals。记录已读来源/范围与缺失，未发生步骤不补造；已替代决定保留关联，不作为当前新规则。不为完整扫描全库或其他 Task 历史。

每个 Work 提供紧凑结果/来源，由父 Task 汇总，不为每个 Work 再启动完整知识链。同稳定有效输入复用有效判断/Request/Result，相关版本变化只重评受影响内容，不能沿用过期结果。

## 提炼与去重责任
1. 提取有证据的业务规则、架构/接口/数据事实、决策理由、根因、风险或操作/验证经验；标来源、适用条件、失效条件及当前确认程度。
2. 不稳定、证据不足、临时 workaround、聊天流水、普通常识和无复用价值内容不升级为长期知识；说明实际处置依据而非用空信号默认跳过。
3. 核对合法 knowledge_target/project/kind；缺目标不跳过评估，保留候选与待解析目标，不能编造 canonical 地址。与已有知识冲突时标冲突和证据，不静默覆盖。
4. 通过可信 KNOWLEDGE_CONVERGENCE_REQUEST 将来源/候选交 [tp-knowledge](../../../agents/tp-knowledge/SKILL.md) 做 current project + registered shared 的定向检索/判重与维护。CREATED/UPDATED 绑定 exact canonical，DUPLICATE 有命中，NO_DURABLE_INSIGHT 也有真实检索和理由。
5. **不得直接写 Knowledge Vault 的 canonical/90-sources 或最终 Knowledge Result**；source registry、index、L1–L4 知识验证和 baseline 由 tp-knowledge 负责，不与 L0–L3 工程等级混用。无可信 Request 不伪造 Result，缺正式登记能力如实待处理，不把 NOT_REQUIRED 当成本次已提炼。
6. 各步骤 Rule/Fact/Procedure、临时与已替代决定交 [项目记忆捕获](../tp-memory-capture/SKILL.md) 归位。稳定重复方法可成为公共 Skill/Review 检查项候选，但新方法不因一次成功转 active，持久测试仍依项目规则及授权。

## 回执

新 Request 使用 `tp-spec.task-learning/v1`；将实际逐项 coverage、分组候选和 Memory 处置交给 tp-knowledge，
通过 `knowledge task-converge --assessment FILE|-` 写入既有 Result。格式与受指纹约束的局部复用见
[Task 收敛契约](../../../agents/tp-knowledge/references/task-convergence.md)。输入清单本身不证明已读，
不得从 digest 自动填造“无价值”判断；缺项先解决，不靠空 queries 或假目标消除阻塞。
在既有交付事实内记录输入覆盖、实际判断、目标链接与未保存原因，Knowledge 最终检索/处置引用可信 Result；不另建 quality-and-knowledge.md 或学习/记忆/归档四套报告。必要环境/Request/Result 缺失保持待处理，未执行不可称已收敛；可选 Memory 落盘失败按其自身边界披露，不混同“已判断”和“已保存”。
