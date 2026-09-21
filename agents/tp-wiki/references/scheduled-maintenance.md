# Wiki 定时维护

适用条件：由 human_owner 配置的 Wiki Scheduler 唤起维护时读取。


具备命令前置能力的宿主先执行 `wiki maintain`，NO_CHANGE 不唤醒模型；仅 prompt 定时器仍有唤醒成本，必须披露。外部 AI Scheduler 只保存 `automation/wiki/SCHEDULER_BOOTSTRAP.md` 中的短 bootstrap；每次运行读取当前 `automation/wiki/daily-maintenance.md`。canonical protocol 无法读取时停止，禁止凭记忆继续。
