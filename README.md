# TP-Spec-Coding

> **一个入口，按正式软件工程角色组织 AI，把一个人的工程能力扩展成一支轻量 AI 项目组（面向一人项目组）。**

TP-Spec-Coding 是一个**本地优先、可追溯、可迁移、可扩展**的个人 AI 软件工程系统。用户默认只需要进入 `tp-spec-coding`；系统以低上下文成本识别意图，并把软件工作交给 `tp-software-lifecycle`，再根据 L0～L3、风险与当前事实按需选择正式工程角色。

当前版本：**v5.2.5** · License：**MIT**

## 为什么做这个项目

直接让 AI 写代码很快，但当一个人同时承担产品、架构、技术规划、安全、开发、数据库、测试、代码 Review 和集成交付时，单纯“需求 → 代码”已经不够。TP-Spec-Coding 的目标不是让每个任务走更重流程，而是把这些正式职责组织成可按需调用的能力池，同时让简单任务继续保持轻量。

典型问题：

- 客户只给一句话或一份文档，需要先变成可开发、可验收的 Requirement；
- 产品/架构/技术决策散在不同 AI 会话里，Task 开始后很难继续复用；
- 测试、Review、安全检查容易混成一个“大验证步骤”；
- “测试通过”“已经集成”缺少稳定 subject 与真实 evidence；
- 大任务需要深度规划，小任务又不能被完整流程拖慢；
- Wiki、Knowledge、Project Memory 要长期积累，但不能反过来成为交付收费站。

## 产品模型

```text
User
  ↓
tp-spec-coding                  # 唯一默认产品入口
  ↓
Domain Agent
  ├─ tp-software-lifecycle      # 软件工程生命周期
  ├─ tp-wiki                    # Code Wiki / Project Truth
  ├─ tp-knowledge               # 长期 Knowledge
  ├─ tp-base-maintenance        # 基座安装/迁移
  └─ tp-project-autonomy        # 项目自治维护

software intent
  ↓
Formal Engineering Role Pool
  ├─ tp-product-manager
  ├─ tp-software-architect
  ├─ tp-tech-lead
  ├─ tp-security-engineer
  ├─ tp-development-engineer
  ├─ tp-database-engineer
  ├─ tp-test-engineer
  ├─ tp-code-reviewer
  └─ tp-integration-engineer
```

## 核心原则

- **Role-first**：按“正式角色负责什么”组织能力，而不是让“需求分析/开发/验证”等动作冒充永久角色。
- **能力完整、执行按需**：L0～L3 裁剪 phase，Role Resolver 裁剪角色，每个 Role 再 lazy-load 必要 Skill。
- **Requirement Ready 后再建 Task**：pre-task 产品/需求工作合法；成熟需求可以快速进入 Task，明确 Bug 可直接 L0。
- **Record-first / CLI-first**：AI 做真实工程工作；CLI/Runtime 自动记录少量必要事实，纯治理增量成本目标不超过 5%。
- **五态不变**：`NEW / ACTIVE / BLOCKED / COMPLETED / CANCELLED`；phase 只是查询/审计事实，不是收费站。
- **安全边界正交于角色**：`mode` / `effects` / Execution Envelope 不因角色化重构而削弱。

## 正式软件工程角色

| Role | 责任 |
|---|---|
| Product Manager | 产品规划、原始需求理解、需求分析/拆解、范围、验收、必要产品设计 |
| Software Architect | 系统设计、技术选型、接口/模块/兼容/可靠性、UltraPlan、隔离架构评审 |
| Tech Lead | 技术规划、代码规范、任务拆解、依赖与实施约束 |
| Security Engineer | 安全设计、审计、扫描、认证/授权、敏感数据与专项验证 |
| Development Engineer | 前后端实现、调试、重构、性能/并发与开发自测 |
| Database Engineer | 数据模型、SQL、DDL、Migration、索引、一致性与数据库性能 |
| Test Engineer | Unit / Integration / API / Regression / Acceptance / Runtime 验证 |
| Code Reviewer | 独立 Diff/Commit Review、规范、正确性、可维护性、回归与技术债 |
| Integration Engineer | 变更检查、Git 集成、交付事实、集成后验证与 Delivery Result |

旧版经过实践验证的轻量步骤经验没有丢失；它们被还原为 lifecycle preset 和这些正式角色内部的能力。普通任务不会固定执行全部 9 个角色。

## Domain Agent

