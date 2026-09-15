# TP-Spec-Coding

> **一个入口，把一个人的工程能力扩展成一支轻量 AI 项目组（面向一人项目组）。**

TP-Spec-Coding 是一个本地优先、可追溯、可迁移的软件工程协作基座。用户从 `tp-spec-coding` 进入；软件研发交给 `tp-software-lifecycle`，再根据任务风险、当前事实和配置规则按需启用正式 Role 与 Skill。

## 项目定位

TP-Spec-Coding 解决的不是“让 AI 多写几份流程文档”，而是让 AI 在长期工程中能稳定找到项目、复用已有事实、选择合适能力并留下最低必要的可追溯记录。

核心体验目标：**底层可以复杂，用户入口必须简单。** Runtime 可以维护 Task、Event、Evidence、Workflow 和版本兼容；用户日常只需要描述真实工作目标并让 CLI/Runtime 自动完成治理记账。

## 核心产品模型

```text
用户
  ↓
tp-spec-coding                 唯一默认产品入口
  ↓
Domain Agent                   按意图选择领域能力
  ↓
Role / Capability Skill        按任务需要选择能力，不是固定流程包
  ↓
CLI / Runtime                  自动维护 Task / Event / Evidence / Workflow
```

Agent / Role / Skill 的权威拓扑来自 [`governance/role-catalog.yaml`](governance/role-catalog.yaml)。面向用户的文档导航见 [`docs/README.md`](docs/README.md)，不要在 README 再维护一份完整 Role / Skill 清单。

## 核心原则

- **Record-first，工作优先。** 状态、账本、Evidence、事件等主要由 CLI/Runtime 自动产生；AI 不负责手写大量 Governance 文档。
- **配置驱动策略。** 路由、阈值、Role/Skill 条件和生命周期规则尽可能由 Base 配置控制，升级 Base 不等于重新配置一次业务项目。
- **Governance 是副产物。** 非关键治理记录缺失不应轻易阻塞或回滚已经完成的真实工作；真正参与路由和一致性的核心事实才 fail-closed。
- **完整能力，按需执行。** 生命周期描述能力上限，不要求所有任务跑完整流程；Role 是能力集合，不是固定阶段包。
- **机器路径留在机器上。** 公共仓库和业务项目只保存 portable identity；安装路径由用户级配置解析。

## 交给 AI 自动安装

可以把下面内容直接复制给能够访问本机文件系统的 AI：

```text
请为我检查并配置 TP-Spec-Coding。

1. 先阅读 README.md、docs/README.md、docs/GETTING_STARTED.md。
2. 先检查现有安装和项目绑定，不要默认这是第一次安装。
3. 不要猜测任何机器路径。先确认 Base Root、Wiki System Root、Knowledge System Root 和业务项目根目录。
4. 不要把 machine-local 绝对路径写入公共仓库、业务源码、README、AGENTS 或 portable project binding。
5. 安装缺失依赖后运行 base installation-doctor；已有配置正确时保持不变。
6. 只有 installation 配置缺失或明确需要修复时才运行 base configure。
7. 只有项目尚未注册/绑定时才运行 project init；已有合法 binding 时不要重新初始化。
8. 对需要同步的项目运行 base sync-project --apply，然后运行 base resolve 验证解析结果。
9. 遇到路径不存在、project id 冲突、多个工作区候选、需要覆盖现有配置或身份不明确时停止并询问，不要自动猜。
10. 不修改业务源码、生产数据库或 Runtime 事实源，不新增服务。
11. 最后报告：实际使用的 Base/Wiki/Knowledge/项目路径、写入或保持不变的配置、项目绑定、doctor/resolve 结果和仍需我决定的事项。
```

常用命令的完整参数见 [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md)。这里的关键动作是 `base configure`、`base installation-doctor`、`project init`、`base sync-project --apply` 和 `base resolve`，但是否执行写操作必须先依据当前机器事实判断。

## 手工快速开始

要求：Git、Python 3.10+；Windows 完整脚本推荐 PowerShell 7。

```bash
python -m pip install -r requirements.txt
python -m cli.main base installation-doctor
```

如果这是全新安装，在确认三个根目录后配置：

```bash
python -m cli.main base configure \
  --base-root "<tp-spec-coding-root>" \
  --wiki-root "<wiki-root>" \
  --knowledge-root "<knowledge-root>"
```

