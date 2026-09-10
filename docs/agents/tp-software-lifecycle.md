# tp-software-lifecycle

## 适用场景

用于软件需求、架构、规划、开发、数据库、安全、测试、代码审查和交付。它提供完整软件生命周期能力，但实际任务只启用必要阶段与 Role。

## 执行入口

从产品入口 `tp-spec-coding` 路由到本 Agent。机器执行契约、Formal Role 与 Capability Skill 关系以下方自动生成区块和 Role Catalog 为准。

## 能力导航

<!-- TP-SPEC:AGENT-TOPOLOGY-BEGIN -->
<!-- 由 scripts/check_document_navigation.py --write 根据 governance/role-catalog.yaml 生成。不要手工编辑本区块。 -->

- **Agent**：tp-软件工程生命周期 · `tp-software-lifecycle`
- **执行契约**：[`agents/tp-software-lifecycle/SKILL.md`](../../agents/tp-software-lifecycle/SKILL.md)
- **能力 ID**：`lifecycle.routing`、`role.resolution`、`workflow.coordination`

### Formal Role

| Name | ID | 执行契约 |
| --- | --- | --- |
| tp-产品经理 | `tp-product-manager` | [`skills/roles/tp-product-manager/SKILL.md`](../../skills/roles/tp-product-manager/SKILL.md) |
| tp-软件架构师 | `tp-software-architect` | [`skills/roles/tp-software-architect/SKILL.md`](../../skills/roles/tp-software-architect/SKILL.md) |
| tp-技术主管 | `tp-tech-lead` | [`skills/roles/tp-tech-lead/SKILL.md`](../../skills/roles/tp-tech-lead/SKILL.md) |
| tp-安全工程师 | `tp-security-engineer` | [`skills/roles/tp-security-engineer/SKILL.md`](../../skills/roles/tp-security-engineer/SKILL.md) |
| tp-开发工程师 | `tp-development-engineer` | [`skills/roles/tp-development-engineer/SKILL.md`](../../skills/roles/tp-development-engineer/SKILL.md) |
| tp-数据库工程师 | `tp-database-engineer` | [`skills/roles/tp-database-engineer/SKILL.md`](../../skills/roles/tp-database-engineer/SKILL.md) |
| tp-测试工程师 | `tp-test-engineer` | [`skills/roles/tp-test-engineer/SKILL.md`](../../skills/roles/tp-test-engineer/SKILL.md) |
| tp-代码审查员 | `tp-code-reviewer` | [`skills/roles/tp-code-reviewer/SKILL.md`](../../skills/roles/tp-code-reviewer/SKILL.md) |
| tp-集成交付工程师 | `tp-integration-engineer` | [`skills/roles/tp-integration-engineer/SKILL.md`](../../skills/roles/tp-integration-engineer/SKILL.md) |

<!-- TP-SPEC:AGENT-TOPOLOGY-END -->

## 相关文档

- [Agent / Role / Skill 总体模型](../AGENTS_AND_SKILLS.md)
- [安装与项目接入](../GETTING_STARTED.md)
- [Role Catalog](../../governance/role-catalog.yaml)

## 边界

Role 是能力集合，不是固定流程包。工作流按任务复杂度、风险和配置条件选择需要的能力；普通开发工作不应为了补齐非关键 Governance 记录而被回滚。


## 按需路由与现有项目配置

`governance/orchestration.yaml` 是 Base 默认政策，现有 Runtime `config` 表只保存项目少量覆盖，不新增配置文件/数据库。`workflow next --json` 正常读取并校验有效配置；`policy_sources` 标明 Base 与项目来源，`included_stages` 也供进度投影复用。只读路由不启动角色进程、测试或浏览器，不新增 Task、业务事件或卡片。

L1–L3 在没有范围事实及下游工作时仍先澄清；已有相关工作不要求倒补需求事件。需求明确后，架构/架构复审由实际风险、既有活动或显式信号选择，不因 L3 标签自动启用；规划由显式需求、既有活动或真实上游返修触发。没有新问题时不制造下一轮开发。新的可选备注不会仅凭事件编号使完成的开发重新开始；真实架构 REVISE、失败后上游重评、产品/证据主体变化仍重新评估。L1+ Verify、L2/L3 CODE Review 与 Delivery 必要要求保持，未修改 Q01 独立审查频度或身份边界。

开发、验证和审查建议携带 `context.validation`：已有 ChangeSet 标识、HEAD→工作区实际变更路径（最多64项）、acceptance.md 候选（最多12项）、风险信号及未确定的调用关系。列表同时返回总数，`coverage_complete: false`、`authorization_granted: false` 明确这不是覆盖证明/操作许可。历史已提交变化不在这个 Diff 内，不能据此缩小最终任务范围；实际调用方、当前部署、测试选择仍由执行者定向核对。不做 AST/依赖图，不根据路径、行数或单条测试自动授予全局 PASS。

项目只可覆盖下列已有政策；`false` 表示不强制该可选能力，**不关闭其实际风险/活动触发**：

| Key | 值与范围 |
|---|---|
| `orchestration.pipelines.<LEVEL>.<STAGE>.required` | LEVEL 为 L0–L3，STAGE 为该等级已有阶段；JSON boolean；必需 development、L1+ verification、L2/L3 review/delivery 不得置 false 或移除 |
| `orchestration.execution.delivery_fast_path.max_incremental_ai_overhead_percent` | 整数1–5；实际进入交付紧凑上下文；这是已有开销预算，不是运行结果/已达成百分比 |

