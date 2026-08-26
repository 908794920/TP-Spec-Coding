# 云端 AI 实施提示词：TP-Spec-Coding 会话内信息卡片

> 本文用于继续维护 TP-Spec-Coding 的三层信息卡片展示。当前方向是优先复用宿主原生会话内 HTML 可视化，同时保留 Web Artifact 与离线 HTML，不引入 MCP Server。

## 1. 目标

TP-Spec-Coding 已有三种只读 HTML 卡片：

- `tp-spec card global`
- `tp-spec card project --root <workspace-root>`
- `tp-spec card task --task <TASK-ID> --db <runtime-db>`

目标是在支持会话内 HTML 可视化的 Codex/ChatGPT 宿主中，让三种卡片直接出现在生成它们的同一次回复中；同时继续产生固定网站预览入口：

```text
<workspace>/.tp-spec-preview/card/index.html
```

显式命令通过 `--inline-output <ABSOLUTE-FRAGMENT-PATH>` 输出会话内 HTML 片段，并打印 `INLINE_VISUALIZATION` 标记。Skill 必须把该绝对路径在同一次回复中作为宿主会话内引用输出。宿主不支持该能力或片段失败时，依次降级到固定 Web Artifact 和离线 HTML。仓库代码不得宣称能够强制不支持该能力的宿主内嵌渲染。

## 2. 架构边界

继续复用：

```text
Runtime / Resolver / Registry / Wiki / Knowledge
                ↓
cli/cards/snapshot.py
                ↓
cli/cards/render.py
       ↙              ↓                  ↘
离线 HTML      固定 Web Artifact      会话内 HTML 片段
                index.html           同回复宿主引用
```

不得新增：

- MCP Server / MCP Apps；
- FastMCP；
- 后台服务；
- WebSocket / 轮询；
- 第二套数据库、Registry、任务账本或状态机；
- 页面内写 Runtime/Wiki/Knowledge 的操作。

## 3. 输出规则

1. 现有离线 HTML 输出继续保留，不改变其降级价值。
2. 每次显式卡片命令同时覆盖固定 `.tp-spec-preview/card/index.html`。
3. 宿主支持会话内可视化时，显式命令传入唯一的 `--inline-output` 绝对路径并生成 HTML 片段。
4. `card project` 默认使用显式 `--root` 作为 Artifact 工作区。
5. `card global` / `card task` 使用当前工作区；测试或特殊宿主可显式传 `--artifact-root`。
6. 正式 Runtime 白名单步骤通过单进程 `TP_SPEC_CARD_INLINE_OUTPUT` 同时刷新 Task 离线预览、固定 Artifact 与会话内片段。
7. 固定 Artifact 只保留最新内容；会话内片段使用唯一文件名；历史事实仍由 Runtime Event 保存。
8. Artifact 或会话内片段写入失败不能让已经成功的 Runtime 命令变成失败。
9. 会话内片段超过 1 MB 时只压缩片段中的长文本和超长集合，并在异常区显示截断提示；离线 HTML 与 Web Artifact 保留完整快照。

## 4. UI 稳定性

- 导航必须使用 `button type="button"` + `hidden` 切换，不用 URL hash/锚点。
- 时间线展开必须使用按钮、`aria-expanded`、`aria-controls`，不用 `<details>`。
- 禁止 `scrollIntoView()`、`window.scrollTo()`、`location.hash` 或手工恢复页面 `scrollTop`。
- 完整网页保持外层高度稳定、内容在卡片内部滚动；会话内片段不使用固定视口高度或内部纵向滚动，由宿主按内容定高。
- 复制、筛选、标签切换和时间线展开均只改变本地 UI，不访问网络。
- 保留严格 CSP、无 CDN、敏感键剔除和安全 DOM 渲染。
- 会话内片段不得包含 `doctype/html/head/body`，根节点使用唯一 ID，样式和 DOM 必须隔离，文件小于 1 MB。

## 5. Skill 语义

- 用户明确请求全局配置、当前项目或指定任务时才生成对应卡片。
- 宿主支持会话内 HTML 可视化时，必须使用 `--inline-output` 并在同一次回复输出对应引用，不能打开右侧网页代替。
- 宿主未渲染会话内片段时，依次展示固定 `index.html` 和离线 HTML，任何层级都不得只回复路径而不尝试宿主支持的展示方式。
- 普通文件读取、代码搜索、测试、Shell、`workflow next`、`task get` 不触发卡片。
- 正式任务自动刷新仍只允许现有白名单：`task create/checkpoint/verify/block/resume/delivery-converge/complete`、`work start/end`、`workflow confirm`。

## 6. 验收

至少验证：

- 三种显式命令均能生成原离线 HTML、固定 `index.html` 和会话内片段；
- 三种片段均无完整文档标签、外部请求、固定视口高度、内部纵向滚动和程序化页面滚动；
- 超大快照的会话内片段严格小于 1 MB、显示截断提示，完整离线/Web Artifact 内容不被截断；
- Skill 在生成片段的同一次回复中输出会话内引用；
- 多次生成只覆盖同一个 `index.html`；
- `--artifact-root` 与 `--inline-output` 可用于 Fixture/宿主工作区；
- Artifact 或片段失败时离线 HTML 仍可用；
- Runtime 成功不受卡片失败影响；
- HTML 无 `<details>`、hash 跳转、主动滚动和外部网络请求；
- 原卡片测试与 Role Catalog/Manifest/Portability 门禁不回归。