接入**尚未绑定**的项目：

```bash
python -m cli.main project init --id <project-id> --root "<project-root>"
python -m cli.main base sync-project --workspace-root "<project-root>" --apply
python -m cli.main base resolve --workspace-root "<project-root>"
```

已有安装或已有项目 binding 时不要机械重复 configure/init；先 doctor/resolve，再做最小必要修复。

## 本地可视化工作台

在本项目根目录安装一次前端依赖，随后用同一命令管理前端与 Python 只读接口：

```bash
npm ci
npm run dev
```

需要满足 `package.json` 的 Node.js 版本范围，并已准备上文的 Python 运行依赖。访问终端输出的本机地址；`Ctrl+C` 关闭本次两端。启动不会自动安装依赖、初始化/迁移 Runtime 或执行测试。

工作台提供项目总览、任务工作区、全局配置、真实 WorkItem 关系图、四类详情、验收/证据适用性、按需结单预检，以及刷新失败/乱序响应处理。详情只解释事实，不执行验收或结单。旧卡片命令、渲染器、模板、宿主桥接和展示角色已退出，不保留兼容别名；本地工作台是唯一可视化入口，现有纯文本/JSON 查询继续可用。

本专项源码和 Patch 已交付，云端局部验证不代表真实浏览器、锁定工具链构建/完整类型检查或 Windows 已通过；这些仍由本地安装后的实际验证确认，详见工作台说明。

启动参数、来源说明、开发命令与排错见 [`docs/WORKBENCH.md`](docs/WORKBENCH.md)。

## 按 Agent 选择能力

第一次选择能力直接打开 [`docs/README.md`](docs/README.md)。软件研发从 [`docs/agents/tp-software-lifecycle.md`](docs/agents/tp-software-lifecycle.md) 开始；Base、Wiki、Knowledge、Autonomy 也各有独立导航。Role/Skill 列表由 Role Catalog 驱动的生成区块维护，避免代码升级后人工同步多份能力清单。

## 数据与安全边界

- Runtime SQLite `task` / `task_event` 是任务事实账本；本地工作台、status/events 文件属于投影或展示产物；历史 HTML 不代表当前状态。
- `summary` 是人类可读文本，不参与 PASS/FAIL、阶段完成、颜色或下一步路由判断。
- Evidence、事件语义和可信 producer 由正式 CLI 自动生成；普通 `event add` 不能伪造正式 Review/Verification/Workflow 结果。
- Wiki / Knowledge 是代码理解与复用知识层，不替代 Runtime 任务状态。
- 机器级 installation、workspace inventory、registry 保存在用户环境，不提交真实个人路径到公共发布面。

## 文档入口

- [`docs/README.md`](docs/README.md)：统一文档地图
- [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md)：安装、已有安装升级、项目接入、迁移与排错
- [`docs/AGENTS_AND_SKILLS.md`](docs/AGENTS_AND_SKILLS.md)：Agent / Role / Skill / Runtime 模型
- [`wiki/README.md`](wiki/README.md)：Wiki 子系统
- [`knowledge/README.md`](knowledge/README.md)：Knowledge 子系统
- [`automation/README.md`](automation/README.md)：自动化入口
- [`CHANGELOG.md`](CHANGELOG.md)：发布历史

## 开发与验证

```bash
python -m pip install -r requirements.txt
```

修改本仓库前，按需读取 [`docs/TESTING.md`](docs/TESTING.md) 的现行规则：仅验证当前改动，必要的临时单测执行后清理，不保留基座历史套件。日常开发、commit、push、PR 和 Patch 交付不自动触发全量测试；确需全量验证须由用户明确决定。

已有 Manifest、Role Catalog 等生成工具继续用于对应内容变更，不组合成每次必跑的检查包。业务项目测试、Runtime 验证及结果接收能力保持原职责，不因基座测试清理而删除。

## 贡献与 License

贡献规则见 [`CONTRIBUTING.md`](CONTRIBUTING.md)，安全说明见 [`SECURITY.md`](SECURITY.md)。请勿把真实机器路径、用户配置、Runtime DB 或业务私有数据提交到公共仓库。

TP-Spec-Coding 使用 [MIT License](LICENSE)。