### `tp-software-lifecycle`
唯一软件工程 Domain Agent。它负责 L0～L3、角色/能力路由、返工、深度模式和完成判断，但不替专业角色做专业结论。

### `tp-base-maintenance`
负责安装配置、项目接入、路径解析、Workspace Inventory、项目搬迁、跨机器迁移和健康检查。

### `tp-knowledge`
负责长期可复用 Knowledge 与 task-scoped convergence。Integration 只提供 verified handoff；Knowledge 判断不再塞进交付角色。

### `tp-wiki`
负责从当前源码维护高信息密度、可引用、可增量更新的代码认知地图，Project Truth 最终回源码核验。

### `tp-project-autonomy`
负责自治发现、Proposal/Batch/Cycle/Workspace 与集成入口；批准后的软件工作仍交 `tp-software-lifecycle`，不复制一套开发流程。

### Record-first：工作优先，账本旁路记录

TP-Spec-Coding 使用 **Record-first** 思路：

```text
业务工作
   ↓
专业角色完成真实工作
   ↓
Runtime 记录状态 / 角色 / 事件 / 验证事实
   ↓
SQLite 作为权威账本
```

不会为了“流程完整”强迫生成空文档，也不会因为缺少可选工件阻塞普通开发。

公开 Task 状态只有：

```text
NEW / ACTIVE / BLOCKED / COMPLETED / CANCELLED
```

`requirement / architecture / development / verification ...` 是当前工作事实，不是繁琐状态机。

### 多 AI 工具可复用

核心 Agent / Skill 都是仓库内的可读契约，不绑定单一模型或 IDE。只要 AI 编程环境能够读取项目文件并执行本地命令，就可以按同一套角色和 Runtime 事实工作。

不同编辑器对 Agent / Skill 的自动发现能力不同；TP-Spec-Coding 不假装提供所有编辑器的原生插件适配。无法自动发现时，直接让 AI 读取对应 `SKILL.md` 即可。

### 跨机器，不把路径写死在项目里

机器路径属于用户安装状态：

```text
~/.tp-spec/installation.yaml
~/.tp-spec/workspaces.yaml
~/.tp-spec/registry.local.json
```

项目仓库只保存 portable identity 和项目状态，不保存某台机器的 Base / Wiki / Knowledge 绝对路径。

因此换电脑后不需要修改历史 Task 或 DB 里的专业角色身份，只需要重新配置当前机器路径并执行项目同步。

## 长期项目自治维护

`tp-project-autonomy` 是长期 Autonomous Maintenance 的薄入口：一次配置维护目标、L0～L3 上限、每 Cycle 新 Task 上限与隔离 Workspace 后，可由具备本地文件/Git/Python/Agent 能力的外部 Executor 周期性唤醒。自治开发只发生在独立 Git clone 中；普通软件 Task 仍由 `tp-software-lifecycle` 按 L0～L3 与正式 Role Pool 治理，Canonical 代码只有经过 Review + Integration Prepare/Verification + human_owner 明确 Apply 才会改变。

详细外部自动化协议见 `automation/autonomy/`。

## 快速开始

### 1. 环境要求

- Git
- Python **3.10+**
- 推荐 PowerShell 7（Windows 上运行完整 CI 和包装脚本时使用）

安装 Python 依赖：

```bash
python -m pip install -r requirements.txt
```

开发 / 测试环境：

```bash
python -m pip install -r requirements-dev.txt
```

### 2. 克隆 TP-Spec-Coding

```bash
git clone <repository-url>
cd TP-Spec-Coding
```

仓库中的配置示例是**空配置**，不会带作者机器路径、项目注册信息、Runtime DB 或用户 Knowledge/Wiki 数据。

### 3. 准备 Wiki / Knowledge 存储目录

选择两个你自己的目录：

```text
<your-wiki-root>
<your-knowledge-root>
```

这两个目录可以放在本机磁盘、同步盘或你自己管理的位置。TP-Spec-Coding 不替你猜路径。

### 4. 配置当前机器

在 TP-Spec-Coding 根目录运行：

```bash
python -m cli.main base configure \
  --base-root "<TP-Spec-Coding-root>" \
  --wiki-root "<your-wiki-root>" \
  --knowledge-root "<your-knowledge-root>"
```

检查：

```bash
python -m cli.main base installation-doctor
```

Windows 也可以使用包装器：

