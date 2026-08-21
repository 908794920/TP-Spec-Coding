# 任务模板版本目录

公共基座只保留唯一活动契约的模板版本。历史版本由 Git release 分支承担；更早版本的历史任务继续按其任务目录内已有工件只读归档，运行时不再解析，也不需要公共模板副本：

| 任务版本 | 模板目录 | 状态 | 说明 |
|---|---|---|---|
| `5.2.6` | `5.2.6/` | **唯一活动契约** | V5.2.6 正式角色化软件工程体系升级版：在上一版本工程化加固基座上新增结构化引用、无损可回溯摘要、溯源 Schema、归档报告、Cutover 机制、审查预检与 S1 声明拒绝校验器。运行时 YAML 经受控加载模块（`cli/config_loader.py`）解析，版本门控为全量精确匹配。 |

创建新任务时必须写入 `base_version: 5.2.6` 与 `artifact_contract.version: 5.2.6`。模板删减不改变已创建任务目录中的工件路径；历史版本契约（含上一版本）的任务为静态归档，由 Git release 分支承担，`Test-TpSpecTask.ps1` 对其一致拒绝解析。

## Pre-task intake 使用

需求分析可以早于正式 Task。需要 pre-task 工件时，可复制当前版本的 `requirement-knowledge.md` / `requirement-clarifications.md` / `requirement-decisions.md` 到 intake/preliminary 目录，保持 `task_id: ""`，不得为了填 TaskId 提前创建任务。阻塞清零后由 `tp-spec task create --from-intake <DIR>` 统一建立正式 Task、绑定 TaskId/当前契约并记录 provenance。
