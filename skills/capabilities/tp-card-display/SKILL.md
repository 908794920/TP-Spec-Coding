---
name: tp-card-display
display_name: 卡片展示调度
version: 5.2.9
description: 只读卡片展示能力；仅在用户明确要求查看 TP-Spec 全局、项目或任务卡片时，消费官方 CARD_DISPLAY 结果并按真实宿主能力选择会话内、Web Artifact 或离线 HTML 展示层。
---

# tp-card-display

## 定位
这是 `tp-software-lifecycle` 按需调用的**只读能力 Skill**。它不成为产品入口，不读取或改写 Runtime 状态，不维护后台状态；唯一职责是把用户明确要求“显示卡片”的意图路由到现有权威卡片命令，并根据命令返回的 `CARD_DISPLAY` 选择真实可用的展示层。

## Trigger
只在用户明确要求查看以下信息时使用：
- TP-Spec 全局/总配置卡片 → `tp-spec card global`
- 当前项目概况卡片 → `tp-spec card project`
- 指定正式任务卡片 → `tp-spec card task --task <TASK-ID>`

普通 `task get`、`workflow next`、代码阅读、搜索、测试、Shell 操作和普通 Runtime 步骤不得因为本 Skill 额外触发显式卡片。

## 展示流程
1. 先执行官方 `tp-spec card ...`，不得自行编造 HTML，不得用通用可视化指令替代权威 snapshot。
2. 需要会话内展示且当前宿主已确认支持 HTML fragment 时，为**当前单次子进程**传入 `--inline-output <ABSOLUTE-FRAGMENT-PATH>`，或仅在正式 Runtime 自动刷新场景设置 `TP_SPEC_CARD_INLINE_OUTPUT`。
3. 读取命令输出中的 `CARD_DISPLAY`。`inline.status=generated` 只表示 fragment 已生成，不表示宿主已经渲染。
4. 当前宿主确实提供官方会话内 HTML fragment 展示桥接时，使用该桥接在同一次回复展示 `CARD_DISPLAY.inline.path`，并说明实际展示层为“会话内”。不得把某个通用 `visualize` 文本当作固定协议。
5. 宿主不支持会话内 fragment、桥接会原样显示或 inline 生成失败时，优先使用 `CARD_DISPLAY.web_artifact`，说明实际展示层为“Web Artifact”。
6. 若宿主也无法打开 Web Artifact，则提供 `CARD_DISPLAY.web_artifact`（若存在）与 `CARD_DISPLAY.offline_html` 的可点击/可访问路径，说明实际展示层为“离线 HTML”。
7. Artifact 或 inline 失败不改变已成功的离线 HTML，更不得改变原 Runtime 命令的成功结果。

## 边界
- 不新增 MCP、MCP App、HTTP/WebSocket 或其他宿主服务。
- 不写 Runtime、Wiki、Knowledge，不新增 public state、数据库对象或后台服务。
- 不自行编造 HTML、卡片数据或第二份 snapshot；只消费现有 `tp-spec card` / Runtime 自动刷新生成的展示结果。
- 不因为生成了 `INLINE_VISUALIZATION` 或 `inline.status=generated` 就声称“已经在对话中显示”；必须以宿主实际采用的展示层为准。
- 自动刷新触发时机继续只由 `tp-software-lifecycle` 现有 Runtime 白名单负责，本 Skill 不新增触发时机。
