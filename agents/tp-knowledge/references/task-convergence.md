# Task 知识与记忆收敛

适用：新交付 Request 的 `learning_schema=tp-spec.task-learning/v1`。
本文件是正式 CLI 的输入/回执说明，不是自动提炼服务，也不是一份待复制的任务报告。
集成交付工程师触发并核对；knowledge-capture 提炼候选，tp-knowledge 定向检索与维护，
共享 tp-memory-capture 判断项目记忆。每个 Task 的责任链都执行，Work 只提供紧凑结果。

## 1. 顺序与真实输入

先按 `task complete --check` 处理当前已知缺口，固定最终候选并复用有效技术结果。
`task delivery-converge ... --delivery-status READY` 为 L0–L3 创建或复用既有
`KNOWLEDGE_CONVERGENCE_REQUEST`，没有 knowledge_signals 也会创建。
轻量任务只绑定实际适用的 Verification/Review；不适用的 event ID 为 0，不伪造 PASS。

```bash
tp-spec knowledge task-inputs --task <TASK-ID> --task-dir <TASK-DIR> --db <DB>
tp-spec knowledge task-inputs --task <TASK-ID> --task-dir <TASK-DIR> --db <DB> --item event:<ID>
```

这是只读输入清单，不创建 Request，不查询 Knowledge，不生成“已阅读”声明。
返回当前 request ID、`request_current`、输入 digest、逐项来源/指纹、缺口和相对 Request
的 added/removed/changed/unchanged。`--request-event-id` 可选择历史请求作对比，不能让旧请求重新有效。
`--item` 读取该 Task 的作用域、交付语义、事件或 Work 详情；文件按返回的相对 `ref` 定向读取。

覆盖本 Task 的 canonical 需求、澄清/决定、设计/实现、测试/审查、已记录计划和角色工作段、
Work 结果及交付材料；事件可指向本 Task 其他明确证据。事件 source 不等于授权。
完全相同的事件内容去重，原事件不删除；没有登记的历史不补造。
只读已知工件和明确引用，不全盘递归找文件、不扫描其他 Task 或全 Knowledge Vault。
远程引用只作为可导航来源，清单不声称已联网读过。未登记材料应通过现有事实/引用入口补入，
而非仅把它写进学习摘要后宣称覆盖。

`generated/`、status/events 视图和本次 Request/Result 不反向成为输入。
真实源码/AC/原绑定证据变化仍由原 Subject 契约决定技术结果是否失效；
仅新增或修改知识用的非主体来源，不强制重跑源码验证。
输入 `issues` 非空或最终候选失效时不得提交成功 Result；先解决缺口，再重发/复用 Delivery。

## 2. 一份 assessment，不增加四套报告

实际阅读并完成各候选判断后，将下列结构通过 `--assessment FILE` 或 `--assessment -`
送入正式命令。文件可用当前临时工作区；成功后正文进入既有 Result，
不默认在 Task 内增加学习、知识、记忆、归档报告。不要把输入文件再登记为知识来源制造循环。
所有 summary/reason 都是专业角色基于实际阅读的判断；CLI 校验覆盖和证据，不能证明任意自然语言判断正确。

| 字段 | 要求 |
|---|---|
| `schema` | `tp-spec.task-learning/v1` |
| `input_digest` | 当前 Request 对应的完整输入 digest |
| `coverage` | 每个输入恰好一项：`input_id`、`digest`、`classification`、实际阅读后的 `summary` |
| `coverage[].classification` | `CURRENT / TEMPORARY / SUPERSEDED / NO_DURABLE_INSIGHT`；SUPERSEDED 必须用 `superseded_by` 指向不同的当前输入，历史仍保留 |
| `knowledge` | 非空候选/处置列表；所有输入至少被一项处置覆盖。相关输入可归一组，不强迫每文件生成一条知识 |
| `knowledge[]` | 唯一 `id`、相关 `input_ids`、`disposition`、具体 `reason`、实际需要的 `queries`；非无价值项还需精确 `knowledge_ref` |
| `memory` | 实际评估的 `summary` 和 `items`；无可沉淀项时 `items=[]` 并填写具体 `no_items_reason`，不是空信号即跳过 |

