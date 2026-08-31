# Knowledge 对话模型定时维护

适用条件：由 human_owner 配置的 Knowledge Scheduler 唤起维护时读取。


Knowledge 定时器的执行者是**对话模型**，不是单纯脚本。Scheduler 只保存短 bootstrap；每次唤起后：

1. 解析当前 Base/Knowledge；
2. 读取 `automation/knowledge/daily-maintenance.md` 当前 canonical protocol；
3. 通过 Knowledge CLI 获取 deterministic facts；
4. 只在有明确证据/范围时做 targeted AI UPDATE；
5. 不得使用 AskUserQuestion；需要人工决策则记录 `NEEDS_REVIEW`，保持旧 baseline；
6. 输出简洁日报：变化、自动动作、质量结果、未处理阻塞。

定时器本身不得复制整套维护提示词，否则 Base 升级后会产生双权威。