例如项目确实要求实施规划时，在获准项目中设置一次；一般无需覆盖：

```text
tp-spec config set --db <DB> --scope project --scope-id <PROJECT> --key orchestration.pipelines.L2.planning.required --value true
tp-spec config get --db <DB> --scope project --scope-id <PROJECT> --key orchestration --effective
tp-spec workflow next --db <DB> --task <TASK> --json
```

优先级为 Base YAML → 精确 project/scope-id 覆盖；不接受 Task/global/user 层的 orchestration 覆盖，也不按工作目录猜目标项目。普通 `config get` 仍返回存储值；`--effective` 返回完整有效政策和每个覆盖的来源。相邻两次调用重新取当前配置；非法值、未知字段、未注册项目或不支持的作用域明确拒绝，不静默使用宽松值。相关旧坏行会阻止依赖其政策的路由；受支持 key 的坏值可通过同一 `config set` 改成合法值，不手改 DB。其他项目的覆盖不会影响当前项目；跨版本迁移仍使用既有正式入口并另行获准。

Base 中已有的信号名、条件角色 phases 和受角色能力约束的 mode 在正常路径生效；项目不覆盖角色身份、mode/effects、公共状态、隔离、权限或信任规则。既有 canonical `workflow:*` 人类信号仍可读取，配置别名按同一语义归一；include/skip 冲突及跳过必需阶段会报错。Stage 是建议能力而非 PASS 门禁；最终 Verify/Review/Delivery/Complete 继续消费真实当前证据。

## 当前有效范围、决定与授权来源

当前业务摘要只维护在已有 `task.md` 或 canonical `requirement.md` **其中一处**；有明确 Requirement 时沿用它，简单 Task 直接在 Task 内维护。使用模板的 `<!-- tp-spec:current:start -->` 与 `<!-- tp-spec:current:end -->` 两个独立行界定短当前区，代码围栏中的示例不生效。它不是新工件、数据库、工作流阶段或必填表；没有内容的模板标题/注释以及旧任务缺少此区，都不会要求新建 Requirement 或重跑 Frontier。

例如在选定工件的当前区写必要语义，机器身份、时间和事件仍由既有 CLI 生成：

```markdown
<!-- tp-spec:current:start -->
目标：修正本轮照片替换，不扩展审批功能。
当前决定 D2：依据本轮真实日志使用现行身份链路；旧假设 D1 不再适用。
验收：只对当前缺陷及直接受影响行为复验；实际页面仍待人验。
操作边界：未授权部署、通知或正式提交。
来源：本工件历史 D1→D2 记录，以及相应真实用户决定/日志位置。
<!-- tp-spec:current:end -->
```

这只是写法，不是实际 IDC 结论。旧决定留在标记外的历史区；确有独立决策历史时沿用 `requirement-decisions.md`。保留原结论、`SUPERSEDED`、继任及替代依据，不删除唯一授权来源；当前区不重复复制历史全文或其他文件的整段规范。新事实区分技术调查与用户取舍，未知/推荐不能提升为确认事实；共同使用同一假设的实现、测试、审查不能互相充当独立证据。

`workflow next --task <TASK> --db <DB> --json` 在有当前区时返回 `context.current_effective`，进度和 generated 接续/结项视图复用该段。`AVAILABLE` 表示片段可读取，**不是**需求已批准、已完成或验收通过；`authorization_granted: false` 恒定。`source` 与 `source_digest` 绑定实际读取的 UTF-8 文本（去 BOM、保留换行）；只是读取时点的内容身份，不是永久新鲜证明。来源链接不被自动访问，后续执行仍需核实相关来源、当前 subject 及真实授权。

程序只读两个固定工件，每个上限512000字节、当前区上限8192字符；不扫描全任务史，不用 mtime 或跨调用缓存。超限不截断后半段限制，而返回 `TOO_LARGE` 和来源，先定向精简/核对。两个非空当前区为 `CONFLICT`；重复/损坏标记、错 Task 身份、链接源或解码失败为 `INVALID`。不按修改时间或旧工件回退选方案；只读路由暂停依赖不明确范围的派发，让执行者先核对，**不**自动变成用户问卷或新增 BLOCKED 事件。既有终态、权限/环境等待仍优先。正常事实记录不因摘要冲突回滚；没有此区时沿用现有流程。

摘要不是授权输入。真正范围变更仍通过获准的 `task scope-change --actor human_owner`，执行许可仍由 Execution Envelope/allowed_effects 等现有控制表达；重要新决定及时更新选定当前区并留来源，不能仅改最后一条 checkpoint 叙述冒充已经收敛。程序不自动裁决两个自然语言说法是否同义/冲突，也不自行给历史结论加 SUPERSEDED；必要业务判断由实际执行者/用户负责。

本批将 canonical `requirement.md` 纳入架构主体及生成视图源指纹，将 `task.md` 和 `requirement.md` 纳入 full/technical Verification 主体。需求或约束改变后旧 PASS 继续保留历史身份，但不能用于新交付；不会重绑旧记录或自动重跑测试。指纹保守保护完整正文，不做自然语言语义比较，历史/备注的实质文本改动也可能要求重新留证；仅 BOM/CRLF 传输差异仍归一。既有未覆盖这些输入的旧 Verification 不能无证据继承，应在统一验证时重新取得适用结果；不在本批自动迁移或修写现场 DB。

## 工作段、里程碑与运行状态

