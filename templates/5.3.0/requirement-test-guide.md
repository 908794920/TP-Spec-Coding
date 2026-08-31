---
artifact: requirement-test-guide
task_id: ""
artifact_contract:
  version: 5.3.0
---

# Test Guide（按需）

仅在测试步骤复杂、需要跨角色交接、真实页面验证或人工后置验证时创建。

## 前置条件
- 启动命令 / 环境：
- 测试数据：
- 登录策略：测试账号 / storage state / Cookie / Mock / test-only provider / 其他

## 非可视化验证
- 编译 / lint / typecheck：
- unit / integration / API / regression：
- 数据 / 日志 / 权限 / 兼容专项：

## 可视化验证
- Change Set / Diff 影响页面：
- 页面入口 / 路由：
- 参考原型 / 截图：
- 目标视口：
- 浏览器 / 运行环境：
- 关键交互 / 完整业务流：
- 必须覆盖状态：normal / loading / empty / error / long-text
- Console / Network / 横向滚动检查：
- Visual Manifest：`evidence/visual/manifest.json`
- actual / diff / visual report：
- 登录策略回退：测试账号 → storage state/Cookie → Mock → test-only provider → 独立临时 Patch/Worktree
- 登录绕过清理方式与 Evidence（如使用）：

## 回归范围
- 由 Diff/Change Set 影响的页面、接口和相邻行为：
