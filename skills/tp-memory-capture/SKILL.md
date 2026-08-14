---
name: tp-memory-capture
version: 5.2.1
description: 内部机会式项目记忆能力；仅在当前角色自然发现高价值、已证实、跨会话可复用且重新发现成本高的项目经验时按需加载，做最小 Memory patch。
---

# tp-memory-capture

## 定位
这是 7 个研发角色可按需调用的**内部薄能力**，不对用户暴露，不进入 Workflow，不写 Runtime event/state，也不主动扫描任务寻找经验。Memory 只是效率增强；缺失、损坏、冲突或写入失败都必须 SKIP，不得阻塞研发。

## Trigger
只在当前工作已经自然出现以下信号时考虑写入：
- human_owner 明确强调“以后记住 / 不要再犯 / 每次都这样”等未来重要性；
- 真实调试/验证揭示了非显而易见、重复成本高的项目固定约束；
- 已验证的方法能明显减少以后同类任务的探索或返工。

不要因为任务很长、AI 某次成功、普通通用常识或一次性结果而记忆。

## Gate — No Evidence, No Memory
写入前同时满足：
1. **Evidence-backed**：来自用户明确确认、真实代码、成功命令、测试/Verification evidence 或已确认需求/架构事实；模型猜测不算。
2. **Non-volatile**：不是时间戳、PID、临时 Session、个人机器绝对路径等易变状态。
3. **Reusable**：跨会话仍可能帮助当前项目的同类工作。
4. **Costly to rediscover**：不是几次 file read / 简单探测即可低成本重建。

任一不满足即 SKIP。密码、Token、密钥、生产敏感信息永不写入 Git Memory。

## 最小动作
- **Fact** → patch `.tp-spec/memory/PROJECT.md` 对应 Runtime / Structure / Constraints / Verification / Navigation；完整知识仍归 Knowledge。
- **Procedure** → `UPDATE existing > CREATE new`；优先补已有 Skill。确需新建时使用 `.tp-spec/memory/skills/<id>/SKILL.md`，默认 `status: candidate`，正文只保留 `When / Steps / Verify`。
- **INDEX** → 只 patch 最短 anchor / `skill-id — when — status` 指针，不复制正文。

始终遵守 **patch > rewrite**；同一 Task 的多个弱信号尽量合并成一次小改动。失败本身不写，除非已经找到并验证了可复用的预防规则。