`report task-summary --task <TASK> --db <DB>`、`report stage-time --task <TASK> --db <DB>`、`workitem list --task <TASK> --db <DB>` 只读账本，不生成卡片、不修订 WorkItem 或历史工作段。路由进度与用户显式查看的卡片复用相同解释：

- WorkItem 的待处理/已认领/已完成仅表示该任务里程碑登记。Task 已结单而 WorkItem 未完成、已完成项仍依赖未完成/不存在项、历史任务仍有 ACTIVE 项或损坏依赖，显示 `NEEDS_RECONCILIATION`，不自动补完成或计算项目百分比。同任务依赖由既有 `--depends` 表达；跨任务等待沿用已有 `block/resume`，不新增调度器。
- WP-0 等子范围结单不证明大型项目完成；取消/退休记录保持历史性质，不继续派发。非 Git 原型的获准 SHA-256 冻结仍按 canonical 当前范围及原证据表达；声明不代替哈希/授权核验，不强迫初始化 Git 或软件交付 Complete。
- 工作段的 Task、角色、执行者、模型和时间只来自真实记录；未知不补造。ACTIVE 或未闭合 START 不能证明进程运行，END 也不能证明所有相关进程已停止。无可靠进程观察统一为 `UNKNOWN`，同时显示最后工作段记录、未闭合数和损坏/未配对/无法计时诊断。
- START/END 按已记录的 Task、session、角色与执行者配对，必要时核对 `start_event_id`。重复、损坏或身份冲突不按最后一条修复；仅明确且唯一的旧记录可配对。无时区、时间倒退或缺失 END 不估算工作时长。已配对间隔按状态边界分摊，可能跨角色重叠；`active` 是已记录间隔之和，不是 CPU/模型工时，也不是 CLI 内部分段计时或 Token。等待结束原因不提供等待时长，未观察到的值显示 `-`。

新 `work start` 拒绝终态/退休任务及不属于该任务或已完成的 WorkItem；选择与重复检查在同一既有事务内进行。`work end` 必须与开始记录的角色和执行者一致，沿用其 WorkItem 引用。`--agent` 是记录一致性约束，不是新增身份认证，也不能证明独立 Reviewer 已实际执行。没有传 `--agent` 时仍沿用 Task owner；原记录不同就明确拒绝，不默默关闭其他执行者的段。

只有已知中断且 ownership/授权成立，才能显式结束原工作段；原任务已终止时，仍可按相同约束补记已知结束，不会重开 Task 或自动改写工作项。未知/歧义历史只读报告，现场修订按 Q06 另行限定对象及授权。新规则不迁移历史、不自动杀进程；临时工件仍按原 ownership 清理。正常生命周期 Markdown 使用已有结果，用户不必为每条命令查报告或手写机器事实。

### 临时工件与已知中断恢复（按需）

仅创建临时诊断夹具/中间输出、处理当前工作段或诊断残留时读本段，不为每条工具命令查询或开关 session。获准持久回归脚本/夹具/基线保留在业务测试目录；原始文件、intake、正式工件和 Evidence 不按 Temp 清理。

有意义执行段使用 `work start`，取真实 `session_id` 作为 run_id；临时根通过既有入口登记，不创建工作区 `.tmp`：

```text
tp-spec task artifact-path --kind execution-temp --task <TASK> --project <PROJECT> --role <ROLE> --run-id <SESSION-ID> --task-dir <DIR> --db <RUNTIME-DB> --ensure
```

正常、失败或暂停且仍能记录时，由匹配的 task/role/agent 执行 `work end`，END 提交后对该 session 幂等清理；`task complete` / `task cancel` 对已登记路径做兜底。强制中断来不及结束时保留未知，不补造时间或冒充执行者。恢复先用本节的只读工作段报告诊断；仅已知中断、原记录唯一且 ownership/授权均成立时，显式收口：

```text
tp-spec work end --reason interrupted --task <TASK> --role <ROLE> --agent <RECORDED_AGENT> --db <DB>
tp-spec temp orphan-check --db <DB>
tp-spec temp cleanup --project <PROJECT> --task <TASK> --run-id <RUN>
```

这不是三步必跑脚本：`temp orphan-check` 只报告 owned/unmanaged 候选，可加 `--project/--task/--workspace-root` 收窄；**不得自动删除**历史 `.tmp` 或无 ownership manifest 路径。`temp cleanup` 仅显式重试已登记且获准的自有路径。`CLEANUP_PENDING` 表示本机清理未完成，不新增 Task state、不逆改已提交事实；依赖必要清理证据的 Delivery 门禁仍有效。未知、重复或损坏的 START 不选最后一条、不自动修历史，不杀进程。

## v5.3.2 记账入口与恢复

普通命令不生成卡片。会话基于本轮 CLI 回执简短说明结果、下一责任和等待条件；需要详细卡片时才显式调用 `card task`。机器 stdout 保持 JSON/YAML，不插入展示 marker。

同一工作批次可一次引用多个真实输出，无需为每个文件再写一篇治理说明：

```text
tp-spec task checkpoint --task <TASK> --task-dir <TASK_DIR> --db <DB> --actor tp-development-engineer --phase development --summary "本批业务变化" --request-id <本批稳定ID> --collect <输出文件A> --collect <输出文件B>
```