单项结构示例（占位符必须替换为实际输入；不是可直接提交的完整 assessment）：

```json
{
  "id": "K1",
  "input_ids": ["event:42", "file:requirement.md"],
  "disposition": "DUPLICATE",
  "reason": "实际比较后说明哪些规则已由目标覆盖，以及适用条件是否一致",
  "queries": ["本任务实际主题和术语"],
  "knowledge_ref": "PROJECT-OPS-001"
}
```

```bash
tp-spec knowledge task-converge --task <TASK-ID> --task-dir <TASK-DIR> --db <DB> \
  --workspace-root <PROJECT-ROOT> --request-event-id <REQUEST-ID> --assessment <ASSESSMENT.json>
```

新模式不与旧 `--query / --source / --disposition / --knowledge-ref / --reason-code` 混用。
无新 schema 的旧 Request 仍可用原参数处理；已终态任务只返回其真实终态，不追补新义务。
已采用 `tp-spec.closeout/v1`、但还没有当前 `tp-spec.task-learning/v1` 请求的在途任务，
通过正常 `delivery-converge` 生成/复用请求并接续，不按安装批次名称判断采用状态，
不得伪造 knowledge_signals、手造 Result、删除 closeout marker 或直接修改 Runtime。

## 3. Knowledge 的可核验结果

每个候选由正式命令执行其 `queries`，只查询当前项目和注册 shared。
关闭该次调用的 global fallback，不改变用户通用检索配置；同一次调用相同 query 只查一次。
需要已存在且有来源身份的 Knowledge 投影和可解析项目绑定；缺环境保持待处理，
不在收敛中自动全库 build/scan、安装服务、调用付费模型或运行日常维护链。

| 处置 | 验证 |
|---|---|
| CREATED | 角色先在获准范围内写好精确 canonical；命令读回内容/来源、局部 lint，并只索引该条 |
| UPDATED | 同上，且必须有该 canonical ID 的真实定向命中 |
| DUPLICATE | 实际搜索命中精确 ID，并读回当前 canonical；不复制第二份正文 |
| NO_DURABLE_INSIGHT | 仍需实际读取、非空定向 queries 和具体理由，不绑定伪目标 |

新建/更新的 canonical 要在 `evidence_refs` 绑定本 Task ID 和本候选的准确输入 locator：
文件 ref、`event:<ID>`、`work:<ID>` 等。不能拿本 Task 中无关文件替代该候选的来源。
Result 保留每个候选的检索 receipt、目标路径/内容指纹及适用的单条索引 receipt。
兼容字段 `knowledge_disposition` 按 CREATED、UPDATED、DUPLICATE、NO_DURABLE_INSIGHT
顺序选一项摘要；**完整混合处置以 `knowledge_results` 为准，不能把摘要外推到全部候选。**

Runtime/FTS 是两个存储。命令不写 canonical 或 Memory 正文；索引和检索 telemetry
可能已在正式 Result 前发生。遇到错误查看 `external_effects`，如实区分外部效果与 Runtime
事实，使用现有 journal/reconcile 恢复，不宣称跨库原子回滚，不手工补 SUCCESS。

## 4. 项目记忆与保存结果分开

每个 `memory.items[]` 包含唯一 `id`、`input_ids`、`kind`、`disposition` 和 `reason`。

