# 紧凑 Task 入口与只读终态视图

## 事实与正文各维护一处

`task.md` / 已采用的 `requirement.md` 只在一处 current 区保存有效范围、约束、决定及来源。长需求可单独承载，入口引用它；不得同时维护两份非空 current。进度、步骤、参与、Work 与终态属于 Runtime；AC 和人验/操作声明沿用验收事实。过程按有意义批次记入已有事件/Work，不每次命令生成一组报告。

新模板提供范围、验收、事件和接续导航，不自动替用户整理旧正文。精简已有正文时必须先保存并核对目标，保留被替代历史。终态案例、collected 快照、事件和 terminal manifest 不因减负被修改或删除。

## 生成物不是第二份待办

`generated/continuation.md` 默认显示状态、真实当前步骤/参与、计划版本、等待、下一责任和引用。计划角色不等于已参与；Task 协调责任不等于最后 actor；参与未结束不代表 Agent 在线。未记录时间、角色及下一步保持未知。简短事件摘录有明确提示，全文仍可沿 `events.jsonl` 回溯。

`generated/final-result.md` 默认显示交付、验收/数据库声明、质量/知识/记忆结果与范围历史链接，不复制 current 正文。提炼处置包含来源事件和目标标识；仅展示少量条目时明确总数，全部处置在原 Result 及事件投影中。旧 `NOT_REQUIRED` 不代表做过评估，终态不追补新知识义务。

完成事务将 final-result、显式 COMPLETED 的 continuation 导航、status/events 一起纳入原事务与 terminal manifest。取消事务也同步 CANCELLED 接续；沿用既有取消契约，不声称已经生成完成清单。重复完成不重写视图。生成视图有 `tp-spec.task-view/v1` 标记、Task/状态和原有 source/content 摘要；业务 Subject/验收/证据摘要不因展示瘦身而移除。

## 只读核对与来源边界

```bash
# 无 DB：读取提供的任务归档，不解析 Registry、不初始化或迁移 Runtime。
python -m cli.main projection inspect --task TASK-ID --task-dir <任务目录>

# 有 DB：状态以明确选择的既有 Runtime 为准；文件仍是实时读取。
python -m cli.main projection inspect --task TASK-ID --task-dir <任务目录> --db <既有Runtime.db>
```

结果包括选定入口、状态来源、执行角色、已记录质量、文档新鲜度和历史导航。无 DB 的 `archive.status+last_STATE` 只是来源文件一致性观察，不是已认证人工/Runtime 事实；二者缺失或冲突时返回 UNKNOWN。退出 0 表示完成读取，不表示质量、验收或 Complete 通过；读取问题在 `problems` 和各视图 `status/issues` 中列出。目录/Task 不存在返回非零。

| 视图结果 | 含义 |
|---|---|
| CURRENT | 声明的状态、来源集合及摘要、正文摘要相符；不等于业务语义正确或授权 |
| STALE | 源码工件/投影来源、正文或生成时状态不符；不采用旧接续 |
| MISSING | 没有生成视图；不等于业务未完成 |
| UNKNOWN | 缺状态或必要摘要，不能确认新鲜度 |
| INVALID | 读取/格式或来源身份异常，保留诊断 |

工作台同源展示终态说明和过期原因，默认不读回/展开长正文。所有文档路径相对 Task，复制后在已有本地工具打开；不新增文件执行或工作台写接口。读取是 SQLite 事务加实时文件，不承诺跨介质原子快照。生成失败可表现为 MISSING/STALE，具体错误沿生产命令的 `view_status=PENDING` 及 stderr 查询；不能从缺失文件推断失败发生的原因。

## 修复与保护

在途任务仅派生视图过期，用 `projection rebuild --view-only`；status/events 与账本漂移时先用既有 `reconcile`。这不重新执行 Verify/Review，不产生业务授权，也不修改 current 区的有效需求。正式结果适用性仍由原 Runtime 判断。

COMPLETED/CANCELLED/旧契约终态只提供正确只读解释：生成时 ACTIVE 的旧 continuation 标为过期；最后阶段和 actor 作为历史，不冒充当前责任。`projection rebuild`、`reconcile` 不通过重写原件/重算 hash 让旧终态“变正确”。已提交但尚未清理 journal 的终态，只在文件仍与原 journal target digest 一致时清理该次事务残留；不一致保留恢复依据，不能重新封存掩盖漂移。未提交事务仍按原恢复路径回滚。

本能力不迁移或删除历史案例，不增加工作对象、公共阶段、学习/知识/记忆/归档四套报告，不替任意文字中的旧进度做自动语义纠错。
