# 任务模板版本目录

公共基座只保留唯一活动契约的模板版本。历史模板由 Git release 分支承担；历史终态/已退役任务保留自身工件只读归档，不需要公共模板副本。旧契约在途任务不自动变成归档，需要继续执行时走既有显式迁移入口：

| 任务版本 | 模板目录 | 状态 | 说明 |
|---|---|---|---|
| `5.3.5` | `5.3.5/` | **唯一活动契约** | 文档口径纠偏与用户级外部 SKILL 接入；沿用既有 Runtime 状态、事件和显式迁移机制，不因读取外部能力改写项目或任务。历史终态保持只读，在途任务按授权显式迁移。受控 YAML（`cli/config_loader.py`）仍按当前契约全量精确匹配。 |

创建新任务时必须写入 `base_version: 5.3.5` 与 `artifact_contract.version: 5.3.5`。模板目录迁移不改变已创建任务的工件路径。`Test-TpSpecTask.ps1` 的活动契约检查拒绝旧版本，不等于删除旧任务或否定历史证据；在途任务按 [Getting Started](../docs/GETTING_STARTED.md#跨版本更新至当前契约) 的项目/任务显式迁移步骤处理，终态及已退役任务不迁移。

## Pre-task intake 使用

需求分析可以早于正式 Task。需要 pre-task 工件时，可复制当前版本的 `requirement.md` / `requirement-clarifications.md` / `requirement-decisions.md` 到 intake/preliminary 目录，保持 `task_id: ""`，不得为了填 TaskId 提前创建任务。阻塞清零后由 `tp-spec task create --from-intake <DIR>` 统一建立正式 Task、绑定 TaskId/当前契约并记录 provenance。
