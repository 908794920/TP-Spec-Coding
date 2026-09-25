# Work 结果、Fix 接续与 Task 集成候选

## 适用边界

本接口补充[具体执行计划](EXECUTION_FACTS.md)，继续使用 `work_item` 和 `task_event`，不新增表、公共 Task 状态或第二套工作账本。新 Work 由 `tp-spec.work-unit/v1` 识别，不凭版本字符串相同推断已采用。Wxx/FIXxx 只是建议命名；父 Task、步骤和同一问题分别显式绑定。

主协调者与执行者分开：计划中的 coordinator 登记范围、接收精确结果、记录实际集成候选；认领者提交结果。角色字符串、agent 标识和工作区路径只校验记录一致性，不认证人工身份、不证明进程在线或宿主强隔离。真实执行仍遵守 Task 授权、宿主工具权限与 [Security Change Authority](security-change-authority.md)。这些命令不运行测试、启动 Agent、应用 Patch、commit、merge、push、删除工作区或关闭父 Task。

## 登记范围与依赖

下例是输入结构，不是实际需求、授权或已发生事实。先有父 Task、有效执行计划和真实来源文件；路径均为项目相对路径，Task ID / Work ID / 步骤需替换为现场真实值。

```json
{
  "step_id": "DEV",
  "scope": "已批准范围中的具体结果，不包括周边增强",
  "scope_refs": ["task.md#current"],
  "roles": ["tp-development-engineer"],
  "paths": ["src/example.py"],
  "ac_refs": ["AC-01"],
  "depends_on": [],
  "isolation": {"mode": "sequential"}
}
```

```bash
tp-spec workitem create --task TASK-ID --id TASK-ID-W01 --file work-spec.json --role tp-software-lifecycle --agent main-agent --db RUNTIME-DB
tp-spec workitem claim --task TASK-ID --id TASK-ID-W01 --role tp-development-engineer --agent dev-a --db RUNTIME-DB
```

`--file` 是一次提交载荷，不需另建长期状态文档。不能再用 `--paths/--depends/--acceptance/--security-change/--effect-scope` 维护另一套范围；JSON 模式把安全效果和提案写入同一 `security_context`。实施路径支持明确文件或 glob；父步骤有显式 paths/AC 时不得越过其边界。普通 Work 的角色取自父步骤；Fix 可登记完成分析、修复、复验所需的已注册角色。AC 必须在当前 Task 矩阵中存在。来源文件须可读，`event:<ID>` 必须属于本 Task；文件片段仅作导航，不证明自然语言的全部范围和授权。

依赖只指向本 Task 已登记 Work，不能自依赖或跨 Task；认领、提交及接收时重查。新契约依赖需要结果已提交且已由协调者接收，单独 `COMPLETED` 不够。既有未采用结果契约的依赖保留原完成语义。主协调者仍判断真实依赖、隔离与业务边界；程序不从路径证明任意 Diff 的全部语义。

`repo_root` 可显式指定实际结果工作区，`target_root` 指向父 Task 已登记的集成仓库；省略时使用当前项目根。源码包不固化机器绝对路径，实际路径只存入该机器 Runtime。默认同一工作区顺序认领；`isolation={"mode":"declared","reference":"真实宿主/工作区依据"}` 只是声明，同根重叠路径仍需串行。不同根是否真的隔离由宿主和操作者核实。`shared_paths` 可登记允许范围内的路径到写入 Work ID 的映射，非所有者不能将该路径作为自己的变更输出。

`security_context` 可提供 `effect_scope` 和 `security_changes`；不提供时仍检查现有相关提案。调查 Work 使用 `read_only/isolated_poc/record_only`，不能提交产品变更路径冒充修复。依赖检查、正常权限检查和人类批准各自独立，不借 Fix 名称绕过。

## 提交实际结果与协调接收

```json
{
  "summary": "实际完成内容及定向验证结论",
  "changed_paths": ["src/example.py"],
  "artifact": {"kind": "snapshot"},
  "evidence_refs": ["evidence/targeted-check.txt"],
  "limitations": ["实际未验证的环境或边界；没有则为空数组"]
}
```

