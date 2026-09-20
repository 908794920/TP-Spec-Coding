# Contributing to TP-Spec-Coding

感谢你愿意改进 TP-Spec-Coding。

## 适合直接提交的改动

- Bug 修复；
- 当前功能的必要验证与缺陷复现；
- 文档、示例和兼容性修复；
- 不改变公开契约的小型可维护性改进。

较大的行为变化、Runtime/schema 变化、角色职责调整或新工作流，请先在 Issue 中说明：目标、使用场景、兼容影响和验证方式，再开始大范围实现。

## 开发环境与验证范围

```bash
python -m pip install -r requirements.txt
```

本仓库唯一的现行验证说明是 [`docs/TESTING.md`](docs/TESTING.md)。根据当前 diff、调用方和验收要求选择局部检查；必要临时单测在隔离目录执行，结束后清理代码与夹具，仅记录实际结果和未执行项。读取文档不运行产品测试。

不恢复历史测试目录、分类 catalog 或自动全量 CI，也不通过“发布前保险”、Reviewer 建议或通用 Skill 自动扩大范围。普通 commit、push、PR、批次结束与交付不追加测试；缺少永久测试文件本身不是拒绝提交或交付的理由。

## 源码与交付一致性

按本次授权提交或制作 Patch，完整包含新增、修改和删除项；不要把用户其他未提交改动一并纳入。实际修改角色文档时同步 Role Catalog，源码交付范围变化时同步 Manifest，按需使用现有生成工具核对对应内容，不机械执行全部维护脚本。

`manifest.sha256` 的开发模式覆盖 Git 可见工作树；正式 Git 发布面仍使用已暂存的源码集合核对，不能把未入库文件当作已交付。`update_manifest.py --verify-release` 只校验文件身份，不运行测试，也不签发产品验收通过。

本地合并、真实任务体验、commit/push 和正式发布分别报告；Tag/Release 由发布所有者明确决定，不从局部检查或 Patch 交付推导发布授权。

## 设计边界

贡献请保持这些不变量：

- Workflow 决定什么时候调用，Skill 决定怎么执行，Runtime 记录事实；
- `tp-workflow-orchestrator` 不代理专业角色写业务事实；
- role ID 是持久化身份，不与物理目录绑定；
- SQLite 是 Runtime 权威账本，投影不能反向伪造事实；
- 真实 blocker / 高风险授权 fail-closed；
- 不为了“流程完整”制造空工件；
- 不把个人机器绝对路径、用户 registry、Runtime DB、Wiki/Knowledge 私有数据提交到公共仓库。

## 新 Agent / Skill

`agents/` 用于用户可以直接选择的专业入口；`skills/` 用于 Agent 内部可组合能力。

新 Agent 应说明：

- 唯一职责；
- 不负责什么；
- 输入 / 输出；
- 是否拥有 Runtime actor 身份；
- 与已有 Agent / Skill 的依赖关系；
- 可测试的安全边界。

## AI 生成代码

AI 辅助贡献是允许的，但提交者仍对代码、实际验证结果、许可证和安全性负责。建议在 PR 中说明使用的 AI 工具，以及哪些关键结论经过了人工或独立验证。

## Commit / PR

推荐使用简洁的 Conventional Commit 风格，例如：

```text
fix(runtime): preserve professional actor provenance
feat(agent): add documentation specialist
Docs: improve clean-machine onboarding
```

PR 请包含：

- 为什么改；
- 主要行为变化；
- 兼容/迁移影响；
- 实际执行过的局部验证命令、结果及临时材料清理情况；
- 未验证或仍有风险的部分。

提交代码即表示你同意你的贡献按本仓库的 MIT License 发布。
