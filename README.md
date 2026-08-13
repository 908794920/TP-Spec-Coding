# TP-Spec-Coding

> **让 AI 按研发流程做事，而不是只靠一段聊天直接改代码。**

TP-Spec-Coding 是一个**本地优先、可追溯、可迁移、可扩展**的 AI 研发工作流框架。你把研发任务交给 `tp-workflow-orchestrator`，它像“开发组长”一样判断任务复杂度，并按需组织需求分析、产品设计、架构设计、开发、验证和交付；真正的专业结论仍由对应专业 Skill 负责，过程事实写入本地 Runtime 账本。

当前版本：**v5.2.0** · License：**MIT**

## 为什么做这个项目

直接让 AI 写代码很快，但项目一复杂，经常会遇到这些问题：

- 需求、约束和决策散在聊天记录里，换会话以后容易丢；
- 不同 AI 对同一任务的理解不一致，做完才发现方向错了；
- 大任务不知道该先分析、先设计还是直接开发；
- “测试通过”“已经处理”很难追溯是谁、何时、基于什么证据得出的；
- 换 AI 工具、换电脑、移动项目目录后，要重新告诉 AI 一堆路径和背景；
- 老项目每次都从源码重新读，Wiki 和长期知识没有形成真正可复用的资产。

TP-Spec-Coding 的目标不是增加更多流程，而是让 AI 在需要的时候按正确的专业分工工作，同时把关键事实留下来。它不替代 Codex、Claude Code、Qoder、OpenCode 等 AI 编程工具，而是给这些工具一套可以共同遵循的研发工作方式。

## 能带来什么

| 直接和 AI 聊天开发 | 使用 TP-Spec-Coding |
|---|---|
| 每次都要重新解释上下文 | Task、Wiki、Knowledge 让已确认事实可以继续复用 |
| AI 自己决定先做什么 | 开发组长根据 L0～L3 组织合适的专业角色 |
| 做完才发现方向不对 | 高风险任务按需启用独立 UltraPlan / UltraReview |
| “测试过了”很难追溯 | Runtime 记录专业角色、事件和真实验证证据 |
| 换工具、换电脑重新配置 | 机器路径和项目事实分离，可重新绑定而不改历史账本 |
| 一个 Agent 什么都干 | Agent 是专业入口，Skill 是可组合能力，可以继续扩展自己的专业 Agent |

## 核心优势

### 一个开发入口

开发流程只需要找：

```text
tp-workflow-orchestrator
```

它是“开发组长”，只负责：

- 判断 L0～L3 任务复杂度；
- 决定下一阶段应该找哪个专业角色；
- 判断是否需要 UltraPlan / UltraReview；
- 在真正需要用户选择或授权时请求确认；
- 读取现有 Task 事实继续工作。

它**不写业务代码、不替专业角色做结论、不抢专业角色的账**。

### 专业角色仍然可追溯

开发流程内部有 7 个专业 Skill：

```text
tp-requirement-analysis       需求分析
tp-product-design             产品设计
tp-architecture-design        架构设计 / UltraPlan
tp-architecture-review        独立架构评审
tp-development-engineering    开发实现
tp-verification-engineering   验证 / UltraReview
tp-delivery-convergence       交付与知识收敛
```

目录位置可以变化，但 role ID 是稳定身份。Runtime 中的 `owner_role` / `actor_role` 记录真正完成专业工作的角色，因此以后可以回答：**谁做了什么、为什么这么做、验证结果是什么。**

### 另外 3 个独立专业 Agent

它们不是开发流程里的“步骤”，而是可以直接调用的专业能力，也是 TP-Spec-Coding 可扩展 Agent 体系的示例。

#### `tp-base-maintenance` — 基座维护工程师

负责安装配置、项目接入、路径解析、Workspace Inventory、项目搬迁、跨机器迁移和健康检查。

适合解决：

- Base / Wiki / Knowledge 放在哪里；
- 项目换盘、换目录、换电脑以后如何重新绑定；
- 如何让 AI 自己检查当前机器的配置，而不是硬编码绝对路径；
- 多个项目如何统一维护。

#### `tp-knowledge` — 知识系统工程师

负责长期可复用 Knowledge：外部文档、Task evidence、代码证据、业务规则、长期决策、检索和增量维护。

它解决的是：**AI 做过一次以后，下一次能不能真正复用，而不是每次重新理解整个项目。**

#### `tp-wiki` — 代码理解 Wiki 工程师

负责把当前源码维护成高信息密度、可引用、可增量更新的代码认知地图，并要求关键结论最终回到源码核验。

它解决的是：**大型或老项目不需要每次都从几千个文件重新开始读。**

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
agents/tp-workflow-orchestrator/SKILL.md，
然后根据当前项目事实决定下一步，不要跳过已有 Task/Runtime 记录。
```

如果已经存在 Task，Orchestrator 会优先读取只读路由：

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

## Agent、Skill、Runtime 是什么关系

```text
Agent     = 用户可以直接找的专业入口
Skill     = Agent 内部可组合的专业能力
Runtime   = 记录真实发生了什么
```

当前公开 Agent：

```text
agents/
├─ tp-workflow-orchestrator   # 开发组长 / 研发流程入口
├─ tp-base-maintenance        # 基座安装与迁移
├─ tp-knowledge               # 长期知识
└─ tp-wiki                    # 代码理解
```

研发流程内部 Skill：

```text
skills/
├─ tp-requirement-analysis
├─ tp-product-design
├─ tp-architecture-design
├─ tp-architecture-review
├─ tp-development-engineering
├─ tp-verification-engineering
└─ tp-delivery-convergence
```

你也可以按同一模式扩展自己的 Agent，例如需求文档、技术写作、数据分析、视频生成等；只要保持 Agent 与 Skill 的职责边界清晰即可。

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

项目正式名称从 v5.2.0 起为 **TP-Spec-Coding**。为兼容已有项目和历史 Task，以下技术命名暂不强制改名：

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
agents/          对外专业 Agent 与 role catalog
skills/          研发内部角色与可复用方法 Skill
governance/      活动契约、风险、编排和内容系统规则
cli/             确定性 Runtime / Base / Wiki / Knowledge CLI
templates/       当前唯一活动 Task 契约模板
project-entry/   注入业务项目的 managed entry 模板
wiki/            Wiki 规则、schema、模板
knowledge/       Knowledge 规则、schema、模板
automation/      Wiki / Knowledge 可版本化维护协议
scripts/         CI、manifest、portable 校验和 PowerShell 包装器
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
