# 视频制作领域

<!-- TP-SPEC:AGENT-TOPOLOGY-BEGIN -->
<!-- 由 scripts/check_document_navigation.py --write 根据 governance/role-catalog.yaml 生成。不要手工编辑本区块。 -->

- **Agent**：tp-视频制作 · `tp-video-production`
- **执行契约**：[`agents/tp-video-production/SKILL.md`](../../agents/tp-video-production/SKILL.md)
- **能力 ID**：`video.routing`、`video.workflow`

<!-- TP-SPEC:AGENT-TOPOLOGY-END -->

默认入口把明确的视频制作请求转交 `tp-video-production`。范围明确的单项制作可直接使用角色方法。需要跟踪正式制作时，使用现有项目 Runtime 创建 `video` Task，并通过 `workflow next` 恢复。视频工作区可以没有 Git。

```powershell
tp-spec route --text "制作一支知识讲解视频" --json
tp-spec skill read --id tp-video-production --json
tp-spec task create --id TASK-VIDEO-01 --project <项目> --domain video --scaffold
tp-spec workflow next --task TASK-VIDEO-01 --json
```

简报写入 Task 的当前区或引用现有真实简报。使用实际验收项填充 `acceptance.md`。视频计划使用原有 `work plan --file` 和版本控制，角色、步骤和依赖按交付需要填写。阶段可用 `intake`、`creative`、`asset_production`、`post_production`、`media_quality`、`delivery`。交付由制片负责，独立声音步骤按需安排。视频不填软件等级、模式或软件省略理由。

同一时间线由约定的剪辑负责人写入。可并行的镜头和声音使用不同的实际范围并登记相应 Work。Work spec 使用工作区相对的 `media_root` 及该根下的 `paths`。通过既有 `workitem claim/complete/receive` 报告和接收真实结果。结果 JSON 使用 `summary`、`changed_paths`、`evidence_refs`，默认工件类型为 `media`。记录会计算实际文件大小和 SHA-256，并以 `complete` 回执中的 `event_id` 作为接收输入。`receive` 回执中的 `event_id` 供导出清单引用。返修用 `rework fix` 挂回原步骤。

## 当前导出与审看

在 Task 的 `evidence/` 下保存小型 JSON 清单，媒体保留在已登记工作区的媒体根。下例中的路径相对该根，收据 ID 指向同一 Task 精确接收事件。无需从 Work 取得的复用资产可以保留版本和路径，省略 `work_item`。

```json
{
  "version": "cut-a",
  "media_root": "media",
  "main": "exports/cut-a.mp4",
  "attachments": ["exports/cut-a.srt"],
  "selected": [
    {"path": "shots/shot-01.mp4", "role": "picture", "version": "s01-v2", "work_item": "TASK-VIDEO-01-W01"}
  ],
  "receipts": {"TASK-VIDEO-01-W01": 23},
  "affected": ["visual", "shot-01", "00:00–00:08"],
  "required_checks": ["technical", "visual", "captions"],
  "independent_review_required": false
}
```

完成质检步骤的返修时，每项 Fix 的复验范围来自与其精确收据关联的选用资产，或来自 `affected` 中对本次导出全部返修实际影响的声明。用 `audio`、`visual` 或适用的自定义检查标识表达影响，镜头号和时间码用于定位。自定义检查标识在 `affected` 或选用资产角色中声明，并列入 `required_checks`。旧清单缺少可识别范围时，登记新导出补充 `affected`，可沿用未改的媒体文件和有效素材收据。以新导出事件为主体重新登记适用检查，音频和画面可分次记录 PASS。

用 `task checkpoint --phase post_production --actor tp-video-editor --media-manifest evidence/export.json` 登记导出，保留返回的 `event_id`。需要对当前导出登记检查时，用 `task verify --media-qc evidence/qc.json --media-export-event <实际审看的导出事件>`，同时提供实际角色、结论和摘要。QC JSON 中 `kind` 可为 `technical`、`self` 或 `independent`，`coverage` 使用适用检查标识。用 `unchecked` 写明缺失的播放或听音覆盖，用 `findings` 定位实际问题，用 `source_refs` 引用可适用的既有检查。要求独立审看时应记录真实独立工作段和执行者，使用 `--media-agent` 区分其身份与制作人员。各次检查仅绑定实际审看的版本。

用户接受使用 `task acceptance-override --mode accept --actor human_owner --ac <实际覆盖AC> --source <用户实际决定> --media-export-event <用户实际审看的导出事件> --request-id <同一逻辑请求标识>`。可以先记录接受，再收敛 READY。导出已经换版时，首次登记会拒绝对旧版本的接受。相同请求重放原回执。新版本或实质验收范围变化会使旧接受不再适用。

制片通过 `task delivery-converge --delivery-status READY` 收敛当前事实，用 `task complete --check` 读取缺项，已满足时通过 `task complete` 结单。上述任务命令沿用 `--task`、`--task-dir` 及所需摘要或原因等现有参数。需要重试同一导出、检查或交付记录时复用 `--request-id`。

缺工具或生成失败时保留真实待执行材料与恢复条件。费用、上传或发布需要实际动作的明确授权。可用 `task block --kind permission` 记录等待，`workflow confirm` 记录对应的真实决定来源，再由有权者恢复。工作台只读显示计划、参与者、当前登记媒体及缺项。需要重新读取文件内容和受信验收时使用正式预检。
