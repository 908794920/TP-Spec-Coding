---
name: tp-autonomy-setup
version: 5.2.3
description: 创建或维护一个长期 Autonomous Maintenance Profile 与隔离 Workspace，并生成可恢复的外部 Scheduler/Executor bootstrap prompt。
---

# tp-autonomy-setup

## 目标
把用户“长期自动维护某个项目/某些 Git Repo”的意图收敛为一个可验证的 Autonomy Profile，并初始化一个物理隔离、长期存在的 Autonomous Workspace。

## 引导顺序
1. 确认 Canonical 大 Workspace 与本次真正允许修改的 Git Repo 范围。只维护 `idc` 就只选 `idc`，不复制整个父 Workspace。
2. 仅当构建/测试真实需要兄弟源码 Repo 时，将其加入 support repos；support 默认只读。
3. 收集长期维护目标，不把宽泛“优化一下”扩展成无边界工作。
4. 选择 `difficulty_ceiling`（L0～L3）。超过上限必须停，不允许伪装降级后继续。
5. 设置 `max_new_tasks_per_cycle`。这是 ceiling，不是 quota；0 个新 Task 完全合法。
6. 选择 Autonomous Workspace 路径。必须与 Canonical 物理分离，不能位于彼此目录树内部。
7. 使用 `tp-spec autonomy profile create ...` 保存到用户目录，再运行 `autonomy doctor`。
8. 运行 `tp-spec autonomy workspace init ...` 创建独立 Git clone 与独立 `.tp-spec` Runtime。
9. 输出并保留 Profile 中的 Scheduler Prompt，同时说明 Executor 必须能访问本地文件、Git、Python/CLI 与 Agent 环境。

## 修改已有 Profile
配置变化必须走正式 Profile CLI/迁移协议；不要直接编辑 YAML。更换隔离路径前先 doctor/review，避免丢失仍待 Integration 的 staging 成果。

## 非目标
不配置 Cron/daemon；不替用户在第三方工具中创建 Scheduler；不创建 Proposal DB；不复制 Wiki/Knowledge 内容。Canonical Wiki/Knowledge 由 Resolver 只读复用。