| 维度 | 可用值/要求 |
|---|---|
| kind | RULE / FACT / PROCEDURE / TEMPORARY / SUPERSEDED |
| disposition | SAVED / COVERED / SKIPPED / NOT_PERSISTED / RETAINED_IN_TASK |
| SAVED、COVERED | 项目相对 `target`、实际 `excerpt` 和 `scope`；命令读取文件确认片段存在、保存 SHA256，不代替专业语义判断 |
| RULE 保存/已覆盖 | `authorization_source` 必须指向本条已绑定输入；它是来源声明，不是自动人工身份认证。角色仍需按现有授权规则判断 |
| FACT、PROCEDURE 保存/已覆盖 | `rediscovery_cost` 说明稳定、可复用且重发现成本较高；PROCEDURE 还需 `created` 布尔值 |
| 新 Procedure | 文件 frontmatter 必须 `status: candidate`，一次成功不能自动转 active |
| TEMPORARY、SUPERSEDED | 只可 SKIPPED 或 RETAINED_IN_TASK，不能升级为永久规则 |
| NOT_PERSISTED | `responsibility` 和 `recovery_condition` 必填；不虚构保存成功 |

目标是准确大小写的根 `AGENTS.md` 或当前项目 `.tp-spec/memory/` 内文件；
保护托管区、先保存目标并读回再精简源条目，由共享方法负责，CLI 不自行改写或移动。
完整 Knowledge 正文不再复制到 Memory。属于本次产品交付物的规则/方法改动仍纳入产品主体。

AGENTS 薄入口的维护与可发现性核对统一按 [项目记忆捕获](../../../skills/capabilities/tp-memory-capture/SKILL.md) 执行。沿用 `memory.summary`、各项 `reason` 和既有 disposition 记录正文与入口的各自处置，不新增 schema 字段：

- 正文与 AGENTS 均有保存/覆盖事实时，分为不同 `id` 的条目，分别填写真实 `target`、`excerpt`，可绑定相同的相关 `input_ids`。各项 `kind` 按实际内容判断，仍满足上表的来源、授权或重发现成本要求，不为增加入口伪造规则授权或新建 Procedure。
- 正文已保存但必要入口未保存时，保留正文的实际结果，入口另记 `NOT_PERSISTED`、责任与恢复条件，不能合并成全部成功。
- 已有入口足够时记录实际覆盖；无需新增入口在 `reason` 中说明，无可沉淀项沿用 `items=[]` 与具体 `no_items_reason`，不制造空条目或强制修改文件。
- `summary`/`reason` 如实说明可发现性核对结果。CLI 的片段读回和 SHA256 不校验问题词语义或目标锚点，不证明宿主发现或 AI 遵守；未核对不能声称通过。

必做评估缺失会待处理；**可选记忆未保存或保存目标后来变化，显示
`ASSESSED_WITH_UNPERSISTED` 和责任/恢复条件，不把它说成未评估，也不无关阻塞全部研发。**
重要规则尚未保存时当前已知约束仍然遵守；授权不清只停止相应行为。

## 5. 复用与最后预检

完整稳定输入、相同 assessment、相同已索引检索上下文与目标读回一致时，重复命令直接返回
原 result ID：不再检索、索引、追加 Result 或刷新 Task 视图。检索身份基于已有投影和注册配置，
不声称自动发现尚未索引的 Vault 文件。中途并发变化在 Runtime 写锁内复查；失败不写半条成功。

输入变化后，新 assessment 只重评变化项。未变的 coverage 可用
`{"input_id":"event:42","reuse_result_event_id":123}`；未变的 Knowledge 或 Memory 单项可用
`{"id":"K1","reuse_result_event_id":123}` / `{"id":"M1","reuse_result_event_id":123}`。
必须来自本 Task 的可信旧 Result，依赖的输入指纹全部相同；Knowledge 还需检索上下文与精确目标未变。
不能按主题相似自动套用旧判断。整体摘要及没有条目的处置原因仍由角色实际确认。

最后再执行 `task complete --check`，检查知识/记忆的真实结果、当前输入及其他交付义务。
只有全部适用事实齐备才正式 complete。终态摘要中的学习结果是已接受候选的历史回执，
不是对后来其他任务的源码或知识库重新认证。