```powershell
pwsh -File scripts/tp-spec.ps1 base installation-doctor
```

### 5. 接入一个项目

```bash
python -m cli.main project init \
  --id <project-id> \
  --root "<project-root>"

# project init 会创建项目 Runtime，并写入 portable project-binding.yaml；
# 如果当前目录已经绑定到另一个 project id，会 fail-closed，不会覆盖。

python -m cli.main base sync-project \
  --workspace-root "<project-root>" \
  --apply
```

`sync-project` 会维护项目里的 TP-Spec-Coding managed entry，让 AI 知道如何解析 Base / Wiki / Knowledge 和项目 `.tp-spec` 状态，而不是复制机器绝对路径。

### 6. 让 AI 开始工作

打开你的业务项目，对 AI 说：

```text
请使用 TP-Spec-Coding 处理这个研发任务。
先定位当前机器的 TP-Spec-Coding Base，读取
entry/tp-spec-coding/SKILL.md，
由统一入口把软件意图交给 tp-software-lifecycle；
然后根据当前项目事实决定下一步，不要跳过已有 Task/Runtime 记录。
```

如果已经存在 Task，Software Lifecycle 会优先通过既有 Runtime 读取只读路由：

```bash
python -m cli.main workflow next --task <TASK-ID> --db <DB-PATH> --json
```

## 第一次配置也可以直接交给 AI

你不需要自己理解所有路径。可以把下面这段直接交给一个能访问本机文件系统的 AI：

```text
我要在这台机器配置 TP-Spec-Coding。
请先阅读仓库 README.md 和 docs/GETTING_STARTED.md。
不要猜路径，也不要写入项目源码中的机器绝对路径。

1. 确认 TP-Spec-Coding 仓库根目录；
2. 让我选择 Wiki System Root 和 Knowledge System Root；
3. 使用 base configure 写入用户级 installation.yaml；
4. 运行 base installation-doctor 验证；
5. 扫描/确认我要接入的项目目录；
6. 对每个项目使用 project init（仅未注册项目）和 base sync-project --apply；
7. 最后告诉我实际写入了哪些用户级配置，以及每个项目的绑定结果。

遇到身份冲突、重复 project id 或无法确认的旧路径时必须停止并询问，不要猜。
```

详细步骤见 [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)。

## 跨机器迁移

换电脑时，推荐把这三类东西分开看：

| 内容 | 是否跟项目走 | 说明 |
|---|---:|---|
| TP-Spec-Coding 源码 | 否 | 在新机器重新 clone / checkout 对应版本 |
| 项目 `.tp-spec` Task/Runtime 状态 | 是 | 属于项目研发事实 |
| `~/.tp-spec/*` | 否 | 当前机器的安装、workspace 和 registry 状态，需要重新生成 |
| Wiki / Knowledge 数据 | 由你决定 | 可以复制、同步或重新指定存储根 |

新机器上：

```text
clone TP-Spec-Coding
        ↓
base configure
        ↓
base installation-doctor
        ↓
base sync-project --apply
        ↓
继续原 Task
```

项目移动路径时，Runtime `project.root_path` 只是当前机器 locator/cache；portable identity 仍以项目 binding / project id 为准。存在同 ID 多个工作区时会 fail-closed，不自动猜哪个是真的。

## Agent、Role、Skill、Runtime 是什么关系

```text
Agent     = 用户/领域入口
Role      = 软件工程正式责任主体
Skill     = Role/Agent 内部可组合、按需加载的能力
Runtime   = 记录真实发生了什么，并提供恢复/迁移/安全边界
```

当前产品入口：

```text
entry/
└─ tp-spec-coding          # 唯一默认产品入口
```

当前公开 Domain Agent：

```text
agents/
├─ tp-software-lifecycle   # 软件工程 Domain Agent
├─ tp-base-maintenance
├─ tp-knowledge
├─ tp-wiki
└─ tp-project-autonomy
```

软件领域的 active formal Role 由 `governance/role-catalog.yaml` 统一登记；Role Skill 位于 `skills/roles/`，共享能力位于 `skills/capabilities/`，自治专项能力位于 `skills/autonomy/`。旧 action-role 只存在于 previous active contract → 5.2.5 migration/history，不参与 active routing。

未来可以增加视频生成、数据分析等新的 Domain Agent；它们拥有自己的角色/Skill 体系，但复用底层 Runtime，而不把完全不同的生命周期塞进软件工程 Skill Pool。

