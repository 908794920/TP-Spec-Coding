# TP-Spec-Coding Getting Started

这份文档面向第一次拿到 TP-Spec-Coding 的使用者，重点解决三个问题：

1. 一台**全新机器**怎么从**空配置**开始；
2. 怎么把已有项目交给 AI 接入；
3. 换电脑或移动项目以后怎么恢复，而不是重新配置一遍所有历史事实。

> TP-Spec-Coding 的公共仓库不携带任何作者机器路径、项目注册、Runtime DB、Wiki 或 Knowledge 用户数据。机器信息只在你自己的 `~/.tp-spec/` 下生成。

## 1. 准备环境

需要：

- Git
- Python 3.10+
- Windows 推荐 PowerShell 7

进入 TP-Spec-Coding 根目录：

```bash
python -m pip install -r requirements.txt
python -m cli.main --help
```

如果第二条命令能打印 CLI 帮助，Base 源码本身可以运行。

## 2. 理解“空配置”

仓库里的：

```text
config/installation.example.yaml
config/workspaces.example.yaml
db/registry.local.json.example
```

只描述数据结构，默认值全部为空。

真正运行时使用的是当前用户自己的机器状态：

```text
~/.tp-spec/installation.yaml
~/.tp-spec/workspaces.yaml
~/.tp-spec/registry.local.json
```

Windows 的 `~` 代表当前用户 Home，Linux/macOS 同理。

不要把这三个机器文件复制进 TP-Spec-Coding Git 仓库，也不要复制到业务项目里当“通用配置”。

## 3. 第一次配置 Base / Wiki / Knowledge

你需要决定三个位置：

```text
Base Root       = TP-Spec-Coding 仓库根目录
Wiki Root       = 你希望保存代码理解 Wiki 的系统根
Knowledge Root  = 你希望保存长期 Knowledge 的系统根
```

Wiki Root 和 Knowledge Root 必须是已经存在的目录。你可以让 AI 先创建目录，但 AI 不应该擅自选择你的磁盘或同步盘。

配置：

```bash
python -m cli.main base configure \
  --base-root "<TP-Spec-Coding-root>" \
  --wiki-root "<wiki-system-root>" \
  --knowledge-root "<knowledge-system-root>"
```

检查：

```bash
python -m cli.main base installation-doctor
```

健康状态为 `HEALTHY` 时，机器级安装配置完成。

### Windows 包装器

在 Base 根目录也可以：

```powershell
pwsh -File scripts/tp-spec.ps1 base installation-doctor
```

包装器解析 Base 的优先级包括 `TP_SPEC_BASE_ROOT`、用户 installation 配置和当前脚本真实位置，用于避免把 Base 绝对路径写进业务项目。

## 4. 让 AI 帮你完成第一次配置

如果你不熟悉这些概念，直接把下面提示词交给能够访问本机文件系统的 AI：

```text
请帮我把 TP-Spec-Coding 配置到这台机器。

要求：
- 先阅读 TP-Spec-Coding/README.md 和 docs/GETTING_STARTED.md；
- 不允许猜机器路径；
- 不允许把机器绝对路径写进业务项目的 README/AGENTS/源码；
- 先确认 Base Root；
- 再让我选择 Wiki System Root 与 Knowledge System Root；
- 使用 `base configure` 写用户级 installation.yaml；
- 使用 `base installation-doctor` 验证；
- 任何路径不存在、重复 project id、多个候选 workspace 都必须先告诉我，不得自动猜。

最后列出：
1. 使用的 Base/Wiki/Knowledge Root；
2. 写入的用户级配置文件；
3. doctor 结果；
4. 仍需要我决定的事项。
```

## 5. 接入第一个业务项目

假设项目根是 `<project-root>`，先给项目一个稳定 ID：

```bash
python -m cli.main project init \
  --id <project-id> \
  --root "<project-root>"
```

`project init` 会创建项目 Runtime，并写入 `.tp-spec/config/project-binding.yaml` 作为稳定 portable identity；如果该目录已经绑定到另一个 project id，会直接拒绝，避免覆盖错项目。

然后同步 portable project entry：

```bash
python -m cli.main base sync-project \
  --workspace-root "<project-root>" \
  --apply
```

这一步会维护项目 binding 和 managed entry。项目文件只记录 portable identity，不重复记录 Wiki / Knowledge 的机器绝对路径。

检查解析结果：

```bash
python -m cli.main base resolve --workspace-root "<project-root>"
```

## 6. 开始一个研发任务

默认产品入口：

```text
tp-spec-coding
```

它只做低上下文 Domain routing、Status / Continue / Explain；软件研发意图交给：

```text
tp-software-lifecycle
```

软件生命周期再根据 L0～L3、风险和当前事实选择正式工程角色，不要求每个 Task 跑完所有角色。

把下面提示词交给 AI：

```text
请使用 TP-Spec-Coding 处理这个任务。
先通过 TP_SPEC_BASE_ROOT 或 ~/.tp-spec/installation.yaml 定位 Base，
读取 agents/tp-spec-coding/SKILL.md，
再读取当前项目 managed entry 和已有 .tp-spec Task/Runtime 事实。
如果属于软件研发，让 tp-software-lifecycle 继续调度；
不要跳过已有历史，也不要让入口 Agent 代替专业角色做需求、架构、开发、测试或 Review。
```

