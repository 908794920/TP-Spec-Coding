## 为什么改

<!-- 用一两句话说明问题和目标。 -->

## 主要变化

- （请填写）

## 兼容 / 迁移影响

<!-- 没有请写“无”。涉及 Runtime、schema、角色 ID、路径或机器配置时请明确说明。 -->

## 实际验证

按 [`docs/TESTING.md`](../docs/TESTING.md) 选择本次范围；PR / 提交 / 推送不触发全量测试，也不要求重跑已验证且未受影响的内容。

```text
# 请填写实际执行过的命令和结果，不要写“应该通过”。
```

## 检查项

- [ ] 没有提交机器绝对路径、真实 Runtime DB、用户 Registry、私有 Wiki/Knowledge 数据或凭据
- [ ] role ID / Runtime actor 归属没有被目录移动或 Orchestrator 错误改写
- [ ] 已说明当前改动的局部验证结果或未执行原因；本次临时用例与夹具已清理，不要求永久测试文件
- [ ] README / Getting Started 与真实 CLI 行为保持一致（如本次改动影响使用方式）
- [ ] 交付包含本次新增、修改和删除项；涉及 Manifest / Role Catalog 时已同步对应派生物