`--collect` 复制已完成的本地输出到 Task 的 `evidence/collected/`，自动绑定路径、内容 SHA-256 与 Development ChangeSet；不执行源命令、不证明退出码、独立审查或验收 PASS。稳定脚本、场景、夹具和认可基线仍保存在项目正式测试目录，不转为 Temp。复制限额来自当前 Base 的 `governance/orchestration.yaml / execution.artifact_collection`；当前实现不是项目级策略 override，也不是自动发现所有宿主工具产物。失败批次可能留下未绑定的采集文件，不能据此宣称事实已入账。

`checkpoint` 与 `verify` 支持 `--request-id`：同 Task 的同逻辑请求重试返回原始回执，不新增事件；新工作、新验收或改变参数使用新 ID。回执 `replayed: true` 指向原操作，**不是本次执行或当前版本的新 PASS**。已有绑定证据缺失/变更会拒绝重放，不能直接重跑原工作掩盖损坏。未给 ID 时自动生成并返回；发生响应丢失而调用方未保存 ID 时，不能保证调用方下一次随机 ID 被去重。当前并未扩展到所有写命令。

### 一次接收已有结果报告

已有 pytest JUnit XML、Playwright原生JSON、`Test-TpSpecBase.ps1 -ReportPath` JSON 或 `tp-spec.code-review-result/v1` JSON 时，可与本批短摘要一起接收，不必手写测试数量、耗时或 Event/Evidence 元数据：

```text
tp-spec task checkpoint --task <TASK> --task-dir <TASK_DIR> --db <DB> --actor tp-development-engineer --phase development --summary "本批修改与待复验边界" --request-id <稳定批次ID> --result-report <pytest.xml> --result-report <base-report.json> --collect <其他输出>
```

`--result-report` 可重复、可与 `--collect` 合用。CLI 复制并哈希原件，从副本读取必要摘要；每份报告生成一条既有 `OBSERVATION`，再与本批 `FACT` 在同一事务登记。任一报告校验或必要投影失败时不提交该批事实；已经提交后，非关键接续视图失败仍返回 `facts_committed: true, view_status: PENDING`，按原入口重建。未提交的采集副本不等于已入账，也不会导致重新运行源测试。

返回的 `result_observations` 明确为 `authority: observation_only`、`source_kind: external_report`、`execution_observed_by_cli: false`。`reported_result` 是原件声明，不是 CLI 目击执行：JUnit 不含可靠命令或进程退出码，这些值保持 `null`；Base JSON 仅保留源文件已有的逐项退出码。报告耗时仍是**报告声明的执行区间**，账本时间是**本次接收时间**，不能互相替代。上报 subject/actor 分别放在 `reported_subject` / `reported_actor_role`，不冒充已验证的当前部署、真实身份或独立执行者。接收的 Task/actor/contract/ChangeSet 与复制证据仍按原 checkpoint 正常绑定。

**报告写了 PASS 也不会创建正式 Verification、Review 或 human witness，不满足任何必需验收。** 真实 Review/Verify 仍使用原正式入口和门禁；审查机器回执只能作为关联线索，不能代替原审查产物或让开发签独立 PASS。没有必需验收的既有 L0 行为不额外增加全局门禁。

解析限额为每份 UTF-8 报告 4 MiB、最多 10,000 个测试或检查项，仍受现有采集总文件数/单文件限额约束。JUnit 只接受已验证的平面 suite/case 布局，校验数量和真实结果元素；空报告为 `not_run`、跳过为 `incomplete`，失败不被摘要隐藏。拒绝 DTD/实体、歧义 JSON、非有限数、矛盾计数及不支持的布局；不自动修报表使其通过。不兼容或更大的产物使用 `--collect` 原样留存。Base 摘要最多展示 16 个检查、优先失败，完整结果仍在证据原件。原件可能包含隐私，接收前按获准范围选择/脱敏；本入口不扫描环境、不收集凭据、不上传模型，也不声称自动脱敏原始日志。

稳定请求 ID 在本次调用前确定。同 ID/同参数重试核对原事务、观察列表、证据哈希和报告摘要，返回原批次而非再接收或执行。源文件移走后仍可核对已绑定副本；同源路径已经用于新一轮测试时必须使用新 ID，不能把原请求的重放解释为新测试结果。改变 actor/文件列表/语义却复用 ID 会拒绝；不同 ID 不按摘要或 ChangeSet 合并。当前入口是**已有报告接收**，不是进程执行器、认证系统或多主体正式结果签收器，不能宣称已自动观察宿主外命令、时长或授权。

### 显式运行已获准的 pytest 检查并接收实际输出

只有原本就要运行、范围和副作用已获准的 pytest 检查才用此入口；不是每次 checkpoint 或每个 Task 的新必做步骤。已有报告继续使用 `--result-report`，无需为了采集元数据重新执行：

```text
tp-spec task run-pytest --task <TASK> --task-dir <TASK_DIR> --db <DB> --test tests/test_feature.py::test_case --authorization-evidence evidence/<已有授权来源> --request-id <本次执行的稳定ID> --summary "本次获准检查与边界"
```

`--test` 可以重复，只接受已经绑定的产品仓库内现有 `.py` 文件或 pytest node ID，不接收目录、任意 Shell 命令或附加 pytest 参数；多仓任务用 `--repo-root` 选择已登记 Development ChangeSet 中的一个仓库。初次执行要求 Task/Project/目录/contract 绑定有效，非等待/终态/退休，且当前产品内容仍匹配已登记的 Development ChangeSet。不会把生成报告、阶段变化或角色名称当作执行许可。