如果已有正式 Task，可以先查看只读路由：

```bash
python -m cli.main workflow next \
  --task <TASK-ID> \
  --db <DB-PATH> \
  --json
```

如果输入只是客户一句话或一份需求文档，Product Manager 可以先在 pre-task 阶段完成产品/需求规范化；达到 Requirement Ready 后才创建正式 Task。

## 7. 当前软件工程角色

`tp-software-lifecycle` 按需使用以下正式 Role：

```text
tp-product-manager         产品/需求规划、分析、拆解与验收
tp-software-architect      系统设计、技术选型、接口与架构
tp-tech-lead               技术规划、规范、任务拆解与技术把关
tp-security-engineer       安全设计、审计、扫描与验证
tp-development-engineer    代码实现、调试、重构与性能
tp-database-engineer       数据模型、SQL、DDL、迁移与数据库质量
tp-test-engineer           单元、集成、接口、回归与验收测试
tp-code-reviewer           独立 Diff / Code Review
tp-integration-engineer    变更检查、集成、Git 与交付收敛
```

Role 与 phase 正交，同一 phase 可以按风险调用多个 Role；L0/L1 的简单任务仍保持轻量，不会为了角色完整强制走全流程。

其他 Domain Agent：

```text
tp-base-maintenance
tp-knowledge
tp-wiki
tp-project-autonomy
```

它们与软件生命周期职责分离；未来其他领域也应拥有自己的 Domain Agent + Role/Skill Pool。

## 8. 新电脑怎么迁

### 应该带走什么

根据你的存储策略复制或重新 clone：

- TP-Spec-Coding 源码；
- 业务项目源码以及项目自己的 `.tp-spec`；
- Wiki / Knowledge 数据（如果你需要沿用）；

### 不要直接复制什么

不要把旧机器的以下文件当成 portable truth：

```text
~/.tp-spec/installation.yaml
~/.tp-spec/workspaces.yaml
~/.tp-spec/registry.local.json
```

它们保存的是旧机器 locator。

### 新机器恢复步骤

1. clone / checkout TP-Spec-Coding；
2. 安装 requirements；
3. 创建或恢复 Wiki / Knowledge 存储目录；
4. 执行 `base configure`；
5. 执行 `base installation-doctor`；
6. 对每个业务项目执行 `base sync-project --workspace-root <project-root> --apply`；
7. 执行 `base resolve` 核对 scope；
8. 再让 `tp-software-lifecycle` 继续已有 Task。

如果项目从旧路径移动到了新路径，TP-Spec-Coding 可以安全重绑 Runtime locator；如果旧路径仍存在，或者发现同一 project id 的多个活跃 workspace，则会 BLOCKED，要求用户决定，防止绑定错项目。

## 9. Workspace Inventory

管理多个项目时，可以让 TP-Spec-Coding 生成当前机器 Inventory：

```bash
python -m cli.main base inventory \
  --search-root "<projects-root>" \
  --write
```

之后可通过支持 `--all` 的 Base 命令批量检查。

Inventory 是机器状态，不属于项目事实，不应提交到公共 Base 仓库。

## 10. 为什么历史账本不跟目录一起改

TP-Spec-Coding 把“角色身份”和“Skill 文件路径”分开：

```text
role id                 = 持久化身份
skills/.../SKILL.md     = 当前实现位置
```

因此专业 Skill 移目录不会重写历史：

```text
task.owner_role
task_event.actor_role
```

Orchestrator 只是调度，真实 requirement / architecture / development / verification 事实仍属于对应专业角色。

## 11. Git 中应该提交什么

业务项目是否提交 `.tp-spec` 由你的项目策略决定；如果它作为研发事实历史跟项目走，就应明确纳入版本管理策略。

TP-Spec-Coding 公共仓库本身不应提交：

- `db/registry.local.json`；
- Runtime `*.db` / `*.db-wal` / `*.db-shm`；
- `~/.tp-spec/*`；
- 用户 Wiki / Knowledge 数据；
- 本机绝对路径；
- 测试缓存和临时产物。

## 12. 健康检查与排错顺序

### Base 找不到

检查：

```text
TP_SPEC_BASE_ROOT
~/.tp-spec/installation.yaml
```

然后：

```bash
python "<TP-Spec-Coding-root>/cli/main.py" base installation-doctor
```

### 项目 scope 不确定

```bash
python -m cli.main base resolve --workspace-root "<project-root>"
```

不要按目录名猜 Wiki / Knowledge 项目。

### 项目搬迁后绑定异常

先只读：

```bash
python -m cli.main base doctor --workspace-root "<project-root>"
python -m cli.main base migration-plan --workspace-root "<project-root>"
```

确认身份后再：

```bash
python -m cli.main base sync-project --workspace-root "<project-root>" --apply
```

### 编排异常

```bash
python -m cli.main workflow doctor --json
```

Orchestrator 故障时可以按 `agents/role-catalog.yaml` 手工加载对应内部专业 Skill，但不要重新创建一套并列开发流程或第二状态机。

## 13. 兼容命名说明

正式项目名是 **TP-Spec-Coding**，但以下技术 namespace 为兼容历史 Task / DB 保持不变：

```text
tp-spec CLI
.tp-spec/
~/.tp-spec/
tp-spec.* schema
TP_SPEC_BASE_ROOT
```

这属于稳定接口，而不是旧品牌残留。
