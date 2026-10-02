---
name: tp-base-project-integration
display_name: 项目接入维护
version: 5.3.7
description: 用于项目 Binding、入口文档同步、Content Systems override 规范化、Runtime root rebind、旧链接处置及明确授权的项目初始化。
---

# 项目接入维护

## 定位

维护项目如何找到 Base、Wiki、Knowledge 和已有 Runtime，不维护业务内容或 Task 生命周期。默认只操作明确的单项目；批量写入需已有授权列出工作区及副作用，不因 Inventory 有记录就自动迁移全部项目。

## 选择动作

1. `base resolve --workspace-root <workspace>`、`base doctor` 确认身份、实际 DB、内容系统项目 scope、Runtime contract 和当前异常。Runtime contract 仍旧时先交 [契约升级迁移](../tp-base-contract-migration/SKILL.md)，不只改 Binding 伪装完成。
2. Binding 需要创建或更新时，先看 `base migration-plan`，再在获准范围执行 `base migrate --apply`。该命令负责 Binding，并包含后续项目同步；`base sync-project` 本身不负责升级 Binding 版本。
3. 现有 Binding 已正确、仅入口文档、portable override 或 machine-local root 漂移时，先 `base sync-project` 查看计划，获准后才 `--apply`。读 [项目接入与可移植性](references/project-integration.md)核对具体写入面及阻塞条件。
4. 只有明确处理旧链接时读 [Junction 处置](references/junction-migration.md)。新 Binding 可解析且 Target 精确一致后，才可使用 `base migrate --apply --remove-legacy-links`；真实目录保留。
5. 确需项目 Runtime 初始化时读 [Project bootstrap](references/project-bootstrap.md)，先 `--check-only`。缺库不表示获准新建，Binding 同步也不包含初始化授权。

## 保留与停止条件

- Binding 保存项目身份和合法语义覆盖；系统根来自 Installation/Resolver。项目 Content Systems 只清理可证明重复的 machine roots，保留真正的项目 override、显式空值及 false。
- AGENTS/README 只替换 Base 托管区，自有区保留原字节；Memory create-once，不重建项目 Skill、测试或经验。精确 `AGENTS.md` 大小写、损坏标记及不可读原件问题按正式计划 BLOCKED，不自动改名或合并。
- `project.root_path` / Registry 属于本机 locator。旧 root 或同身份另一 live workspace 仍存在时停止 rebind；不手改 SQLite，不猜测其他数据库。
- 项目生成物放 `.tp-spec/<feature>/`；短生命周期执行夹具仍放 system Temp。真实 `.tp-spec/docs`、历史 `card/`、tasksHistory 和 evidence 不因升级删除或清洗。

## 复验

重跑目标项目 doctor/resolve，核对 Binding、Runtime、内容 scope 和待同步差异，并按实际变更核验自有区与用户文件。逐文件同步不是全项目事务：`BLOCKED_AFTER_BINDING` 时报告已经提交的变化，只修复具体原因后幂等重试；不覆盖较新的用户事实。已满足的授权不重复询问。
