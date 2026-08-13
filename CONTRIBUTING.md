# Contributing to TP-Spec-Coding

感谢你愿意改进 TP-Spec-Coding。

## 适合直接提交的改动

- Bug 修复；
- 测试补强；
- 文档、示例和兼容性修复；
- 不改变公开契约的小型可维护性改进。

较大的行为变化、Runtime/schema 变化、角色职责调整或新工作流，请先在 Issue 中说明：目标、使用场景、兼容影响和验证方式，再开始大范围实现。

## 开发环境

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

提交前至少运行：

```bash
python -m pytest -q
python scripts/check_version_consistency.py
python scripts/update_role_catalog.py --verify
python scripts/check_portability.py
python scripts/update_manifest.py --verify
```

Windows 环境再运行：

```powershell
pwsh -File scripts/ci/Test-TpSpecBase.ps1 -Mode Full
```

## 正式发布检查

普通开发允许 `manifest.sha256` 临时覆盖尚未 `git add` 的可见文件，方便 Patch 在提交前验证；**正式发布不允许这样做**。发布候选必须以 Git index 为准，确保 GitHub 最终能拿到本机测试过的全部文件。

```bash
# 必须使用 -A，避免漏掉 .github/ 这类点目录或删除项
git add -A

python scripts/update_manifest.py --verify-release
```

Windows 发布候选再运行完整门禁：

```powershell
pwsh -File scripts/ci/Test-TpSpecBase.ps1 -Mode Full
```

只有 Linux / Windows CI 均通过后，才创建对应 **Git Tag** 和 **GitHub Release**。Tag 指向的提交必须就是完成上述 Release Gate 的提交；不要先打 Tag 再补文件。

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

AI 辅助贡献是允许的，但提交者仍对代码、测试、许可证和安全性负责。建议在 PR 中说明使用的 AI 工具，以及哪些关键结论经过了人工或独立验证。

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
- 实际执行过的测试命令；
- 未验证或仍有风险的部分。

提交代码即表示你同意你的贡献按本仓库的 MIT License 发布。