这是固定的本地 `python -m pytest` 调用，使用当前 CLI 解释器、`shell=False` 和所选仓库 cwd。它清除 `PYTEST_ADDOPTS`、显式覆盖 `addopts` 为空并启用 strict-markers，避免命令外的选项改变运行范围；同时禁止字节码缓存写入，但不删除已有缓存或改动项目配置。它仍加载 pytest 按当前环境/项目配置发现的插件和 conftest，**不是沙箱**，不能证明插件/测试没有外部副作用。依赖自定义 pytest 参数、其他解释器、Temp 目录测试或非 pytest 工具的场景，继续使用原来获准的命令及已有报告接收，不由本入口扩成通用执行器，不自动安装/升级依赖。

`--authorization-evidence` 只保存已存在的授权来源及原件副本，CLI 不解释自然语言授权真假，也不新增或替代 Execution Envelope、allowed_effects、宿主批准、编译/部署/浏览器/生产限制。执行者必须事先核对测试代码、插件和真实环境的许可；无有效权限不得运行，尤其不能仅创建一份写着“已批准”的文件就越权。自动调用此入口的宿主同样要执行其原有权限控制。

程序保存命令参数、Python 版本、当前解释器的 pytest 发行元数据版本（不冒充子进程实际 import 路径证明）、PID、前后 ChangeSet、原始 stdout/stderr、pytest JUnit、实际退出码、开始/结束和单调计时耗时，随后通过原 `checkpoint` 事务自动采集/绑定，输出一份紧凑 JSON。`execution.observed_here=true` 只指本程序实际观察了本地执行尝试/直接子进程（NOT_STARTED 无 PID 和测试退出码）；嵌套 `result_observations` 仍按上游报告的非权威格式表达。PID 不是独立 Reviewer 身份，模型未知为 `null`；不观察远端部署或宿主外命令。`prepared_at` 是控制原件预留时间；`started_at/finished_at` 是进程启动尝试及等待结束时间。耗时只覆盖 spawn/wait，不包含取证记账，更不是模型工时。源码在执行中变化时 `subject_unchanged=false`，只留实际观察，不修正旧主体。

**退出 0 不产生正式 Verification、CODE PASS、Visual PASS 或 human witness。** 需要正式结论时，由原职责主体对照真实范围和证据通过既有 `verify` / `review record` 门禁留证；不得把外部截图、机器输出或一次批次汇合当成独立审查。采集成功也不保证所有所选测试运行：跳过/空用例/失败照原结果报告。

本入口在 `evidence/pytest-executions/<请求哈希>/` 保留执行控制原件，并使用原 `evidence/collected/` 保存绑定副本。请求 ID 在执行前保存，同 ID 只对应一次执行：已结束则核对原始输出和已提交回执，不重跑；登记失败则只重试登记。已提交但响应丢失会只读查找原回执，能确认时返回 `facts_committed=true`；未提交为 `false`，数据库/回执不可核实时为 `null` 并明确 `UNKNOWN`。必要事实失败不回滚测试对产品产生的实际效果，派生视图失败仍遵守既有 PENDING 恢复。

默认等待上限600秒，可用正且有限的 `--timeout` 指定。超时返回124，中断返回130，未能启动为127；pytest 退出码0–5原样保留，其他进程退出保留原码在 `execution.exit_code`、命令返回1。只有原测试为0而记账未能确认时，外层命令才转为非零并单独报告记账问题。超时/可捕获中断只结束本次拥有的直接子进程；后代进程状态不监控、既有外部业务副作用不撤回。

目录预留后崩溃、完成回执缺失/损坏或控制文件冲突，都保持 `INCOMPLETE` / `INVALID`，**不自动过期、不删除预留、不换新ID偷重试**。只有实际所有权和授权成立、运行/外部结果核实后才处理恢复；原件存在则恢复原件并以原 ID 重试登记，无法确定执行状态就保持未知。并发同请求只允许一个执行者；这不是跨文件系统/账本/业务的分布式 exactly-once 保证。原始输出可能含敏感数据，应在获准环境与非敏感夹具上使用，按项目证据访问和保留政策管理；不会自动上传模型、自动脱敏、后台刷新卡片或清除用户文件。

### 接收原生浏览器报告与已批准媒体

已有获准 Playwright Test 执行结束后，直接使用 `checkpoint --result-report <Playwright原生JSON>`；不要求改上游 reporter、复制引擎或手拼机器字段。原报告包含的结果只成为 `OBSERVATION`：按各项目/attempt核对汇总，跳过、预期失败、flaky或缺少执行不冒充全通过，且不会生成正式 Verify／Review／Visual／human witness。结果中的 `reported_tool_version` 是报告声明；未实际观察的命令、退出码、actor、浏览器、viewport、模型和远端部署仍未知。

默认不读取报告声明的其他文件。已审核本次输出目录及数据范围后可以显式接收其图片、视频、ZIP和HTML：

```text
tp-spec task checkpoint --task <TASK> --task-dir <TASK_DIR> --db <DB> --actor tp-test-engineer --phase testing --summary "选定场景实际结果、未验边界和下一步" --request-id <本次登记ID> --result-report <本次原生JSON> --report-artifact-root <已批准输出目录>
```

`--report-artifact-root` 必须与 `--result-report` 合用，且至少有一份 Playwright报告；相对附件路径以该目录为基准，绝对路径必须仍在其中。只复制报告实际声明的受限媒体，不递归扫目录、不访问网络、不解压/渲染。拒绝越界、链接/重解析点、缺失、扩展名与媒体类型不符和变化中的文件；不因HTML/MIME名称就宣称内容安全或视觉正确。原生JSON上限4MiB，整个批次沿用既有采集数量/单文件大小限制；大报告或其他格式可显式 `--collect` 保留原件，但不返回解析汇总。独立 Midscene HTML 同样用 `--collect`，不将 HTML 文本签成视觉判定。

