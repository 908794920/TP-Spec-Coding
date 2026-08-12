# TP-Spec-Coding Agent / Skill 入口（v5.2.0）

角色 ID 是 Runtime 账本中的稳定身份；物理目录只是加载位置。`agents/role-catalog.yaml` 是唯一 role → Skill path 权威，目录迁移不得重写历史 `task.owner_role` / `task_event.actor_role`。

## 对外 Agent

```text
agents/tp-workflow-orchestrator/SKILL.md  # 研发流程唯一默认入口（开发组长）
agents/tp-base-maintenance/SKILL.md       # 基座安装、迁移、路径与项目接入
agents/tp-knowledge/SKILL.md              # 长期 Knowledge
agents/tp-wiki/SKILL.md                   # Code Wiki
```

## 研发流程内部专业 Skill

由 `tp-workflow-orchestrator` 按需调度，不作为 7 个并列开发入口暴露：

```text
skills/tp-requirement-analysis/SKILL.md
skills/tp-product-design/SKILL.md
skills/tp-architecture-design/SKILL.md
skills/tp-architecture-review/SKILL.md
skills/tp-development-engineering/SKILL.md
skills/tp-verification-engineering/SKILL.md
skills/tp-delivery-convergence/SKILL.md
```

## 账本原则

- Orchestrator 只决定“下一步找谁”，不抢专业角色事实归属；
- requirement / architecture / development / verification 等事实仍以真正执行角色写 `owner_role` / `actor_role`；
- 普通只读路由不额外制造 Runtime event；
- Skill 移目录不改变 role ID，因此历史 Task / DB 不因目录调整而改写角色字段。

## 扩展原则

- `agents/`：用户可以直接选择的专业入口；
- `skills/`：Agent 内部可组合能力；
- 使用者可以增加需求写作、文档、视频、数据分析等 Agent；
- 是否成为 Runtime actor 必须由职责决定，不能因为目录在 `agents/` 就自动取得记账权；
- 不要求安装到某个 IDE 的全局 skills 目录，不把编辑器绝对路径作为权威来源。
