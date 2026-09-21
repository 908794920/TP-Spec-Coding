# TP-Spec-Coding Getting Started

如果希望直接交给 AI 安装，请先返回根目录 [`README.md`](../README.md) 的“**交给 AI 自动安装**”章节。本手册负责人工安装、已有安装升级、项目接入、跨机器恢复和排错细节。

## 1. 准备环境

需要 Git、Python 3.10+；Windows 完整脚本推荐 PowerShell 7。

```bash
python -m pip install -r requirements.txt
python -m cli.main --help
```

全新机器从空配置开始；仓库公开配置是空模板，不携带作者机器路径、项目注册、Runtime DB、Wiki 或 Knowledge 用户数据。用户级项目注册由 `registry.local.json` 维护。

## 2. 先判断：首次安装还是已有安装

先运行：

```bash
python -m cli.main base installation-doctor
```

如果现有 installation 配置和路径都有效，**保持现状**，不要为了升级 Base 重新 configure。只有配置缺失、路径已迁移或 doctor 明确报告可修复问题时才进入下一节。

用户级机器配置通常位于 `~/.tp-spec/`。这些文件属于本机状态，不复制进业务仓库。

## 3. 首次配置 Base / Wiki / Knowledge

先由用户确认：

```text
Base Root       = <tp-spec-coding-root>
Wiki Root       = <wiki-root>
Knowledge Root  = <knowledge-root>
```

不要猜路径；Wiki/Knowledge Root 应是用户明确选择的位置。

```bash
python -m cli.main base configure \
  --base-root "<tp-spec-coding-root>" \
  --wiki-root "<wiki-root>" \
  --knowledge-root "<knowledge-root>"
python -m cli.main base installation-doctor
```

`TP_SPEC_BASE_ROOT` 可以作为 Base 定位信号，但不要把它的机器绝对值写入业务项目文档。

## 4. 接入项目

先确认 `<project-root>` 是否已经存在 `.tp-spec/config/project-binding.yaml`，并使用 resolver/registry 判断是否已经注册。

只有**尚未绑定**的项目才执行：

```bash
python -m cli.main project init --id <project-id> --root "<project-root>"
```

已有合法 binding 时**不要重新执行 project init**。如果目录已绑定到不同 project id，命令应 fail-closed，由用户决定，而不是覆盖。

同步 managed entry 并验证：

```bash
python -m cli.main base sync-project --workspace-root "<project-root>" --apply
python -m cli.main base resolve --workspace-root "<project-root>"
```

Portable project binding 只保存稳定 identity，不重复保存 Wiki/Knowledge 的机器绝对路径。

## 5. 让 AI 开始软件研发

唯一默认产品入口是 [`entry/tp-spec-coding/SKILL.md`](../entry/tp-spec-coding/SKILL.md)。软件意图交给 `tp-software-lifecycle`；具体 Role/Skill 由当前工作流事实和配置按需解析。

```text
请使用 TP-Spec-Coding 处理这个研发任务。
先读取当前项目 binding 和已有 Runtime 事实；
从 tp-spec-coding 路由到合适 Domain Agent；
如果属于软件研发，由 tp-software-lifecycle 根据当前任务事实按需选择 Role；
不要跳过已有 Task，不要为了补 Governance 文档重复真实工作。
```

已有 Task 可以查看只读路由：

```bash
python -m cli.main workflow next --task <TASK-ID> --db <DB-PATH> --json
```

完整 Role 导航见 [`agents/tp-software-lifecycle.md`](agents/tp-software-lifecycle.md)，不在本手册维护第二份 Role 清单。

## 6. Runtime、Event 与 Evidence

Runtime 负责自动维护核心事实：

- Task 状态与当前阶段；
- 结构化 `task_event`；
- Review / Verification / Workflow Confirmation / Delivery 等正式结果；
- Evidence metadata 与来源；
- 必要的 status/events 只读投影。

本地工作台只消费这些事实，普通 CLI 不会启动或刷新页面；启动方式见 [WORKBENCH.md](WORKBENCH.md)。

AI 应调用专用业务 CLI，让 Runtime 自动记账。`summary` 只用于人类阅读，不能作为 PASS/FAIL、阶段完成或路由依据。缺少非关键 Governance enrichment 时应优先保留真实工作结果，而不是要求 AI 手工补大量文档。

## 7. Wiki / Knowledge / Autonomy