同请求复用原始报告和已采媒体绑定，源目录被移走也不再读取；已采证据损坏明确拒绝，不重新执行浏览器/模型。未选择媒体采集的旧请求保持原契约；为原请求新增 root 是载荷冲突，不静默补写旧事实。无法入账不撤回外部测试已产生的单据或通知，恢复原产物后仅重试登记。

不要将 root 指向 HOME、整个仓库或认证目录；输入必须已经获准且非敏感。工具只减少摘要中的任意文本暴露，不对原JSON/截图/HTML秘密扫描或自动脱敏；原件应受既有本地证据权限和保留政策约束，不自动打包/上传模型。`storageState.json` 等不会因为出现在附件路径中被自动接收，也不应显式发送。文件采集保护不是对同账号恶意进程的完整沙箱。

浏览器调用、真实部署/业务ID、模型判读及人验分别由对应实际执行者核验；默认Verify与Visual Manifest规则不放宽。选场景、TS官方集成、动效、缓存及依赖升级边界按需读 `skills/capabilities/testing-strategy/references/visual-qa.md`。

### 一次汇合不同职责已经留证的正式结果

开发、验证与独立 CODE 审查通过其原职责入口完成可信登记后，协调者可以直接使用返回/查询到的原事件 ID，与本批短摘要一次汇合，无需复制报告、重写机器字段或重新签署：

```text
tp-spec task checkpoint --task <TASK> --task-dir <TASK_DIR> --db <DB> --actor tp-software-lifecycle --phase other --summary "本批实际结果、未验项与下一步" --request-id <汇合ID> --recorded-result <开发事件ID> --recorded-result <验证事件ID> --recorded-result <CODE事件ID>
```

仅接受同 Task、契约有效的 record-first Development FACT、正式 Verification 和 CODE/IMPLEMENTATION/ULTRA_REVIEW 原结果；读取原 actor、scope、subject、事务、证据及回执绑定，在提交边界再核对。不接收自由文本 FACT 冒充专业结果，不让调用者传 actor/decision JSON 来签独立 PASS。缺失、损坏、跨 Task、重复或发生竞争的引用整批拒绝。旧结果只能按历史身份引用，不能变成当前主体的新 PASS；汇合摘要仍不能绕过后续门禁的新鲜度检查。

结果在 `recorded_results` 返回，`authority=original_event_only`。原专业事件保留原 actor/结论/证据且不重新创建，新增的只是当前协调者的批次 FACT；重复同请求不再新增事实。未登记的原始报告仍属于外部观察，不能靠这个选项变成正式结果；需原专业主体通过既有门禁先留证，不引入匿名的跨角色代签协议。此复用策略不要求把多个独立主体的执行伪装成一个开发者，也不承诺宿主身份认证。浏览器/视觉工具的专用运行和报告映射按其已确认接入范围实现，不转用 pytest 命令冒充。

未运行、等待人验、授权不足或前置环境缺失，不等于发现代码缺陷：

```text
tp-spec task block --task <TASK> --task-dir <TASK_DIR> --db <DB> --actor tp-test-engineer --reason "等待当前版本交互验收" --kind human_acceptance --condition "收到用户验收或返修反馈"
tp-spec task resume --task <TASK> --task-dir <TASK_DIR> --db <DB> --actor human_owner --summary "收到用户反馈" --resolution-evidence evidence/owner-feedback.md
```

证据必须真实来自相应动作/用户，不得由 AI 编造用户签收。恢复本身不产生验收 PASS；反馈含缺陷时在原 Task 内按 Finding 返修，复用仍有效证据，只验证实际影响范围，最终必要门禁不变。`permission` 同样要求 `human_owner`；`environment` 要求新的真实恢复证据，相同内容不因改 mtime 而通过；`dependency --requires-task <上游TASK>` 核对同项目已声明任务真实 `COMPLETED`，不按名字猜依赖。未填写 `--kind` 的历史自由文本保持旧兼容语义，不自动推断成新的授权或依赖结论。结构化等待记录损坏必须修复，不能降级为无条件恢复。

### 专业结果受阻时的接续

`Review BLOCKED` 与 `Delivery BLOCKED` 表示对应动作缺少前置，不是产品 Finding。`workflow next --json` 在前置未变化时返回不派发的 `recommended_action: none`，并在 `context.waiting` 给出来源事件、等待原因、下一责任与恢复条件；Task 仍可为 ACTIVE，`none` 不代表整任务完成。`status.yaml`、接续摘要及只读进度使用同一等待事实。真实 `NEEDS_FIX/FAIL/REVISE` 仍按原规则交回处理；CODE/IMPLEMENTATION/ULTRA_REVIEW 共用一条最新审查事实线。

同内容 checkpoint、重复登记同一验证结果、复制或改名相同证据、无关笔记均不解除等待。新的实际产品 ChangeSet、受评审 canonical 主体变化或当前主体上的新验证证据允许重新评估，不继承旧 PASS；当前 Verification 的主体或证据已失效时，先调度必要验证，不重复派发已知无法留证的审查/交付。原有角色、effect 授权和正式门禁仍执行。