## UltraPlan / UltraReview

复杂任务不是简单“多想几遍”。TP-Spec-Coding 的深度模式强调**独立上下文**：

- UltraPlan：多个方案视角独立探索，再由主角色综合；
- UltraReview：完整性、正确性、影响面等 Reviewer 独立评审，再汇总；
- 当前 AI 编辑器支持隔离并发 Sub-Agent 时优先并发；
- 不支持并发时按相同 evidence pack 做隔离顺序执行，避免后一个视角被前一个答案污染。

## 数据与安全边界

- SQLite 是 Runtime 权威账本；`status.yaml`、`events.jsonl`、`generated/*` 是投影/可读视图；
- 专业事实使用真正执行角色的 `owner_role` / `actor_role`，Orchestrator 不代记；
- 生产写、DML/DDL、高风险权限/安全动作需要明确授权；
- PASS 必须有真实验证证据，未执行的人测不能伪装成 PASS；
- 路径或项目身份无法确定时 fail-closed；
- Base 本身不要求云端 API Key，核心 Runtime/治理逻辑可在本地运行。

## 稳定兼容命名

项目正式名称现为 **TP-Spec-Coding**。为兼容已有项目和历史 Task，以下技术命名暂不强制改名：

- CLI：`tp-spec`
- 项目状态目录：`.tp-spec/`
- 用户机器状态：`~/.tp-spec/`
- schema namespace：`tp-spec.*`
- 环境变量：`TP_SPEC_BASE_ROOT` 等
- managed block marker：`tp-spec-base:managed`（用于识别并安全更新旧项目中的受管区块）

这些名称属于持久化/兼容接口，不影响对外项目品牌。新项目的用户可见文案统一使用 **TP-Spec-Coding**。

## 常用命令

```bash
# 当前机器安装健康
python -m cli.main base installation-doctor

# 解析某项目 Base / Wiki / Knowledge
python -m cli.main base resolve --workspace-root "<project-root>"

# 同步项目入口和机器绑定
python -m cli.main base sync-project --workspace-root "<project-root>" --apply

# 查看下一开发角色（只读）
python -m cli.main workflow next --task <TASK-ID> --db <DB-PATH> --json

# 检查编排契约
python -m cli.main workflow doctor --json

# Knowledge 检索
python -m cli.main knowledge search --help

# Wiki 健康检查
python -m cli.main wiki doctor --help
```

完整 CLI：

```bash
python -m cli.main --help
```

## 仓库结构

```text
entry/          唯一默认产品入口
agents/         Domain Agent（软件生命周期 / Wiki / Knowledge / Base / Autonomy）
skills/roles/   软件工程正式 Role Skill
skills/capabilities/  Role 可按需加载的共享能力 Skill
skills/autonomy/      Autonomy Domain 的专项 Skill
governance/     活动契约、role catalog、风险、编排和内容系统规则
cli/            确定性 Runtime / Base / Wiki / Knowledge CLI
templates/      当前唯一活动 Task 契约模板
project-entry/  注入业务项目的 managed entry 模板
wiki/           Wiki 规则、schema、模板
knowledge/      Knowledge 规则、schema、模板
automation/     Wiki / Knowledge 可版本化维护协议
scripts/        CI、manifest、portable 校验和 PowerShell 包装器
```

## 开发与验证

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python scripts/check_version_consistency.py
python scripts/update_role_catalog.py --verify
python scripts/check_portability.py
python scripts/update_manifest.py --verify
```

Windows 完整门禁：

```powershell
pwsh -File scripts/ci/Test-TpSpecBase.ps1 -Mode Full
```

GitHub Actions 也会执行 Linux Python 回归与 Windows Full CI。

## 文档

- [Getting Started / 首次配置 / 跨机器迁移](docs/GETTING_STARTED.md)
- [Agent 与 Skill 入口](docs/AGENTS_AND_SKILLS.md)
- [Wiki 子系统](wiki/README.md)
- [Knowledge 子系统](knowledge/README.md)
- [贡献指南](CONTRIBUTING.md)
- [安全策略](SECURITY.md)

## 贡献

Bug、文档改进、兼容性修复和新的专业 Agent / Skill 都欢迎贡献。较大的行为变化请先说明目标、兼容影响和验证方式，避免把个人机器路径或用户数据提交进公共仓库。

详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

TP-Spec-Coding 使用 [MIT License](LICENSE)。
