---
id: tp-base-maintenance
name: tp-基座维护
version: 5.2.4
status: active
type: human-owner-skill
tool_agnostic: 本技能不依赖特定 IDE；Base/Wiki/Knowledge 根必须来自 Installation/Resolver，不在 Skill 中硬编码用户绝对路径。
description: >
  基座维护工程师（tp-base-maintenance）：human_owner 专项 TP-Spec-Coding 安装与项目接入维护 Skill。负责 Base 健康、Workspace Inventory、
  项目绑定、Wiki/Knowledge 项目级 Resolver、项目入口文档、portable project override、旧 Junction
  安全收敛与批量迁移；不维护业务 Knowledge/Wiki 内容，不拥有 workflow state，不成为日常研发 Gate。
---

# tp-基座维护

## 0. 定位

本 Skill 维护的是 **TP-Spec-Coding Installation + Project Binding + Project Integration Surface**，不是业务项目内容。

权威分层：

```text
User Installation
  ├─ Base Root
  ├─ Wiki System Root
  └─ Knowledge System Root
         ↓ Registry / Project Binding
Current Workspace
  ├─ Wiki workspace/repo scope
  ├─ Knowledge project + shared scope
  └─ .tp-spec runtime/task state
```

项目侧 Junction 只属于兼容迁移面。Runtime 不得依赖 `.tp-spec/agents|skills|wiki|knowledge|scripts...` 链接才能工作。

## 1. 标准配置

用户级安装配置默认：

```text
~/.tp-spec/installation.yaml
```

由 `tp-spec base configure` 管理，保存 Base/Wiki/Knowledge **系统根**。

项目绑定默认：

```text
<workspace>/.tp-spec/config/project-binding.yaml
```

只保存项目身份（`project.id`，必要时 `wiki_id/knowledge_id`），不重复保存每个项目的绝对 Wiki/Knowledge 子目录。项目物理子目录由 registry + Resolver 计算。

Workspace Inventory 默认：

```text
~/.tp-spec/workspaces.yaml
```

用于批量 doctor/migration，不要求每次扫描磁盘。`installation.yaml` 与 `workspaces.yaml` 都是
**machine-local、可重新 configure/inventory 的薄配置**，不是 Base 产品逻辑，也不得被复制进项目 README/AGENTS。

项目可移植性边界：

- 项目 `project-binding.yaml` 只保存稳定 identity，不保存 Base/Wiki/Knowledge machine path；
- 项目 `content-systems.yaml` 只保留真正的项目级 override；与 Installation 重复的 machine roots 应移除；
- 项目根 `README.md` / `AGENTS.md` 的 TP-Spec-Coding managed block 与 `.tp-spec/README.md` 由 Base 模板确定性维护，禁止渲染 machine-local 路径。

## 2. Project Scope 不得丢失

去 Junction ≠ 全局搜索。

- Wiki：必须解析当前 workspace 的 Wiki workspace/repository root；
- Knowledge：日常默认 `project + shared`；
- Knowledge 全库检索只有显式 `--scope global` 才允许；
- 全局 Knowledge projection DB 可以包含全部项目，但默认 Query Scope 必须项目化。

## 3. 核心动作

```text
tp-spec base configure
tp-spec base installation-doctor
tp-spec base installation-migrate
tp-spec base inventory
tp-spec base resolve
tp-spec base doctor
tp-spec base migration-plan
tp-spec base sync-project
tp-spec base migrate
```

推荐多项目收敛：

```text
base inventory --write
→ base doctor --all
→ base migration-plan --all
→ human_owner 审阅
→ base migrate --all --apply --remove-legacy-links
→ base doctor --all
```

`base migrate --apply` 已包含 binding、Runtime root rebind、portable project config 与 project entry surface 同步；后续日常在项目搬迁、入口文档/项目 override 漂移时执行 `base sync-project --apply`。

Installation 生命周期：`base configure` 负责 create/update/repair（合法旧配置中未提供的 root 保持不变，损坏配置必须显式给全量 root 才能重建）；`base installation-doctor` 只读诊断；`base installation-migrate` 默认只给迁移计划，显式 `--apply` 才迁移已知 machine-local state。不得猜测新路径。

Runtime `project.root_path` 与 Runtime Registry 是 machine-local locator/cache，不是 portable identity。旧 root 不存在且 project identity/DB schema 唯一一致时，`sync-project --apply` 可确定性 rebind；旧 root 仍存在或同 project ID 存在另一 live workspace 时必须 BLOCKED。

首次 inventory 可结合 Wiki Registry、Knowledge Registry、Runtime registry；需要补发现时再显式给 `--search-root`，不得每次暴力扫描整个磁盘。

## 4. Junction 收敛安全规则

迁移必须严格按：

```text
WRITE PROJECT BINDING
→ RE-RESOLVE Base/Wiki/Knowledge
→ 比对旧链接物理 Target
→ 完全一致才可移除链接对象
```

强约束：

