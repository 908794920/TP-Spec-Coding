## 为什么改

<!-- 用一两句话说明问题和目标。 -->

## 主要变化

- （请填写）

## 兼容 / 迁移影响

<!-- 没有请写“无”。涉及 Runtime、schema、角色 ID、路径或机器配置时请明确说明。 -->

## 实际验证

```text
# 请填写实际执行过的命令和结果，不要写“应该通过”。
```

## 检查项

- [ ] 没有提交机器绝对路径、真实 Runtime DB、用户 Registry、私有 Wiki/Knowledge 数据或凭据
- [ ] role ID / Runtime actor 归属没有被目录移动或 Orchestrator 错误改写
- [ ] 新行为有对应测试或可重复验证证据
- [ ] README / Getting Started 与真实 CLI 行为保持一致（如本次改动影响使用方式）
- [ ] 发布候选已使用 `git add -A` 纳入所有新增文件，并通过 `python scripts/update_manifest.py --verify-release`
