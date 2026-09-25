# Task 执行计划、步骤与角色参与

## 适用范围

需求评估之后，由主协调者登记适用步骤；它描述本 Task 接下来实际要做的工作，不生成第二套 Task/Work 账本，不产生实施授权。Task 公共状态仍为 NEW / ACTIVE / BLOCKED / COMPLETED / CANCELLED。步骤、参与和专业门禁是三个不同事实，不能相互代替。

采用新机制的任务使用 `tp-spec.execution/v1` 标记。所有事实仍追加到既有 `task_event.detail_json`，关联既有 `work_item_id`；不新增表、不在只读查询时迁库。普通命令不启动浏览器或 Agent，不执行产品测试、merge、push 或部署。

## 评估后登记计划

正式 Task、Runtime 与实际需求依据已存在后，创建一个紧凑 JSON 输入；此文件是提交载荷，账本才是当前计划的事实源，不要求长期再维护一份计划状态表。未曾发生的评估/步骤不得补造历史起止；前置评估仅通过 `assessment.source_refs` 关联其真实依据。

以下示例是 L0 小改的计划写法，不是任何真实项目的结论。开发内仍包含必要的定向检查；是否省略独立验证/审查步骤，必须先按实际影响判断。

```json
{
  "expected_version": 0,
  "coordinator": {"role": "tp-software-lifecycle", "agent": "main-agent"},
  "assessment": {
    "summary": "范围窄，开发中完成必要定向检查，随后交付收敛。",
    "source_refs": ["requirement.md#current"],
    "omissions": {
      "verification": "必要行为检查在开发中执行，不另设测试步骤。",
      "review": "按实际风险评估无需独立审查步骤。"
    }
  },
  "reason": "记录本任务已完成评估后的适用步骤。",
  "scope_refs": ["task.md#current"],
  "steps": [
    {
      "id": "DEV", "title": "授权开发与定向检查", "phase": "development",
      "roles": ["tp-development-engineer"], "depends_on": [],
      "scope": "已确认需求中指定的变更与检查", "work_item_ids": []
    },
    {
      "id": "DEL", "title": "交付核对与知识记忆提炼", "phase": "delivery",
      "roles": ["tp-integration-engineer"], "depends_on": ["DEV"],
      "scope": "本 Task 已批准范围的结果接收和收敛", "work_item_ids": []
    }
  ]
}
```

```bash
tp-spec work plan --task TASK-ID --file execution-plan.json --db RUNTIME-DB
tp-spec work show --task TASK-ID --db RUNTIME-DB
```

`work plan` 返回真实 `event_id`、`plan_version`、`effective_level` 与是否重放。首次 `expected_version=0`；修改未来步骤时使用 `work show` 的当前版本并说明原因。相同规范化载荷重试复用原记录，不重复版本。版本冲突必须先重读，不能忽略冲突覆盖他人更改。

有效等级复用 risk/flow 与现有风险信号解释。L0–L3 都包含开发、交付收敛；L1 以上包含验证，L2/L3 包含代码审查。L0/L1 对省略的独立验证/审查步骤说明依据；UI/人验等已批准 AC 义务仍保留。验证、审查、交付节点须分别包含测试、代码审查和集成交付角色。其他角色按需参与，可同一步骤有多个角色，不按等级机械增加所有阶段。

步骤数组是明确的父步骤顺序；`depends_on` 只引用前面的实际 step ID，不是通用并发流程引擎。Work 并发仍由既有 Work 与宿主安排。步骤 ID 不从标题/Wxx 名称猜测。`work_item_ids` 只允许本 Task 已存在的 WorkItem；计划后创建的新 Work 也可通过[Work 结果契约](WORK_UNITS.md)显式绑定该步骤，不重写已开始步骤定义。开始参与时 `--item` 必须属于上述可信关联。

`scope_refs` 与 `assessment.source_refs` 是可追溯定位，不是人类批准。`event:123` 会校验事件属于本 Task；其他文件/片段引用保留原值，不谎称已核验内容、范围或证据适用性。计划的 `effect_scope=record_only`，所有实际动作仍受既有 Execution Envelope 和当次批准限制。

开始过的步骤定义、位置和完成历史不能由计划修订重写；仅调整未来部分。风险/范围后续变化时先复核未来义务并修订，保留旧登记等级及依据，不倒填当年的计划。采用新计划不自动读取旧摘要来补完成；旧任务的可复用真实成果应由本次接收/核对步骤引用，不伪造过去的阶段。

## 实际边界与独立参与

计划登记不激活 Task。正式需求/开发事实依旧通过既有 checkpoint 等入口记录；不得为了使状态变绿创建假的 checkpoint。开始某步骤时：

```bash
tp-spec work start --task TASK-ID --step DEV --plan-version 1 --role tp-development-engineer --agent dev-a --scope "本次具体文件与动作" --summary "实际开始授权处理" --db RUNTIME-DB
```

返回 `session_id` / `participation_id`（同一个真实 ID）。步骤仍是计划态且前面步骤已完成时，这次 start 在同一事务登记步骤开始和参与开始；不写一半。也可由协调者先显式 `work step --action start` 再开始角色参与。下一步骤不能越过未完成步骤；Task 已 BLOCKED 时不开始新步骤/参与或恢复执行。

一个角色可在同一步骤由不同实际执行者或不同 Work 分别参与；相同 role/agent/step/Work 的未结束参与不重复开始，使用其现有 ID 恢复或结束。角色不是 Agent 进程，也不等于强隔离。协调责任由计划中的 coordinator 独立保存，checkpoint/验证/交付等事件只记录自己的 actor，不覆盖 Task owner。

