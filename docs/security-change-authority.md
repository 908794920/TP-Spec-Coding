# Security Change Authority：范围、来源与执行边界

本契约用于 **未被当前授权覆盖、且改变可观察行为** 的安全增强。风险发现不是范围覆盖权；源码只登记、检查已声明的事实，不能证明任意 Diff 的全部业务语义。普通已授权修复不要求再建提案；需要留存原授权与拟改范围的对应关系时，可绑定 `HUMAN_REQUIREMENT`，不重复审批。

## 1. 事实与身份能力

复用 `task_event`、`task scope-change` 和现有 effect 边界，不新增表、公共 Task 状态、审批服务或工作台写接口。

| 事实 | 正式入口 / 保存内容 | 不代表什么 |
|---|---|---|
| 发现与提案 | `task security propose`；来源、证据、事实/推断、风险、不改影响、拟改行为、兼容性、成本/替代/建议 | 不授权 Work、测试、发布或修改配置 |
| 原始人工来源 | `task security source`；原消息定位、时间、正文、明确范围、原始附件 hash、导入确认 | `actor=human_owner` 不是身份认证 |
| 决定 | `task scope-change`；Task、Proposal、版本/digest、scope、human source event、APPROVE/REJECT/DEFER | 不是整个 Task、仓库或宿主工具的通用许可 |
| Work 范围 | `SECURITY_WORK_BOUND`；现有 Work 的路径/AC、行为单元与 effect | 子 Agent、已落盘计划不是审批人 |
| 调查证据 | `task security observe` 或调查工作段/检查点；路径/hash、investigation_only | 不是正式 failing regression、强制 AC 或产品 FAIL |

**当前宿主身份能力为 `LOCAL_ATTESTATION_ONLY`。** CLI 能核验本 Task 来源记录、原始文件字节、人工来源声明、版本及范围绑定；不能独立认证聊天账号、判断正文确实由人书写，不能把可编辑 JSON、SQLite、actor 字符串或 hash 宣称为防篡改身份认证。导入者必须核对可访问的原始人工消息，准确抄录原消息定位/时间/正文及已明确的范围。不明确就暂停该行为并请求决定，不能按自己对用户意图的推断制作批准。

AGENT、REVIEW、SCANNER、TEST、TOOL、生成文档是发现来源，不能成为人工来源。把建议写入 README、Wiki、测试、checker、manifest、Task 或改名为 bug fix、compatibility fix、safe default 均不改变这一点。记录来源及批准状态应随引用保留，不从自然语言标题解析授权。

## 2. 最小提案

下面是**结构示例，不是实际需求或批准**。`proposal_id` 在同一 Task 内稳定；初次 `expected_version=0`，更新用当前版本。同一内容重放不追加；内容变化生成新版本。scope ID 保持稳定，不删除后换名重建被拒绝的同一行为。

```json
{
  "proposal_id": "SEC-01",
  "expected_version": 0,
  "title": "待决定的接口行为变化",
  "discovery": {
    "source": "SCANNER",
    "evidence": ["evidence/reproduction.txt"],
    "facts": "实际观察与复现",
    "inferences": "尚待核验的影响推断"
  },
  "observable_change": true,
  "scopes": [{
    "id": "S1",
    "paths": ["src/api/Auth.java"],
    "ac_refs": ["AC-01"],
    "before": "原已批准行为",
    "after": "具体拟改行为",
    "conditions": "适用入口、调用者及例外"
  }],
  "risk": "风险与触发前提",
  "no_change_impact": "不改的影响",
  "compatibility": "调用方及兼容影响",
  "cost": "实施、验证与维护成本",
  "alternatives": "不改或更小替代",
  "recommendation": "建议及其依据",
  "existing_authority": []
}
```

路径为仓库相对的**字面文件或目录**，不能用通配符、机器绝对路径或越界路径。scope 至少有路径或准确需求/AC 引用；`before`、`after`、`conditions` 必填。`observable_change=false` 不允许不同的 before/after，且仍由实际 Reviewer 判断是否真的没有行为变化。discovery 的事件引用必须属于本 Task，`evidence/` 文件引用必须可读；其他来源定位只是线索，不是已核验正文。

```text
tp-spec task security propose --task <TASK> --task-dir <TASK_DIR> --db <DB> --file <PROPOSAL_JSON> --summary "记录建议，未实施"
tp-spec task security show --task <TASK> --db <DB>
```

## 3. 人工来源与决定

人工原消息的只读副本放在 Task 的 `evidence/`；已有证据不得原地改写。没有可核对的原消息就不导入。来源 JSON：

