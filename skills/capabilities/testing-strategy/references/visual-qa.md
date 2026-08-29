# 可视化 QA：Diff-aware 真实浏览器验证

仅在任务包含 UI/页面 Acceptance 时使用。核心原则：**先从 Change Set/Diff 决定测哪些页面，再以真实用户方式验证；源码字符串断言不能代替页面验收。**

## 1. 从 Diff 推导受影响页面

按当前真实变更映射，不做无边界全站巡检：

- Controller / Router 变化 → 对应 URL；
- JSP / Vue / Template / Component 变化 → 渲染它的页面；
- CSS / Design Token 变化 → 引用该样式的页面；
- Service / API 变化 → 调用它的前端流程和页面；
- 公共组件变化 → 选择主要消费页面做代表性回归。

如果无法从 Diff 明确映射页面，但存在 UI AC，退化为：目标入口 → 主要导航 → 关键业务链路 → 受影响公共组件的代表页面。不能因此跳过浏览器验证。

## 2. 浏览器验证顺序

1. 固定当前 `change_set_id` 和 AC。
2. 准备测试数据与登录状态。
3. 等待路由、请求、字体、图片和动画稳定。
4. 在声明视口打开每个受影响页面；移动 H5 默认至少覆盖任务声明的 375px 视口。
5. 执行关键交互和完整业务流，而不是只截图首屏。
6. 覆盖任务要求的 normal / loading / empty / error / long-text 等状态。
7. 每次关键交互后检查 Console error、失败请求和横向滚动。
8. 保存 reference / actual / diff（适用时）和视觉报告。
9. 发现交互问题时保存操作前、操作后截图与复现步骤，并至少复现一次。
10. 清理临时登录绕过、Mock 和受控 Temp，再记录 Verification。

## 3. 登录策略

按优先级选择最小侵入方式：

```text
现有测试账号
→ storageState / Cookie
→ 网络 Mock
→ test-only Auth Provider
→ 独立临时 Patch / Worktree
```

不得把永久 `DEV=true`、硬编码 Token 或测试账号密码留在产品代码。若确需临时绕过，Visual Manifest 必须声明 `temporary_bypass_used: true` 并绑定清理 Evidence。

## 4. Evidence 规则

- 静态布局/文案问题：至少一张能看清问题的 actual 截图；
- 交互问题：操作前截图 + 操作后截图 + repro steps；
- 同一问题重复截图不增加置信度，应聚合为一个 issue；
- 每个 Visual Manifest case 必须映射真实 AC、route、viewport、actual 和 report；
- Manifest 必须绑定当前 `change_set_id`；代码变化后旧视觉 PASS 失效；
- reference/diff 声明后必须是真实 `evidence/` 文件；路径不得越界。

## 5. 不能冒充视觉 PASS 的内容

以下内容可以作为辅助静态契约，但不能单独满足 UI Acceptance：

- grep 某个 class/token 是否存在；
- DOM/CSS 字符串是否出现；
- 旧样式是否被删除；
- 组件源码看起来与原型相似；
- AI 仅阅读源码后判断“页面应该没问题”。

页面不可运行、无真实登录态或缺关键测试数据时，保持真实 PENDING/BLOCKED，或由 human_owner 使用既有 defer/waive；不得伪造 PASS。