```bash
tp-spec workitem complete --task TASK-ID --id TASK-ID-W01 --role tp-development-engineer --agent dev-a --result work-result.json --db RUNTIME-DB
tp-spec workitem list --task TASK-ID --json --db RUNTIME-DB
tp-spec workitem receive --task TASK-ID --id TASK-ID-W01 --result-event 123 --role tp-software-lifecycle --agent main-agent --summary "已比对该结果与实际证据，尚未代替整任务验收" --db RUNTIME-DB
```

`123` 必须换成上一步返回的真实结果事件 ID。完成要求 Work 已认领、身份相同、关联工作段已结束；角色工作段的开始/等待/结束仍用原 `work start/update/end --item`，不让 Work 状态代替角色参与。

结果载体有三种：`snapshot` 读取声明的精确输出路径及内容摘要；`patch` 另提供 Task `evidence/` 下真实 Patch 的 `ref`，校验文件摘要、Git Patch 路径与声明输出，不执行应用；`commit` 的 `ref` 必须解析到实际结果仓库当前 HEAD，所声明路径没有未提交变化。无需每个 Work 都 commit。文件删除按真实不存在记录；不存在的输出不能被描述成新建文件。Patch 校验不证明它可在任意目标版本成功应用，仍由集成者在获准范围实际核对。

只读检查/方法 Work 可用 `changed_paths=[]`，但仍有真实结果与证据。接收会核对精确结果、来源工作区字节和证据是否仍匹配；后续其他 Work 改动同一工作区前应先接收前一结果。已接收记录保留当时的结果，最终核对以实际集成主体为准，不要求源工作区永远冻结。证据本身后续改变仍使绑定失效。

提交将该 Work 行标为 `COMPLETED`，**不等于已接收、已集成、父步骤完成、Task 验收通过或 Agent 仍在线**。相同创建载荷、同认领者重复认领、相同结果、同精确接收和同集成输入重放不会新增相同事实；输入变了不假装幂等。并发冲突返回错误或要求重读，不覆盖别人认领。

## 父流程前向与同一 Fix 重试

测试、审查或交付发现当前范围内缺陷后，使用父 Task 当前 step；不用旧 `rework open` 将显式计划退回开发。

```bash
tp-spec rework fix --task TASK-ID --id TASK-ID-FIX01 --issue issue-zero-boundary --step TEST --file fix-spec.json --summary "已复现的原范围缺陷" --cause IMPLEMENTATION_DEFECT --role tp-software-lifecycle --agent main-agent --db RUNTIME-DB
```

`fix-spec.json` 与 Work spec 同结构，`step_id=TEST`，明确本次修复路径/AC、来源和实际角色。当前父步骤转 WAITING，已完成开发历史不变。重复同 issue 和相同范围复用原 Work；改变 issue 名称不是扩范围授权，需求变化仍先走原授权流程。没有 Fix 内再创建 Fix 的对象层，不递归制造任务。

父步骤等待时，该 Fix 的已认领角色仍可开始/恢复工作段；父 Task 真正 BLOCKED 时原等待边界不解除。普通父工作若占用顺序工作区，应由其真实执行者结束/交接工作段并释放，不能假称后台进程已经停止。

失败释放需要原因与恢复条件；先结束该 Work 仍未结束的参与：

```bash
tp-spec workitem release --task TASK-ID --id TASK-ID-FIX01 --role tp-development-engineer --agent dev-a --reason "本次实际失败原因" --recovery "可以重试所需条件" --db RUNTIME-DB
```

释放回 PENDING，下一次 claim 增加尝试次数，保留旧结果与失败历史。已提交甚至已接收结果需再处理同一问题时，由协调者 `workitem retry --id ... --step 当前步骤 --reason ... --recovery ... --role ... --agent ...` 复用身份；新结果不沿用旧接收。Fix 可在更后的当前步骤重新接续，原步骤关联与完成时间保留，不能重开已完成父步骤。普通 Work 不允许通过 retry 迁往另一父步骤；应创建有依据的 Fix。

`workflow next --json` 保留当前父 phase，实际需要补做的专业操作在 `context.operation_stage`。`rework_fix/workitem_resolve/workitem_candidate_then_resume` 是协调提示，不是自动派发、更高权限或已完成。Work 的结束/接收都不自动恢复或完成父步骤。