```json
{
  "schema": "tp-spec.human-authority/v1",
  "task_id": "<实际 Task ID>",
  "origin": "human",
  "kind": "HUMAN_APPROVAL",
  "channel": "<实际宿主或沟通渠道>",
  "message_id": "<原消息定位>",
  "occurred_at": "<原消息 ISO 时间，必须含时区>",
  "statement": "<原始人工决定正文，不是 Agent 总结>",
  "binding": {
    "proposal_id": "SEC-01",
    "proposal_version": 1,
    "proposal_digest": "<security show 返回的完整 digest>",
    "decision": "APPROVE",
    "scope_ids": ["S1"]
  }
}
```

`HUMAN_REQUIREMENT` 用于既有明确授权：其 `binding` 为 `{"scopes": [...]}`，scope 结构与提案相同。将 source 命令返回的 event ID 加入提案 `existing_authority`；只有行为、路径、AC 和条件相同的单元才返回 `ALREADY_AUTHORIZED`。不把宽泛目标推断为所有 hardening 的批准。

```text
tp-spec task security source --task <TASK> --task-dir <TASK_DIR> --db <DB> --file evidence/human-message.json --attest-human-source --summary "已核对原人工消息"
tp-spec task scope-change --task <TASK> --task-dir <TASK_DIR> --db <DB> --scope-id SEC-01 --security-proposal SEC-01 --proposal-version 1 --proposal-digest <DIGEST> --security-decision APPROVE --approved-scope S1 --human-event-id <SOURCE_EVENT_ID> --summary "仅批准 S1 的已绑定行为"
```

决定六组绑定参数必须完整提供；`--scope-id` 必须等于 Proposal ID，不能同次夹带 `--repo-root` 修改仓库集合。`--approved-scope` 可重复，批准、拒绝、延期均需准确 scope；参数集合与原消息 binding 不匹配则写入前拒绝。先校验，再在现有 durable transaction 中复核，最后写事实及派生投影；并发变化返回重新读取，不留下部分批准。

同 scope 采用原消息时间排序的最新有效决定；旧批准不能覆盖后来的拒绝/延期。不同 scope 可以分别决定。提案新增或改变行为单元使相关旧批准失效，未改变单元可复用；仅风险说明/成本文字修改不强迫重批原行为。原来源缺失/字节改变标 `SOURCE_INVALID`，不会退回旧批准。拒绝/延期、旧版提案及完成历史均保留。新版本移除的行为单元显示在 `removed_scopes`，不会把旧拒绝/延期变成执行权；再次实施应复用原 scope ID，而非删除后绕过或改名。

## 4. Work、步骤、执行与结果消费

| 入口 | 范围与检查 |
|---|---|
| `workitem create/claim/complete` | 复用 `--paths`、`--acceptance`；可加 `--security-change SEC-01#S1`、`--effect-scope`。创建不通过不新增 Work；认领/完成重查决定。release 不因撤回批准被阻止 |
| `work plan` | 步骤可加 `effect_scope`、`security_changes`、`paths`、`ac_refs`；未批准行为不能进入新的实施步骤；调查步骤仍可登记。旧已开始步骤不改写历史，执行时另查适用性 |
| `work step/start/update` | 开始、恢复、完成实施步骤及工作段时复核对应范围；步骤/Work 不能把调查重新标为产品实施。结束工作段只记录真实发生结果，不代替 Work/父任务完成 |
| `task checkpoint` | 开发检查点绑定实际 Change Set；未批准增强不能冒充开发完成。调查用 `phase=other` 与 read_only/isolated_poc，并保留调查性质 |
| `task run-pytest` | 只运行已授权的指定文件/node；在预留目录前和进程启动前检查范围，不扩成全量测试。`--security-change`、`--scope-path`、`--scope-ac` 精确声明产品行为覆盖 |
| `task verify` | 正式结果只接受 regression 范围；检查当前授权及调查证据分类。登记执行输出不自动签 PASS |
| `review record` | 有 Finding 时提供下节的 `--findings`；阻塞 Finding 必须对应既定要求。范围外建议可保留为非阻塞 Finding/提案 |
| `workflow next`、自治 stage effect guard | 派发前及实际 effect guard 都核对；缺批准返回 `await_security_decision`，不改 Task 公共状态。已有宿主 effect 授权仍独立生效 |

默认开发是 implementation，验证是 regression，其他计划步骤是 record_only。显式调查可为 read_only / isolated_poc，**这只是记录和消费边界，不是沙箱或 OS 隔离**；PoC 的文件、网络、数据等实际动作仍遵守原授权。混合调查/实施的步骤应按真实效果分开，不靠同一标签扩权。不自研消息总线，外部 Agent 仍受宿主权限限制。