下面的 `WORK-ID` 必须换成真实回执 ID，不可编造：

```bash
tp-spec work update --task TASK-ID --session WORK-ID --action wait --summary "等待所需反馈" --wait-reason "相关结果未到" --expected-next tp-test-engineer --finding "有证据的发现" --evidence task.md --db RUNTIME-DB
tp-spec work step --task TASK-ID --step DEV --plan-version 1 --action wait --summary "当前步骤等待" --wait-reason "相关结果未到" --expected-next tp-test-engineer --db RUNTIME-DB
tp-spec work step --task TASK-ID --step DEV --plan-version 1 --action resume --summary "条件满足，恢复本步骤" --db RUNTIME-DB
tp-spec work update --task TASK-ID --session WORK-ID --action resume --summary "恢复同一次参与" --db RUNTIME-DB
tp-spec work end --task TASK-ID --session WORK-ID --reason completed --summary "本次实际处理完成" --result "真实结果与范围" --evidence task.md --db RUNTIME-DB
tp-spec work step --task TASK-ID --step DEV --plan-version 1 --action complete --summary "已接收本步骤各参与结果" --db RUNTIME-DB
```

参与等待与整个步骤等待分别表达，不因一个参与者等待就推断所有人停止。普通父参与在 WAITING 时须先恢复父步骤；已认领且绑定当前步骤的 Fix 参与可在父等待时开始/恢复，以免等待形成循环。真实 Task BLOCKED 仍需原有解除条件与正式入口。`--waiting-item` 可关联本 Task 的等待 Work；该参数不创建或完成 Work。

`work end --reason handed_off` 须写下一责任；`waiting_human` / `waiting_agent` / `blocked` 须写等待原因及下一责任。`--finding`、`--decision`、`--evidence` 可重复；决定记录不是人工授权。完成时清除旧“当前等待”，早先发现/等待仍留在该参与历史里。

结束一条参与不自动完成步骤；协调者确认并接收所有必要结果后记录步骤完成。仍有未结束参与时拒绝步骤完成。结束后的参与不重开，下一次真实参与产生新身份；同一个未结束参与等待/恢复保留原身份。计划后续修订不改变老参与的开始版本，结束仍绑定原 START、角色、执行者、步骤及 Work。

所有新计划/步骤/参与命令返回 JSON；未采用计划的旧式 `work start/end` 保留原文字成功回执。写入前置错误非零退出且事务不留部分边界；故障后先 `work show` 核对，不盲目补写。计划与 Work 创建/结果/接收/候选的相同有效载荷重放按各自契约处理；步骤和参与边界不猜测两次同摘要是否同一操作。

## 同源查询与结单边界

`work show` 在只读事务输出计划历史、当前/下一步、参与详情及完整执行边界。报告与 `workflow next --json` 的 `context.execution` 复用同一解释。角色实际起止只来自正式事件时间；未结束、时间损坏或无时区就不计算跨度。跨度含等待，不代表模型计算时间；未结束记录始终不证明在线。

工作台沿用现有 Task GET 接口，`workflow.execution` 给出完整关联；步骤与角色详情、筛选以及终态解释见 [工作台操作](WORKBENCH.md)。新事件在 `events.jsonl` 派生投影仍映射为 `FACT`，原 `event_type` 和绑定留在 detail，不扩充第二套状态枚举。`work` 命令只写正式账本；普通 checkpoint/受支持投影入口随后生成文件视图，恢复时以账本而非旧文件缓存为准。

已采用计划的 Task 结单预检/complete 检查未完成步骤和未结束参与；这是记录完整性，不能用 `step complete` 代签 Verification、Review、Owner Acceptance 或 Delivery。既有专业门禁路由仍独立有效，不因为步骤已完成就放行。Fix 创建/回收、父流程前向接续和实际集成候选使用[Work 结果契约](WORK_UNITS.md)。当前父步骤与需要补做的专业操作分开，候选和步骤完成都不代替上述门禁。

## 旧记录、终态与回滚

没有显式计划的任务不追补新义务，也不自动绑定旧 Work Session 到猜测的步骤。旧式未结束工作段仍按原唯一角色/执行者规则选择；显式 `--session` 后另传的角色/执行者必须与 START 一致。明确已知结束且原 ownership/授权成立时，旧式工作段保留终态补记 END 的原恢复路径，不重开 Task、不修改 WorkItem，也不补造过去结束时间。不能只因“很久没活动”就代记结束。

新显式计划的终态或退休步骤/参与只读，当前/下一步骤、当前角色均为空。历史未结束记录如实保留；不为显示整齐改写已完成任务。错误的新增格式或身份绑定返回可见问题，不静默降级为旧记录。未结束历史、主体新鲜度、事实来源与操作权限分别判断；本地 actor 字符串不是防篡改身份认证。

本接口不升级物理 DB schema。仅源码回滚无需删除新事件；旧代码不会理解新步骤完整性/协调语义，因此已采用新计划的在途任务不应在旧版继续写入。需回退时先按原流程停止受影响写入、保留数据库备份，由有权限者选择恢复同一一致快照或继续新代码；不能删除事件或重算哈希伪造未采用记录。

## 安全行为与步骤范围

步骤可按实际需要增加 `effect_scope`、`security_changes`、`paths`、`ac_refs`，Work 复用原路径/AC 并登记对应效果。细则与例子集中在 [Security Change Authority](security-change-authority.md)，不从 scope 文本、角色或 Work 名称推断批准；未批准的实施入口暂停，调查/无关工作可继续。已开始步骤仍保持不可改写的历史；继续实施时重查当前决定。