外部前置用既有 typed `block/resume` 留存实际解决证据：`block --phase` 对应受阻的 `review` 或 `delivery`（架构复审使用 `review`），不能用其他阶段或未分类的历史 resume 冲掉专业阻塞。环境恢复证据须与原前置内容不同、当前文件哈希仍有效；依赖须实际完成。`HUMAN_DECISION` 或明确归 `human_owner` 的交付阻塞，只有同阶段的 `human_acceptance/permission` 且由 `human_owner` 留证恢复才允许重新评估，代码变化和环境恢复不能代替授权。恢复条件本身的业务含义由真实执行者/用户确认，程序不从说明文本推断。

首次命令因前置校验失败、尚未形成专业结果时，保留实际错误并按上述现有等待入口记录分类；不能填 `NEEDS_FIX` 代替未运行，也不要在同一条件下反复调用失败命令。本次没有建立跨命令失败缓存、自动轮询或重试调度器。解决记录不授予测试/Review/Visual/human PASS，也不免除实际 Delivery READY 与 Complete 校验。诊断查询仍不写业务事实或生成卡片。

正常事实提交后的 `generated/continuation.md` 是可重建派生物；更新失败返回 `facts_committed: true, view_status: PENDING`，不得将旧视图声称为最新。可在故障排除后运行：

```text
tp-spec projection rebuild --task <TASK> --task-dir <TASK_DIR> --db <DB> --view-only
```

此命令不新增业务事件。`status.yaml`、`events.jsonl`、必要证据和结单封存仍受原有事务/恢复约束；数据库失败、账本损坏或必要投影失败不按派生物容错。重放原请求不会偷偷刷新视图。

正常 CLI 自动将分段诊断写入用户级 `diagnostics/cli/`；通过以下只读入口查询，不读取完整卡片：

```text
tp-spec report timings --task <TASK> --limit 20 --json
tp-spec report timings --invocation <cli_invocation_id> --json
```

每条诊断区分未进入/完成/抛出异常的区段，给出解析、配置、ChangeSet、锁等待、持锁、写入、提交、证据、投影、卡片与总耗时。总计从标准流设置后的 `main` 解析起至调度返回，不含解释器启动、进入 `main` 前的导入、标准流设置和诊断文件自身保存；显式卡片内部的按需导入则包含在 card 区段内。分段是 inclusive 且同名调用累加，可能相互嵌套，不能相加或拿总时长减重叠区段求其他成本。

`lock_wait` 只测显式 `BEGIN IMMEDIATE`；`lock_held` 从成功获取该锁到 COMMIT/ROLLBACK（或回滚尝试失败），包括其内证据、备份、投影及 journal 工作。正常 checkpoint 的必要事实事务与派生只读事务各有一次持锁区间，不将它们算成两次业务提交。延迟事务无法由 BEGIN 推定获取写锁的时点，其等待仍包含在 `db_write` 中，`lock_held` 不补造其持锁时间。命令结果始终看真实退出码和事实回执，某区段 completed 不代表业务 PASS。

`completion: finished` 只表示已正常完成命令收尾，不代表退出码为 0；传播到命令边界的 KeyboardInterrupt 记 `interrupted` 和退出码 130，再继续传播中断。强杀/断电可能没有结束诊断，缺记录保持未知，不根据事件间隔补时长。旧 v1 诊断没有 completion/lock_held 仍可查询，缺字段不补造数值；损坏的分段数值/状态被跳过并计入 `corrupt_records_skipped`。

普通命令 card 为 `not_entered`，只注册轻量参数，不导入 snapshot/render 实现；显式查看失败不冒称展示完成。默认保留最近 200 条，可用 `TP_SPEC_DIAGNOSTICS_KEEP=1..10000` 调整；路径仍遵循 `TP_SPEC_USER_ROOT`。诊断不保存原始 argv/凭据，Task 关联只保留符合既有格式的标识，非法输入记空；这不认证身份或授予权限。诊断构造/保存失败仅尝试一次无详细异常内容的警告，警告通道也不可用时不改变主结果，调用上下文仍释放。诊断不属于 Runtime 权威事实。派生视图故障的警告通道不可用时，机器回执仍返回 `facts_committed: true`、`view_status: PENDING` 及恢复入口。

## 当前审查证据与交付前置

`review record --kind CODE`（含 `IMPLEMENTATION` / `ULTRA_REVIEW`）的 PASS 必须由 `tp-code-reviewer` 提交，`--findings-count` 非负，并通过 `--evidence evidence/<实际审查结果>` 引用真实文件。Runtime 生成的回执只包装结论，不代替实际审查；`--actor` 也不证明启动了独立执行者。不得把开发自测复制成独立 Reviewer 结果。计数没有表达严重度，不能仅凭非零计数把建议项自动升级为阻断项；真实Reviewer仍须对所声明的decision负责。

当前门禁只消费最新同角色的适用结果：新的 FAIL/NEEDS_FIX/BLOCKED、失效主体或损坏证据不能被更早的 PASS 覆盖。CODE 的三个名称共用结果序列。审查绑定当前 Verification、ChangeSet 和证据；交付再次校验审查原证据与机器回执。事务写入前会复核已绑定结果，复核失败不追加对应事实，也不撤销已完成的产品修改。

`delivery-converge --delivery-status READY` 与 `task complete` 共用必要 AC 处置及真实证据/owner 授权检查。技术和代码审查通过不授予人验 PASS；必需人验仍 PENDING/BLOCKED 时不得 READY。合法 defer/waive 继续通过既有 `task acceptance-override` 留证，不手改账本或把未运行写为 PASS。