## 固定集成主体与原步骤复验

先在当次授权内由协调者实际应用结果/处理冲突，再记录真实 Task 工作区。只登记，不执行合并：

```json
{
  "summary": "实际集成范围及已比对的结果",
  "evidence_refs": ["evidence/integration-check.txt"],
  "resolutions": []
}
```

```bash
tp-spec workitem candidate --task TASK-ID --file integration.json --role tp-software-lifecycle --agent main-agent --db RUNTIME-DB
tp-spec work step --task TASK-ID --step TEST --plan-version 1 --action resume --role tp-software-lifecycle --summary "已接收 Fix 并核对当前候选，恢复原测试步骤" --db RUNTIME-DB
```

候选读取父 Task 全部已登记 Git 仓库，绑定真实 Change Set、AC/Subject、结果接收事件及集成证据。沿用既有 Task Change Set 契约；没有有效仓库基线时明确报告，不自动初始化 Git，也不把非 Git 原型快照冒充正式 Git 集成验收。Work 本身可以从实际目录给出文件 snapshot，最终交付应遵守该 Task 原本适用的主体契约。

不同 Work 提交同一目标文件但输出不同时，或目标文件与接收结果不一致时，要求明确 `resolutions` 条目：`path`、`owner`（贡献该输出的 Work ID）、`reason`、`evidence_refs`；多仓库另有 `repo_root`。记录真实冲突处置和最终文件，不自动挑“最后一次”结果，也不覆盖产品文件。未知目标仓库拒绝，不借候选扩大父仓库集合。

允许登记**中间候选**，包含当前已接收输出并列出当时 `outstanding_work_items`；这避免“测试 Work 等修复，而修复候选又等测试 Work 完成”的循环。恢复当前父步骤要求必要 Fix 已接收且同一实际候选仍有效；普通当前工作/未来计划工作仍须各自完成，不能借中间候选提前结单。新增接收、源码、AC/Subject 或证据变化会使候选需重新核对。最终预检及 READY Delivery 仍要求全部必要 Work 已完成、接收并进入最终候选。

恢复后进行受影响复验，使用原 `task verify`、`review record`、`task delivery-converge` 等专业入口，最后才 `work step --action complete`。测试/审查步骤中 Fix 后完成会验证相应正式结果仍适用；交付 Fix 要有接收后的真实交付收敛。未改变产品/Subject/证据的有效验证可复用，不要求只因新 Work 元数据就全量重跑；实质变化不能沿用旧 PASS。步骤完成、专业 PASS、Owner Acceptance 与正式 Task complete 不互相代签。

## 查看、学习输入与恢复

工作台从同一只读 Task API 展示步骤到 Work/Fix 的链接，点击展开具体范围、实际角色/执行者、尝试、结果、接收与候选。保留原步骤/角色时间线筛选；不在前端另造状态机。候选只标已登记，不在普通概况查询中声称当前 PASS；使用 `task complete --check` 检查当前适用性及全部缺口。`rework list` 与 `workitem list --json` 可从新会话恢复真实记录，无需长会话记忆。

Work 范围、失败/重试、真实结果、接收及候选加入 P5B 既有 Task 学习输入；认领本身不当成知识。来源按已知 Task 文件/事件定向读取，文件片段不当成磁盘文件名。每个 Work 给紧凑结果，由父 Task 统一提炼，不为每项重复全量知识收口或生成四份总结。

旧无显式计划 Work 继续可读、认领、完成，不补造新结果、隔离或接受义务。终态/退休新 Work 只读，不直接改事件/SQLite/封存 hash。旧 `rework open` 仅用于未采用显式计划的任务。不存在 DB 时只读查询不建库；写入非法参数、依赖或授权错误在同一事务回滚。

源码 Patch 可逆向应用，但写入新格式事实后不能降级旧程序继续操作该在途 Task：旧程序不知道结果/候选义务。保留用户备份与原记录，优先恢复新代码或向前修复，不删事件冒充未发生。Windows、现场隔离保证、真实业务/人验与前端浏览器交互仍需对应环境核对，命令文档不代表已经验收。