- Wiki：见 [`agents/tp-wiki.md`](agents/tp-wiki.md) 与 [`../wiki/README.md`](../wiki/README.md)
- Knowledge：见 [`agents/tp-knowledge.md`](agents/tp-knowledge.md) 与 [`../knowledge/README.md`](../knowledge/README.md)
- Autonomy：见 [`agents/tp-project-autonomy.md`](agents/tp-project-autonomy.md) 与 [`../automation/autonomy/README.md`](../automation/autonomy/README.md)

它们都是按需能力，不要求每个软件任务全部启用。

## 8. 跨机器或目录迁移

迁移原则是“带 portable identity，重建 machine-local resolution”：

1. 在新机器准备 Base/Wiki/Knowledge 根目录；
2. 运行 `base installation-doctor` 判断已有状态；
3. 仅在需要时 `base configure`；
4. 打开业务项目，保留已有 project binding 和 Runtime；
5. 执行 `base sync-project --apply` 与 `base resolve`；
6. 出现 project id 冲突、多个 workspace 候选或路径身份不明时停止并由用户决定。

不要通过编辑历史 `task_event`、复制旧机器 registry 或把绝对路径写回项目来“修复”迁移。

## 9. 排错顺序

### Base 找不到

```bash
python -m cli.main base installation-doctor
```

检查 installation 配置、`TP_SPEC_BASE_ROOT` 和当前 Base 实际目录是否一致；不要在多个候选之间自动猜。

### 项目解析异常

```bash
python -m cli.main base resolve --workspace-root "<project-root>"
```

先确认 binding 的 project id，再检查当前用户 registry/workspace inventory。

### 工作流异常

先读取 Task、结构化 Event 和当前 workflow contract。旧事件缺少新结构化字段时只允许使用 Base 明确定义的确定性 legacy contract；禁止扫描自由文本 summary 猜 PASS/FAIL。

## 10. 同版本源码升级与兼容

本轮原始输入已经标为当前活动契约，只检查 VERSION 不能确认新能力是否存在。应用前核对交付 Patch 头部的原始源码身份、manifest 与适用链，保留自己的未提交修改、Runtime、Knowledge 和机器配置；不要 `reset --hard`、删库或覆盖业务任务来凑基线。

最终全量 Patch 以原始 `32e8abb` ZIP 为输入，不应叠加在已应用 P1/P2A/P3/P4/P5A/P5B/P5C/P2B 的目录。已应用增量时，在独立原始基线副本核对全量目标，再由实际合并者按现有授权集成差异；不在用户工作区反复试错或重复应用。补丁应用命令和精确 digest 随 Patch 提供。

| 事实/数据 | 升级后的解释 |
|---|---|
| Task 公共状态与 SQLite 物理 schema | 不新增第二账本或额外 Task 状态；用既有事件表保存新记录 |
| `tp-spec.execution/v1` / `tp-spec.work-unit/v1` | 显式计划、角色参与、范围和结果接收/候选；未采用标记的旧 Task/Work 不补造新记录 |
| `tp-spec.closeout/v1` / `tp-spec.task-learning/v1` | 新 READY Delivery 按有效等级检查并强制生成/复用任务输入评估；无信号也处理，稳定输入可复用 |
| 同版本旧在途 Task | 先只读查看既有事实；需要新显式计划时用 `work plan`，不补造过去开始/完成；后续新 Delivery 才采用其新契约 |
| 旧终态/历史案例 | `projection inspect` / `task terminal-check` 只读发现过期或漂移；不补新知识/步骤，不重算旧 hash 或改成 ACTIVE |
| 更早版本在途 Task | 仍走既有 `project upgrade-contract` 与显式 `task migrate` 的适用契约和授权，不改版本字符串绕过；本次未替所有历史版本做迁移验收 |

在实际获准的机器安装中先 `base installation-doctor`、`base resolve --workspace-root "<project-root>"`；同名版本不自动改 installation。确需同步薄入口时先运行不带 `--apply` 的 `base sync-project` 查看计划，再经已有授权应用；AGENTS 自有区、Runtime 和项目 binding 保留，不把机器路径迁入共享内容。

新格式已写入后不要降级旧程序继续操作这些在途 Task。逆向 Patch 只恢复源码，不能撤销数据库事件、知识写入或人工决定；优先恢复新代码或向前修复。实际 Windows 安装、路径/Junction、宿主会话隔离、真实业务/权限和人工验收需现场核对；[工作台补验表](WORKBENCH.md)列出当前前端缺口，不因此增加全仓回归。

## 11. 发布与文档

当前用户文档从 [`README.md`](README.md) 进入。Agent / Role / Skill 的机器权威仍是 [`../governance/role-catalog.yaml`](../governance/role-catalog.yaml) 与各自 `SKILL.md`；导航文档只负责解释与跳转。