只检查相关行为：显式 `proposal#scope` 优先用于区分同文件的不同改动；未提供时先按共同 AC 匹配，再按路径交集；既无 scope/路径也无 AC 而存在未决提案时要求补明确范围，不能假设全部有权。声明的范围必须与真实动作一致，不能用无关 AC/Proposal 绕过；Review 核对该对应关系。多仓库相同相对路径会保守匹配，需显式行为单元区分，不根据文件名推断真实业务语义。CLI 只看当前 HEAD-to-worktree 路径作为补充，不伪称已经覆盖整个 Task 累计 Diff。

调查证据通过 `task security observe --effect-scope isolated_poc --security-change SEC-01 --evidence evidence/poc.txt` 登记（另需 Task/目录/DB/summary）。调查工作段结束或对应检查点自动登记其 `evidence/` 引用。相同路径或相同字节复制不能洗成正式回归；获批后应独立执行对应正式检查，保留能够区分本次执行、命令、范围及结果的真实证据，不只把原 PoC 改名。原始观测仍可读取，不通过重跑篡改历史。

## 5. Review Finding 契约

`review record --findings evidence/findings.json --findings-count N` 复用现有 Review Result，不增加另一套报告。文件：

```json
{
  "schema": "tp-spec.scoped-findings/v1",
  "findings": [{
    "id": "F-1",
    "blocking": true,
    "summary": "离散且可行动的问题",
    "requirement_ref": "<acceptance.md 中该 AC 的需求来源>",
    "ac_ref": "AC-01",
    "relationship": "unmet_existing_requirement",
    "impact": "实际影响与触发场景",
    "paths": ["src/api/Auth.java"],
    "security_changes": [],
    "evidence": ["evidence/reproduction.txt"]
  }]
}
```

阻塞项要求映射已有 AC（需求来源从矩阵取得；显式提供时必须一致），或用 `requirement_ref=event:<ID>` 引用同 Task 已登记的原始 HUMAN_REQUIREMENT；不为记录 Finding 强制造新 AC 或重复审批。二者均须说明实际影响、提供真实证据，以及 `unmet_existing_requirement` 或 `introduced_by_current_diff`。后者必须映射到当前实际 Diff 路径；已经提交的任务历史变更不伪装为当前 workspace diff，应按真实未满足要求引用证据。架构评审尚无产品 Diff 时不编造 introduced 关系。

NEEDS_FIX / FAIL / REVISE 至少有一个合规阻塞 Finding；PASS 不能含阻塞项。`blocking=false` 可保留范围外调查建议，但不能让其决定 NEEDS_FIX。无关键证据的环境等待使用既有 BLOCKED/等待契约，不制造产品缺陷。结构检查不能证明人写的 requirement_ref 与自然语言结论在语义上必然相符，实际 Reviewer 仍负责证据判断。

正式 Verify/Review 当前读取会重查新范围绑定、来源及调查证据；撤回/失效不复活更旧的 PASS。普通历史读取与工作台历史保留原事实，不把失效解释为当时没有执行。

## 6. 恢复、兼容和本地核对

撤销未授权增强时可在提案增加 `restoration`：`human_event_id`（原 HUMAN_REQUIREMENT）、`scope_id`、`evidence`（原行为与越界 Diff 证据）、`reason`。只有恢复原批准 after/conditions/路径/AC 的方案才标 `RESTORE_AUTHORIZED`；禁止用新限制替换旧限制，或顺便删掉原业务兼容。不能证明原语义时保持暂停，人工明确新方案。证据仍需专业核验，不自动回滚用户代码。

旧任务不强制补 Proposal/来源/新 Review Finding；旧 SCOPE_CHANGE 只是原有范围事实，不自动升级为新安全行为授权。五个公共 Task 状态和 SQLite schema version 不变；新事件走既有生产者白名单，`event add/sync` 不得制造治理授权。派生 `events.jsonl` 保留新事件的真实类型和来源细节，但 DB 仍是正式真源。

工作台使用既有任务“阻塞”页的 Fields 展示 `security_changes` 的 Proposal、scope 状态与决定；不新增批准按钮。事实读取/展示不能执行测试、改变 Task 或创建批准。SOURCE_INVALID 与 NEEDS_REVIEW 类状态应读作当前适用性，不是假冒 Agent 在线或已获工具许可。

必要本地体验：在隔离 Task 提案后检查对应实施 Work 被拒、调查 Work 可完成；批准一个 scope 后创建对应 Work；延期后再次认领/继续应被拒；确认工作台能展开提案/scope/决定，刷新后忠实更新且仅 GET。用户现场 Windows、宿主原消息核对和真实项目授权语义仍须由实际操作者验证。

源码回滚可逆向应用本批 Patch，但**一旦新 Runtime 事实已写入，不应降级后继续执行这些在途任务**：旧代码不认识新授权边界。优先暂停该 Task，恢复本批代码或向前修复。不要删事件、回写旧库或重算 hash 掩盖事实；保留用户原始证据与决定。