### 技术限定结果与完整验收分开

`task verify` 默认 `--scope full`，继续校验当前要求的视觉证据。这里的 full 是结果的验收范围，不是自动执行全量测试的授权。命令只接收已经发生的检查和真实产物，不执行测试、不代替人验。

视觉/人验尚未完成时，可以显式记录当前技术检查，并由实际独立 CODE Reviewer 另行留证：

```text
tp-spec task verify --task <TASK> --task-dir <TASK_DIR> --db <DB> --scope technical --check "实际已执行的检查及范围" --decision PASS --summary "仅这些技术检查通过；视觉/人验待验" --evidence evidence/<本次真实技术结果>
```

`--check` 可重复，technical 至少需要一项非空检查说明；PASS 仍要求真实文件和当前 Development ChangeSet。范围、检查清单与证据进入同一正式事件/回执及幂等请求身份，不新增账本。状态、进度、接续摘要和显式卡片保留 `TECHNICAL` 限定；技术/审查均通过后，完整验收缺口仍显示等待，不能反复派发已知不满足前置的交付。未知范围不按完整 PASS 放行；无范围字段的历史事件保留原 full 语义，不自动转换旧 PASS。

补齐实际视觉/人验后，按当前完整验收范围重新执行默认 Verify 留证。原 CODE 审查明确绑定 technical 结果，当前产品、验收标准和检查方案未变，且原技术证据和审查产物仍有效时，不单凭补验的 Verify 事件编号要求重做该审查。普通 full 结果的既有重验证/Review 策略不因此放宽。只允许补充 AC 的执行证据/结论，不忽略 AC 标准、方法、必要视觉策略或产品变化；新 FAIL/NEEDS_FIX、损坏证据或失效主体不能被后来的 PASS 遮蔽。新执行应保留旧证据原件，不能覆盖旧文件后仍沿用其审查。

`technical PASS` 本身不能满足 READY 或 Complete（包括 L0）。最终门禁仍汇合当前完整验证、必要 AC/human 处置和适用独立审查；提交边界复核当前主体，不能沿用预检后已经变化的结果。范围是证据含义，不是跳过权限或降低 Review 频度的开关。使用新范围事件时，读取/写入端须同步使用本升级；未验证旧二进制混用，不修改 Task 版本绕过检查。

历史无独立证据的 CODE PASS 保留为历史，不能继续作为新交付的有效前置；需要真正的当前审查与证据，不自动补造旧报告、迁移或重开终态任务。本次没有更改公共状态、数据库 schema 或独立审查的授权要求。

## 完整仓库范围与最终交付

Development 可以显式 `checkpoint --repo-root` 只登记本轮局部仓库；不带该参数时，Runtime 自动采用本 Task 已登记的完整仓库集合，尚无记录才使用原项目绑定。普通局部记录不抹掉较早的后端/身份仓库。`full` Verify、Delivery 和 Complete 必须覆盖该完整集合；局部证据只能通过显式 `--scope technical --check ...` 表达，不能当作整任务 PASS。合并范围的 checkpoint 是绑定当前事实，不要求重新改代码或无条件跑全量回归；实际检查仍由影响和现有授权决定。

**仅在 owner 已明确批准范围变化时**，通过既有命令提供完整的新集合（每个保留仓库重复参数），并在 summary/canonical 当前区关联批准依据：

```text
tp-spec task scope-change --task <TASK> --task-dir <TASK_DIR> --db <DB> --actor human_owner --scope-id <DECISION_ID> --summary "已批准的范围变化及来源" --repo-root <INCLUDED_REPO_A> --repo-root <INCLUDED_REPO_B>
```

新增参数是可选扩展，复用现有 SCOPE_CHANGE 和 `repo_roots` 载体，不新增数据库或状态。不带参数仍是原范围说明，**不替换仓库集合**；AC waiver 不暗含排除仓库。显式集合形成后，Development 不得自行加入其他仓库。改变集合后先登记新的 Development，再取得适用验证和审查；原先技术审查不能跨越该 owner 范围边界沿用。命令的 actor 字段记录职责，不是身份认证、真实授权或操作许可的替代品。

Runtime 只知道已登记仓库，不能从自然语言自动证明“所有获准仓库都已登记”。Integration 仍需对照 canonical 当前有效范围、全部必要 AC、实际代码/配置/数据影响及真实环境，发现未登记影响先按权限纠正绑定；不得只看最后一次单仓 Diff 或一条退出码。合法排除和 defer/waive 保留各自来源，不自动扩大或撤销。

ChangeSet 原内容 ID 保持原格式；正式新记录额外保留既有快照内的逐仓 `product_digest`，按**仓库身份→内容**校验，避免两个仓库交换内容而总 ID 恰好不变。selected pytest 的 `subject_unchanged` 同样检查逐仓绑定。旧单仓仍可按原内容 ID 校验；旧多仓记录缺逐仓摘要时必须重新登记当前 checkpoint 和实际适用证据，不能补写历史摘要或复用旧 PASS。仅历史提交元数据变化、产品内容未变的原有兼容语义保留；未验证混用旧二进制读取新记录。

最终结单重新检查最新 Delivery 及其原始附件；较新的损坏/失败结果不能回退到旧 READY。必要人验/视觉、独立 CODE、临时绕过清理和可信 AC 处置仍执行。范围历史损坏时报告具体阻塞，不静默丢掉较早仓库；提交前主体变化拒绝入账，但不撤销用户的产品修改。普通流转不生成或刷新卡片。
