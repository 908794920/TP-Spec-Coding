---
id: tp-base-maintenance
name: tp-基座维护
version: 5.3.2
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

### 项目级生成物放置规则

与当前项目绑定、由 TP-Spec-Coding 生成、非产品源码且无需独立外部存储的本地产物，默认收敛到 `<workspace>/.tp-spec/<feature>/`，不得为单一功能在项目根新增 `.tp-spec-*`、`.xxx-preview`、`.tmp` 等兄弟隐藏目录。当前固定卡片 Web Artifact 为 `.tp-spec/card/index.html`。

`.tp-spec/card` 仅属于 **presentation-only / rebuildable / non-authoritative** 展示产物：删除后仅在用户显式请求卡片时由正式 `tp-spec card ...` 重建，不写 Runtime/Task truth，不成为任务账本或产品内容。高频、短生命周期 execution scratch（测试工作区、ZIP 解压、中间渲染等）继续使用受 ownership 管理的 **system Temp**，不得为了目录统一迁回 `.tp-spec`。用户级/机器级状态继续使用 `~/.tp-spec/`。

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

默认只操作明确指定的单项目；只有获准批量对象清单和对应副作用时，才使用以下多项目收敛方式：

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

项目侧 Junction/symlink 只属于兼容迁移面。只有新 Project Binding 可解析，且旧链接物理 Target 与 Resolver target **精确一致**时，才允许移除链接对象；只删除链接本身，绝不删除 Target。真实目录、target mismatch、scope 未解析或归属无法证明时必须 fail-closed，不得为了目录整洁猜测处理。详细迁移分支按下方 Context Pointer 读取。

## 5. Health 结论

面向 human_owner 的语义结论仍使用：

- `HEALTHY`
- `SYNC_AVAILABLE`
- `SYNC_REQUIRED`
- `REPAIR_REQUIRED`
- `UNSAFE`

CLI 可输出 `PASS/FAIL/READY/BLOCKED` 作为确定性执行状态，两者不要混淆。

检查至少覆盖：Base VERSION/关键文件、Installation lifecycle、Project Binding、Workspace Inventory、Wiki workspace mapping、Knowledge project mapping、Runtime DB/任务状态、Runtime root portability、ACTIVE formal artifact legacy references、legacy link mismatch。若 Runtime project contract 仍是旧版本，结论必须是 `SYNC_REQUIRED`，先走官方 `project upgrade-contract`，不得只改 binding 伪装完成同步。Project 切换不迁移 Task；需先检查计划并取得具体对象/备份授权，不把升级 Base 或同步模板当成迁移授权。

缺失可选 Junction 不是故障。



## 6. 按需 Context Pointers

- 读取条件：兼容升级、配置来源或旧 Task 契约不匹配；内容：只读计划、有限迁移政策、备份、提交/缓存失败与恢复边界；路径：[兼容与迁移操作](../../docs/agents/tp-base-maintenance.md#兼容更新与显式契约迁移)

- 读取条件：执行 legacy Junction/symlink 迁移或移除；内容：迁移顺序阻塞条件一次性binding seed与link删除边界；路径：[Junction 迁移](references/junction-migration.md)
- 读取条件：执行 base sync-project 或检查 active task portability；内容：项目入口surfaceportable override与active formal artifact规则；路径：[项目接入与可移植性](references/project-integration.md)
- 读取条件：检查或执行项目 Runtime bootstrap；内容：pristine判定授权条件与bootstrap fail-closed边界；路径：[Project bootstrap](references/project-bootstrap.md)

## 7. 写入边界

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

## 8. 与其他 Skill 的边界

- Knowledge 内容/迁移/索引 → `tp-knowledge`
- Code-understanding Wiki → `tp-wiki`
- Task 生命周期 → workflow roles
- 本 Skill 只维护“这些系统怎么被当前项目可靠找到和绑定”。
