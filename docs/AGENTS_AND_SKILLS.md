# TP-Spec-Coding Agent / Role / Skill 入口（v5.2.4）

`agents/role-catalog.yaml` 是 active Domain Agent / Formal Role → Skill path 的单一权威。历史 previous-contract Action Role 只用于 migration/history，不能参与 active routing。

## L1 产品入口

```text
agents/tp-spec-coding/SKILL.md
```

默认用户只需要这个入口。它只做 signal-driven / low-context Domain routing、Status/Continue/Explain，不做第二次需求分析或第二套 workflow orchestration。

## L2 Domain Agent

```text
agents/tp-software-lifecycle/SKILL.md  # 软件工程生命周期
agents/tp-base-maintenance/SKILL.md    # Base / installation / migration
agents/tp-knowledge/SKILL.md           # 长期 Knowledge
agents/tp-wiki/SKILL.md                # Code Wiki / Project Truth
agents/tp-project-autonomy/SKILL.md    # 项目自治
```

## Software Formal Role Pool

```text
skills/tp-product-manager/SKILL.md
skills/tp-software-architect/SKILL.md
skills/tp-tech-lead/SKILL.md
skills/tp-security-engineer/SKILL.md
skills/tp-development-engineer/SKILL.md
skills/tp-database-engineer/SKILL.md
skills/tp-test-engineer/SKILL.md
skills/tp-code-reviewer/SKILL.md
skills/tp-integration-engineer/SKILL.md
```

Role 与 phase 正交：一个 phase 可以需要 0..N 个 Role；同一 Role 也可以跨 phase 参与。L0～L3 只决定实际需要的生命周期深度，不要求每个 Task 跑完所有 Role。

## 内部共享辅助 Skill

例如：

```text
skills/requirement-clarification/SKILL.md
skills/assumption-management/SKILL.md
skills/delivery-planning/SKILL.md
skills/task-decomposition/SKILL.md
skills/implementation-control/SKILL.md
skills/systematic-debugging/SKILL.md
skills/testing-strategy/SKILL.md
skills/technical-review/SKILL.md
skills/tp-memory-capture/SKILL.md
```

共享 Skill 是能力，不默认成为 Runtime owner，也不要求每次调用都记账。Role 只 lazy-load 当前任务真正需要的能力。

## 账本原则

- 用户体验默认不暴露 Role ID / Skill path / event id；
- Runtime 只记录真正需要追溯的 formal responsibility 与可信 event/evidence；
- phase 是事实，不是状态门禁；
- Sub-Skill invocation 不默认写 ledger；
- AI 不直接维护 SQLite/status/events；使用 Record-first CLI；
- pure governance incremental overhead 目标 <=5%。

## 扩展原则

未来视频生成等完全不同体系应增加独立 Domain Agent + 自己的 Role/Skill Pool；共享 Runtime，不共享软件生命周期。