- 只删除 Junction/symlink **本身**，绝不删除 Target；
- 若 `.tp-spec/<name>` 是真实目录而非链接，标记 `MANUAL_REVIEW`，不得自动删；
- link target 与 Resolver target 不一致 → `BLOCKED`；
- Knowledge/Wiki project scope 未解析时，不得移除对应链接；
- 旧 Knowledge Registry 尚无 `workspace_roots` 时，可用现有 `.tp-spec/knowledge` Junction/symlink **精确匹配已注册 `10-projects/<id>`** 作为一次性 binding seed；不得按目录名猜；
- 简单 `content-systems.yaml` 只有在与用户 Installation 完全等价时才可选择删除；含项目特有 override 必须保留。

## 5. Health 结论

面向 human_owner 的语义结论仍使用：

- `HEALTHY`
- `SYNC_AVAILABLE`
- `SYNC_REQUIRED`
- `REPAIR_REQUIRED`
- `UNSAFE`

CLI 可输出 `PASS/FAIL/READY/BLOCKED` 作为确定性执行状态，两者不要混淆。

检查至少覆盖：Base VERSION/关键文件、Installation lifecycle、Project Binding、Workspace Inventory、Wiki workspace mapping、Knowledge project mapping、Runtime DB/任务状态、Runtime root portability、ACTIVE formal artifact legacy references、legacy link mismatch。若 Runtime project contract 仍是旧版本，结论必须是 `SYNC_REQUIRED`，先走官方 `project upgrade-contract`，不得只改 binding 伪装完成同步。

缺失可选 Junction 不是故障。

### Project integration surface

`tp-spec base sync-project --workspace-root <ROOT>` 默认只读计划；显式 `--apply` 后才允许：

- 新建/更新根 `AGENTS.md` 的 `tp-spec-base:managed` block；
- 新建/更新根 `README.md` 的同一 managed block，并保留项目自身内容；
- 生成/更新 Base-owned `.tp-spec/README.md`；
- 从 project-local `content-systems.yaml` 移除与当前 Installation 完全重复的 machine roots；若只剩 schema/空 override，则删除该冗余 project config；
- 含真实项目级 coverage/quality 等 override 时保留语义，只移除可证明冗余的 machine roots。

遇到 malformed managed markers、与 Installation 不一致的 absolute project override 或其他无法证明安全的 machine path 必须 `BLOCKED`，不得猜测或静默重写。

### Active task portability

Base 只检查 `.tp-spec/tasks` 中仍处于 `NEW/ACTIVE/BLOCKED` 的顶层 Markdown formal artifacts。若发现具有执行语义的旧 `.tp-spec/knowledge|wiki|scripts|agents|governance|skills|templates|automation|cli` 路径，报告 `LEGACY_ACTIVE_REFERENCE` 并要求 targeted review。明确的 legacy/禁止使用描述不作为 actionable finding。`tasksHistory`、evidence 与已完成任务不做历史清洗。

SQLite `*.db-wal` / `*.db-shm` 属于 transient runtime，不作为 portable truth，不因其存在判定 portability FAIL。

### Project bootstrap 健康边界

本 Skill 继续负责项目 Runtime 初始化健康检查，但它与 Base Binding 迁移是两件事。

- 只读预检：`tp-spec project bootstrap --id <PROJECT> --root <ROOT> --check-only`；
- 未初始化且确认 pristine 时，只有 human_owner 明确要求才执行 bootstrap；
- 非 pristine、ledger/registry 歧义或已有不兼容状态必须 fail-closed，保留 `PROJECT_BOOTSTRAP_UNSAFE`；
- 不得把“去 Junction / 写 project-binding”误当成“初始化项目 Runtime”。

## 6. 写入边界

默认 doctor/resolve/migration-plan 只读。只有 human_owner 明确要求 configure/migrate/repair 时才写。

允许：

- 写/迁移用户 Installation、Workspace Inventory 与 machine-local Runtime Registry；
- 通过 Base 官方 rebind 实现更新 Runtime DB 的 machine-local `project.root_path`，不改 Task 事实；
- 写项目 `project-binding.yaml`；
- 写 Base managed 项目入口文档；
- 对可证明冗余的 project-local Content Systems machine roots 做 portable normalization；
- 在精确比对后移除 legacy Junction/symlink；
- 调官方 Base Runtime 初始化/同步命令。

禁止：

- 修改项目业务源码；
- 修改 Knowledge canonical/source/evidence；
- 修改 Wiki 正文；
- 绕过 Base 官方命令直接手工改 Runtime SQLite；
- 为了“目录干净”删除真实 `.tp-spec` 项目状态目录。

## 7. 与其他 Skill 的边界

- Knowledge 内容/迁移/索引 → `tp-knowledge`
- Code-understanding Wiki → `tp-wiki`
- Task 生命周期 → workflow roles
- 本 Skill 只维护“这些系统怎么被当前项目可靠找到和绑定”。
