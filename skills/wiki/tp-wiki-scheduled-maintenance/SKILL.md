---
name: tp-wiki-scheduled-maintenance
display_name: Wiki 定时维护
version: 5.3.6
description: 用于 human_owner 已配置的 Wiki Scheduler 唤起维护；读取当前短 bootstrap 与 canonical daily protocol，保留零变化快路径，不自行创建或扩大定时任务。
---

# Wiki 定时维护

## 调用边界

仅承接 human_owner 已配置的 Wiki automation 及其明确 registry/repo 范围；有此 SKILL 不等于已授权创建、启用或扩大定时任务。普通研发不因此多一个 Task Gate，也不产生 Task 状态、交接或结单。

## 当前协议

外部 AI Scheduler 只保存 [SCHEDULER_BOOTSTRAP](../../../automation/wiki/SCHEDULER_BOOTSTRAP.md) 中的短 bootstrap，每次实际运行读取当前 [daily-maintenance](../../../automation/wiki/daily-maintenance.md)。canonical protocol 无法读取就停止，不凭记忆或旧 prompt 继续。

具备命令前置能力的宿主先运行正式 `wiki maintain`；`NO_CHANGE` 不唤醒模型。仅 prompt 定时器仍有唤醒成本，必须披露。日常协议可按 registry 顺序维护多个 repo，首次构建/全量重建仍限单 repo 并按专属能力处理。

有真实变化才按当前协议接续[增量维护](../tp-wiki-maintenance/SKILL.md)及必要审计；来源、scope、写入根、质量门和 baseline 条件全部保留，自动唤起不扩展权限。需要新增范围、人类决策或缺失来源时报告并停止依赖动作。

## 结果

沿 canonical protocol 汇总真实 NO_CHANGE、更新、审计、baseline 和失败信息；不把排程存在当作维护成功，不把一次摘要当作全仓 PASS，不承诺未实际建立的后续运行。
