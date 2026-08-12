# AI Scheduled Work

本目录保存可版本化、可审查的 canonical AI 自动执行协议。外部 AI 工具 Scheduler 只应保存很短的 bootstrap prompt，并在每次运行时读取这里的当前协议；不要长期复制一份大提示词到各定时器中。

Wiki 使用 `automation/wiki/`；Knowledge 使用 `automation/knowledge/`。两者都采用“短 Scheduler bootstrap → Base 当前 canonical protocol → 确定性 CLI → 必要时 targeted AI update”的模式。

Knowledge 的 Scheduler 执行者是对话模型，不是纯脚本守护进程。外部定时器不应复制整套 Knowledge 维护提示词，也不得在无人值守运行中 AskUserQuestion；歧义、证据冲突或破坏性操作必须 fail-closed 并报告。

Scheduler bootstrap 必须先通过用户 `~/.ai-work/installation.yaml`（或等价已安装命令）解析 physical BaseRoot，再读取 Base 内 canonical protocol；项目 `.ai-work/scripts` Junction 不是运行前提。

- Wiki Scheduler 可以以 Wiki System Root 作为执行锚点，但必须通过 Installation + Workspace Inventory + Repo Registry 逐个解析 Source Workspace；Wiki Root 永远不是 `--workspace-root`。
