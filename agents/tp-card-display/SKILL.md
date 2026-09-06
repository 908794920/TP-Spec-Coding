---
name: tp-card-display
display_name: 卡片展示调度
version: 5.3.1
id: tp-card-display
status: active
type: human-owner-skill
role: tp-card-display
description: 独立只读卡片 Domain Agent；仅在用户明确要求查看 TP-Spec 全局、项目或任务卡片时，消费官方 CARD_DISPLAY 结果并按真实宿主能力选择会话内、Web Artifact 或离线 HTML 展示层。
---

# tp-card-display

## 定位
这是由 `tp-spec-coding` 直接路由的**只读卡片 Domain Agent**。它不成为产品入口，不读取或改写 Runtime 状态，不维护后台状态；唯一职责是把用户明确要求“显示卡片”的意图路由到现有权威卡片命令，并根据命令返回的 `CARD_DISPLAY` 选择真实可用的展示层。

`tp-software-lifecycle` 只拥有 Runtime 成功后的刷新触发策略；触发后产生的 `CARD_DISPLAY` 必须遵循本 Agent 的展示契约。两者共用当前 Base 的 `cli/cards` 渲染入口，任何一方不得复制卡片模板、渲染器或 Host bridge。

## Trigger
只在用户明确要求查看以下信息时使用：
- TP-Spec 全局/总配置卡片 → `tp-spec card global`
- 当前项目概况卡片 → `tp-spec card project`
- 指定正式任务卡片 → `tp-spec card task --task <TASK-ID>`

普通 `task get`、`workflow next`、代码阅读、搜索、测试、Shell 操作和普通 Runtime 步骤不得因为本 Skill 额外触发显式卡片。

## 三层展示事实
以下三个事实必须独立判断，禁止互相推导：

| 展示事实 | 含义 | Base 能否自行证明 |
|---|---|---|
| `fragment generated` | `CARD_DISPLAY.inline.status=generated`，inline fragment 文件已生成 | 是 |
| `host capability confirmed` | 当前宿主明确提供可消费 HTML fragment 的正式桥接能力 | 否，由当前 Agent/Host 上下文确认 |
| `actual host render` | 本次正式桥接调用已经返回成功，用户会话中实际完成渲染 | 否，由本次 Host bridge 结果确认 |

`inline.status=generated` 永远不等于“已展示”。`capability 未确认` 必须按不可用处理（fail-closed），不得根据宿主名称、历史经验或猜测乐观认定支持。

## Codex 宿主桥接
仅当当前运行时的 Skill Catalog 同时表明存在 Codex `visualize` 能力，并且当前会话提供显式可写的线程级 visualization 目录时，才确认当前宿主可使用 Codex 会话内 HTML bridge。不得通过产品名称、目录名、环境变量或历史会话经验推断。

在该 Codex 分支中，正式 bridge 是同一最终回复中的内容引用：

```text
visualize{"path":"<绝对-inline-fragment-path>"}
```

它只挂载官方 `tp-spec card` 生成的 fragment，不重写、拼接或手写卡片 HTML；应将 `--inline-output` 直接指向该线程级 visualization 目录中的 ASCII 文件名。该 Codex 内容引用不是裸 HTML、Markdown code fence 或临时通用可视化，属于本 Skill 认可的正式 Host bridge。

## 展示决策规则
默认且唯一的展示优先级是：

```text
会话内 HTML fragment → Web Artifact → 离线 HTML
```

降级原因属于本次展示解释语义，不写入 Runtime DB、Task Event 或其他持久化 Task truth：

| 原因码 | 条件 | 下一展示层 |
|---|---|---|
| `INLINE_CAPABILITY_UNAVAILABLE` | host capability 未确认、明确不存在或当前不可用 | Web Artifact |
| `INLINE_RENDER_FAILED` | fragment 已生成，但实际 Host bridge 调用失败 | Web Artifact |
| `INLINE_GENERATION_FAILED` | 请求 inline 后 `inline.status=failed` | Web Artifact |
| `WEB_ARTIFACT_UNAVAILABLE` | `artifact.status=failed` 或没有可用 `web_artifact` | 离线 HTML |
| `WEB_ARTIFACT_OPEN_FAILED` | Web Artifact 已生成，但当前宿主实际打开/展示失败 | 离线 HTML |

任何降级都必须说明实际采用的展示层和对应原因；不得把候选物“已生成”误报为宿主“已展示”。

## 展示流程
1. 先检查当前宿主能力。若满足“Codex 宿主桥接”条件，为**当前单次子进程**传入 `--inline-output <THREAD-VISUALIZATION-DIR>/<ascii-name>.html`；仅在正式 Runtime 自动刷新场景设置 `TP_SPEC_CARD_INLINE_OUTPUT`。其他宿主只有在其自身正式 bridge 已确认时才传入绝对 fragment 路径；能力未确认则不猜测，记录解释原因 `INLINE_CAPABILITY_UNAVAILABLE` 并准备 Web Artifact 降级。
2. 执行官方 `tp-spec card ...`，不得自行编造 HTML，不得用通用可视化指令替代权威 snapshot。
3. 读取命令输出中的 `CARD_DISPLAY`。`inline.status=generated` 只证明 `fragment generated`；`inline.status=failed` 使用 `INLINE_GENERATION_FAILED` 降级。
4. 仅当 inline capability 已确认且 fragment 已生成时，调用当前宿主正式 bridge 消费 `CARD_DISPLAY.inline.path`。Codex 必须在同一最终回复输出 `visualize{"path":"<CARD_DISPLAY.inline.path>"}`；其他宿主使用其已确认的正式 bridge。只有**实际桥接调用成功**后才可声称“会话内已展示”；实际桥接失败使用 `INLINE_RENDER_FAILED` 降级。
5. 降级到 Web Artifact 时消费 `CARD_DISPLAY.web_artifact`。若 Artifact 未生成/不可用，使用 `WEB_ARTIFACT_UNAVAILABLE`；若已生成但实际打开失败，使用 `WEB_ARTIFACT_OPEN_FAILED`，继续降级。
6. 最终降级使用 `CARD_DISPLAY.offline_html`，并明确实际展示层为“离线 HTML”。若宿主支持路径/链接交互，可提供可点击/可访问路径；不得声称它已经在会话内渲染。
7. Artifact、inline 或 Host 展示失败都不得改变已成功的离线 HTML，更不得改变原 Runtime 命令的成功结果。

## 边界
- 不新增 MCP、MCP App、HTTP/WebSocket 或其他宿主服务。
- 不写 Runtime、Wiki、Knowledge，不新增 public state、数据库对象或后台服务。
- 不新增 `host_capability`、`rendered` 一类 Base 无法证明的 `CARD_DISPLAY` 字段；Host capability/render outcome 只属于当前 Agent/Host 的一次性展示事实。
- 不自行编造 HTML、卡片数据或第二份 snapshot；只消费现有 `tp-spec card` / Runtime 自动刷新生成的展示结果。
- 不把裸 HTML、Markdown code fence 或临时手写可视化冒充正式 inline bridge；仅在本 Skill 已确认的 Codex 条件下，允许使用上述 `visualize` 内容引用挂载官方 fragment。
- 不因为生成了 `INLINE_VISUALIZATION` 或 `inline.status=generated` 就声称“已经在对话中显示”；必须以宿主本次实际采用且成功的展示层为准。
- 自动刷新触发时机继续只由 `tp-software-lifecycle` 现有 Runtime 白名单负责，本 Skill 不新增触发时机。
