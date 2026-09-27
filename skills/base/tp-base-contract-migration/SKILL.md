---
name: tp-base-contract-migration
display_name: 契约升级迁移
version: 5.3.5
description: 用于 Base 升级后的 Project/Task contract 不一致、显式迁移计划、备份及迁移复验；模板同步不构成 Runtime 或任务迁移授权。
---

# 契约升级迁移

## 输入与边界

先用 Resolver 确定项目身份、DB 和任务目录，区分软件 VERSION、执行 Base、Binding、Project contract 与每个 Task contract。保留既有维护授权；只有对象、备份或写入窗口尚未覆盖时补充确认，不把 `--actor human_owner` 当授权来源。

## 迁移闭环

1. 按 [兼容与迁移操作](references/contract-migration.md)运行只读 `task migration-plan --project <PROJECT> --db <DB> --tasks-root <ROOT> --gate` 和 `project upgrade-contract --dry-run`。检查支持范围、schema、任务状态及具体工件差异，不凭同主版本推断兼容。
2. 确认本次明确对象与维护窗口，暂停相关写入，对所选 DB 和 Task 目录建立一致备份。存在 WAL 时使用可靠的 SQLite 一致备份或停止连接后的完整状态备份；同时保留将更新的配置、入口和本机登记，按实际计划选择范围。
3. 正式 `project upgrade-contract` 只切 Project contract；仅对明确获准的在途 Task 执行 `task migrate`，不迁移终态/退休档案、不重绑旧 PASS。不直接编辑版本字段、DB、events 或 generated。
4. Binding 版本仍旧时，交 [项目接入维护](../tp-base-project-integration/SKILL.md)执行 `base migrate --apply`；无需重复切 Project。模板同步用 `sync-project`，不将其成功当作 Binding 已升级。
5. 对同一对象复验 doctor、Task migration gate、SQLite 完整性及变化边界；允许正式 Project 版本/时间和升级审计变化，任务历史及非目标数据应保留。部分成功或失败按实际结果报告，用正式 reconcile/缓存恢复入口处理。
6. 本次涉及运行中的工作台时，交 [工作台维护](../tp-base-workbench/SKILL.md)核对并在授权内重启，分别验证接口和实际页面。磁盘 VERSION 或顶部版本文字不能单独证明旧模块已退出。

## 交付与备份

报告迁移前后版本、实际迁移对象、未迁移对象、复验和恢复条件。备份默认按既有保留约定处置；用户明确要求成功后删除时，先确认全部适用验证通过，再核对本次备份绝对路径和归属后仅清理该备份。删除被环境拒绝就保留并说明，不能绕过限制；不删除原始项目状态或历史证据。

已有新事实时不得直接用旧备份覆盖回退；迁移失败后先确定已提交部分及最新状态。
