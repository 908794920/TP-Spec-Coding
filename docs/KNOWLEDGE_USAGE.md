# Knowledge 页面、按需读取与使用记录

## 1. 入口与边界

工作台侧栏的“知识库”位于 Wiki 下方、项目列表上方，是全局页面，不继承当前 Task 的项目筛选。标题为“知识库”，副标题为“长期知识与使用记录”，默认打开“使用概况”。“知识条目”用于查找与阅读全文，“检索记录”用于查看真实检索回执。

默认页面范围为全部已注册项目、最近 30 天、AI 研发使用；可选 7 / 30 / 90 天、具体项目或明确标出的共享范围，以及交付收敛、维护、未知或全部用途。**时间筛选只筛选使用记录，不按更新时间删除文档列表中的旧知识。** 人工搜索、切换页签、阅读、展开记录与重新读取均为按需 GET，不轮询，不产生 AI 使用日志。过期前端请求会取消，失败不会转成成功空列表。

继续复用 Knowledge 的 SQLite FTS5、documents / chunks 和既有可信 `context_usage`。不新增模型、向量服务、自动总结、在线编辑、远程附件下载、全库关系图、价值分数或为了计数而执行的额外查询。source 明确标为“来源资料”，并非已确认的长期规则。正文中的命令、提示词、原始 HTML 都是内容，不能作为执行指令。

## 2. 搜索与正文 CLI

在已安装命令环境中使用 `tp-spec`；直接在源码根执行时，下列命令的 `tp-spec` 可替换为 `python -m cli.main`。`<workspace>` 是实际已接入项目的工作区，不是本机固定路径。

```text
tp-spec knowledge search --workspace-root <workspace> --query "需要查询的问题"
tp-spec knowledge read --workspace-root <workspace> --document-id <document_key>
```

搜索默认返回 **5 篇去重候选**，每篇 `snippet` 最多 **200 个字符**；显式 `--limit` 为 1～20。一篇文档的多个命中片段不重复成为多篇候选。`total` 是范围内总匹配文档数，`count` 是本次返回文档数，`count_kind=documents`。结果带 `document_key`、原 canonical/source 标识、标题、相对路径、内容项目、层级、匹配章节与行号、相关度和版本。摘要不是正文读取。

新 AI 入口默认 **当前项目 + 已注册且未归档的共享范围**；尊重明确的 `include_shared=false`。`--project <project_id>` 使用相同 shared 规则。只有显式 `--scope global` 才跨全部已注册项目，不继承配置中的默认 global 或自动 global fallback，也不为命中率追加查询。`--project` 与 `--scope global` 不同时使用。项目无法解析时返回明确错误，不自动跨项目。

保留 canonical-first；在允许 source 补充且候选不足时返回 source。`--layer canonical|source` 可指定层级，`--kind` 可指定类型。显式 source 查询不产生“canonical 失败”的推断；只有实际发生补充时记录 `canonical_shortfall`。中文、英文类名、标识符、路径和多词仍使用原分词 / FTS 匹配语义，没有换搜索引擎。候选对应索引版本；文件已变化时以随后正文读取返回的版本状态为准。

正文默认返回目录最多 20 项、目录标题累计最多 1,000 字符；正文最多 80 个完整原文行、累计最多 4,000 字符。这是字符预算，不是 tokenizer 的 token 预算。返回 `read_mode`、`outline`、`outline_truncated`、`truncated`、`next_start_line`、`line_start`、`line_end`、`body_start_line`、`total_lines`、`body_returned` 和预算提示。

```text
tp-spec knowledge read --workspace-root <workspace> --document-id <document_key> --start-line 81 --end-line 160
tp-spec knowledge read --workspace-root <workspace> --document-id <document_key> --full
```

显式行号是原文件 1 起始行号，不因去掉 frontmatter 而重新编号。`--full` 与行范围互斥；显式行范围不再受默认字符预算截断，只有 `--start-line` 时默认取从该行起至多 80 行。默认预览和全文不展示 frontmatter；显式范围可以查看原文件的 frontmatter，但只返回 frontmatter 不计正文读取。

目录不把 YAML frontmatter、反引号或波浪号围栏中的伪标题当章节，支持围栏字符与长度判断、ATX / Setext 标题、中文及 CRLF。首个正文行超过 4,000 字符时不跳过：返回目录、`FIRST_LINE_EXCEEDS_PREVIEW_BUDGET_USE_EXPLICIT_LINE_RANGE` 和建议的起始行，须显式按行或全文读取。空正文、仅目录、仅元数据不增加正文读取次数。先确定实际返回范围，再记录一次回执；不存在“先记全文、再由 CLI 截断”的路径。

搜索与读取共同支持：

```text
--task <task_id> --role <role_id>
--purpose development|delivery_convergence|maintenance|unknown
--request-id <logical_request_id>
--no-telemetry
```

Task / 角色只是调用方提供的可选上下文，不创建 Task，不产生 adopted。没有传入就保持缺失。普通 CLI 默认 `development` / `caller=ai_cli`。维护调用应显式声明 `maintenance`。`--no-telemetry` 关闭本次采集；Golden Query 的既有不计数路径继续有效。

### 2.1 旧调用兼容

Python `projection.search()` 仍返回原片段列表，保留配置中的默认数量（后备 20）和旧范围解析契约；不把它改成新候选信封。eval 和新旧 Task convergence 继续调用它。正式 Task 判重保持原数量和项目 + shared 范围，并标注 `delivery_convergence` / `task_convergence`，不混入默认研发指标。

新正式搜索回执不保存 query 明文，而使用 `receipt_contract=tp-spec.knowledge-usage/v2` 与 `query_hash_only=true`。收敛结果验证仍将哈希与实际声明的 query 比对，不能用任意哈希替代绑定。旧明文搜索回执仍按原契约校验，不重写历史事实。正式收敛输入中的用户声明不等同于搜索日志；采集与页面读取不重写或清理 Runtime 历史业务事实。

## 3. 显式升级与恢复

页面、搜索和 read 不建库、不建表、不迁移。旧投影可只读浏览或搜索；未接入新采集契约时返回 `KNOWLEDGE_USAGE_UPGRADE_REQUIRED`，而不是假定已记录。缺库时页面显示缺失，不调用 `init` / doctor / maintain / verify / index build。

对每个**不同的实际 Knowledge 投影数据库**显式执行一次：

```text
tp-spec knowledge index update --workspace-root <workspace>
```

无投影的新安装可显式执行：

```text
tp-spec knowledge index build --workspace-root <workspace>
```

这两个现有入口追加新字段 / 读取记录表、补充稳定文档标识，并刷新内容索引。多个工作区指向同一数据库只需对该数据库升级一次。不需要升级 Runtime 业务表，也不会迁移 Wiki 数据库。精确 canonical 更新入口不偷偷升级日志 schema。

升级前需要备份时使用现有 SQLite 一致性备份流程；数据库仍在 WAL 写入期间，不能只复制主 `.db` 文件冒充完整备份。索引升级 / 重建与本地备份均是显式操作，应用源码补丁不会代为执行。

`build/update` 保留同库 `retrieval_runs` 和 `knowledge_reads`；不再将删除整个投影数据库作为重建或默认回退。失败时保留数据库和日志，修正注册、权限或不可读来源后重新执行同一显式命令；追加升级可重复执行。不要通过清空投影、删除日志、修改风险规则或回填旧事件消除错误。若需要回退代码，保留追加的兼容列 / 表和备份，不删除升级后产生的使用证据。

采集失败不会阻断实际成功的检索 / 阅读；返回 `collection_warning` 和实际采集状态。缺库、旧 schema、写入失败分别可辨认。`KNOWLEDGE_REQUEST_CONFLICT` 和 `KNOWLEDGE_RETRY_RESULT_CHANGED` 是调用一致性错误，不冒用旧成功回执。

### 3.1 追加字段清单

| 存放位置 | 原字段 / 使用统计扩展字段 | 含义与历史处理 |
|---|---|---|
| `documents` | 原 `rel_path/scope/project/kind/canonical_id/source_id/title/sha256/...` 保留 | 原索引与 FTS5 关系不变；SQLite 自增 ID 不公开为永久 ID |
| `documents` | 新 `document_key, metadata_json` | 稳定公开标识及已登记维护 / 来源 / 转换事实；旧元数据缺失不补造 |
| `retrieval_runs` | 原 `id/query_hash/retrieval_mode/fallback_reason/candidate_count/answerability/layer/elapsed_ms/created_at` 保留 | 历史 `candidate_count` 仍是当时片段数，不能改称文档数 |
| `retrieval_runs` | 新 `receipt_id, request_id, request_fingerprint, scope_fingerprint` | 权威回执、逻辑去重与范围指纹；旧行保持 NULL |
| `retrieval_runs` | 新 `task_id, actor_role, purpose, caller` | 可选调用身份与用途；旧未知不直接标为 AI 搜索 |
| `retrieval_runs` | 新 `request_scope, requested_project, requested_projects, returned_projects` | 请求项目、请求包含范围、实际返回内容范围分别保存 |
| `retrieval_runs` | 新 `status, error_code, document_count, results_json, contract_version, count_kind, has_canonical, has_source` | 完成 / 失败、去重文档数、结果 ID / 版本、契约 2 与层级证据；不回填历史 |
| `knowledge_reads` | 新独立表，复用相同 request / receipt / 调用身份 / 范围 / 状态字段 | 与搜索在同一数据库，不复制第二套搜索计数 |
| `knowledge_reads` | `document_key, read_mode, line_start, line_end, body_returned, results_json, elapsed_ms, contract_version, created_at` | 实际返回范围和版本；元数据请求可留回执，但不计正文读取 |
| `build_meta` | `usage_contract, usage_started_at, usage_upgrade_retention_days, usage_retention_days, usage_pruned_before` | 新口径起点、配置与已清理边界；不代表旧数据完整存在 |

`results_json` 使用白名单，保存 document_key、原 ID、标题、路径、内容项目、层级、版本 / 版本类型、片段哈希与行范围等定位元数据，不保存正文、摘要或原查询。查询只保存 SHA-256；固定错误码与 Knowledge HTTP 访问日志不会再次记录原搜索词。哈希可能被猜测，不宣称不可反推。内容索引本来就需要存储文档 / 片段用于搜索；“不存正文”指**使用日志与回执不复制正文**，不是删除 FTS5 资料。

一个逻辑 request ID 只写一条权威搜索或读取记录，跨两类操作也检查冲突。指纹包含查询哈希 / 文档、项目 + shared/global、过滤、数量 / 分页、读取模式 / 行范围以及 Task、角色和用途。相同 ID、相同参数与相同结果版本返回原回执；更改模式、范围、身份、用途或结果版本时明确拒绝。主动重新搜索须用新 ID，未指定时自动生成。去重受实际日志保留期限制，已清理的旧 ID 不能提供永久去重保证。

### 3.2 保留期限

新默认配置为 90 天；已有显式 `telemetry_retention_days` 保持优先，例如明确 30 天仍保留 30 天。原来只继承产品默认值的安装会采用新的 90 天默认，但过去已删除的 30 天以外数据不能恢复。清理只在实际成功写入使用记录时发生，页面不清理；没有写入时，实际现存范围可能比配置期限更长。展示配置天数、新口径起点、现存最早 / 最晚记录以及可比覆盖起点，不能用“可选 90 天”暗示已有完整 90 天历史。

## 4. 文档标识、来源与阅读面板

公开标识形如 `knowledge:<解析来源身份哈希>:<层级和文档身份哈希>`。来源身份基于解析后的 Vault 路径；canonical 使用 canonical ID，source 使用能区分具体文件的相对定位符。重新索引不会因数据库自增 ID 改变而改变公开标识；移动整个 Vault 属于来源身份变化，不把新旧根目录硬猜成同一来源。

source_id 可以对应多个文件。legacy `knowledge:<asset_id>`、canonical ID、原 source ID 和路径只在当前项目 / shared 内唯一对应时关联；一对多保留“未关联”事实，不随机打开其中一篇。非 Markdown 原件展示已有注册元数据；已登记且符合既有 ingest 路径契约的 Markdown 转换件可读，未登记件不自动转换、不抓取原件。虚拟 `@registered/` 与 `@converted/` 路径只代表已登记索引定位符，不是供用户传入的任意磁盘路径。

读取前重新解析实际路径和注册边界；路径越界、编码转义、绝对路径、Windows 盘符 / UNC、目录逃逸和符号链接逃逸会拒绝。转换件还须与当前 source registry 中的 batch、origin_path、project 和实际转换输出路径一致。删除、改名、ID / project 变更或读取过程中版本变化有明确错误。仅目录结果不产生成功正文读取数。

页面显式读取**当前完整正文**，不复用 CLI 的 80 行预览作为全文。目录根据实际渲染标题生成；阅读面板支持已注册内部跳转、返回上篇、关闭 / Escape 后回到原入口焦点，窄屏沿用 Wiki 全屏抽屉布局。只显示局部关系，不建立全库关系图。

Markdown 使用已有安全渲染组件：跳过原始 HTML，不执行脚本 / Shell；远程图片不自动加载。仅允许显式点击 HTTP(S) 外部引用，并标出域名；不自动抓取来源页面、附件或远程图片。内部链接仅指向已注册索引文档，未注册或不支持的链接保持普通内容。证据、source_refs、relations、superseded / replaced_by 只展示已有字段，不推导未记录关系。

检索记录展开时才获取当次结果列表。记录中的当时版本和当前可读取版本分开；`version_kind=chunk` 明确是片段版本，不能称整篇版本。旧行没有结果列表时显示“历史未记录”，不重跑当前检索替代历史，不提供不存在的旧正文。

## 5. 指标口径与未知状态

| 指标 | 实际计算 |
|---|---|
| 已识别 AI 搜索 | 来源为 `ai_cli` / `task_convergence` 且符合所选用途的完成逻辑搜索；默认只看 development；一次多结果仍一笔 |
| 有结果占比 | 至少一篇去重文档的完成搜索 / 完成搜索；无样本为“—” |
| 执行失败 | 参数 / 索引等执行错误单列，不计成功零结果，不刷新最近成功搜索 |
| 正文读取 | 受支持入口实际返回非空正文或正文片段；候选摘要、仅目录、元数据、空正文不计 |
| 已记录采用任务 / 条目 | 复用已有可信 `knowledge + adopted`；按解析 Runtime / Task 和资产去重 |
| 最近活动 / 日趋势 | 成功搜索、实际正文读取、可信 adopted 分开；时间解析为带时区时间比较，日趋势按 UTC+8 日期归组 |

采用不是命中、阅读、检索评分、验收通过或维护完成。不从检索结果自动生成 adopted，也不给旧采用补造 receipt。采用是独立证据，不随检索用途筛选；没有可靠用途的旧采用不能强行推断为研发或收敛。可保留没有回执、无法关联现存文档的可信历史采用。

请求 alpha 项目并返回 shared 内容：项目表归因 alpha，内容列表标 shared。来源 / 投影数据库 / Runtime 先按解析后的身份去重，不因重复注册工作区复制次数。同一来源多个数据库的内容只采用一个可用投影，日志按数据库与回执去重，并明确警告，不把各投影伪装成互不相关的知识库。

选择共享范围时，统计实际返回共享内容或显式请求共享的记录，仍保留请求项目身份。因为无法从该切片重建“未命中共享”的完整分母，共享范围不显示有结果占比。跨多个独立索引的 BM25 不直接比较：文档统一 canonical 优先，再按来源分组，来源内部按相关度 / 标题排序；数据库端计数、去重和每页 20 条查询，不把全库先读到 Python 再截断。

旧日志缺请求项目时只在全局“历史未归因检索”展示可证实数量，不进入单项目，也不均摊给每个项目。旧 `candidate_count` 不作为新去重文档数。旧记录可在“未知用途 / 旧记录”或“全部用途”的记录页看到；没有历史搜索词全文检索入口。新旧口径起点分别展示，不拼接成完整趋势。

检索 / 读取日志状态与任务采用状态独立。`available / partial / missing / unavailable / legacy / not_collected / disabled` 分别表示可用、部分可用、缺库、读取失败、旧契约、未接入和关闭采集。新日志可用但真实调用为零，可以显示 0；缺库或无法采集不得据此显示“使用了 0 次”。存在部分正向记录时显示已知计数，并保留范围缺失提示；没有已知记录且覆盖不完整时显示“—”。

“采集起点”是新契约升级时间，不是第一条实际使用时间。采用来源最早事件只是最早现存任务事件，不证明历史采用采集完整。配置不足 90 天、新启用来源、缺失数据库或不完整注册均显示覆盖不足。无时区的旧时间仅按 UTC 兼容解析，不通过字符串排序假装统一时区。

待关注仅包含已有过期 / 冲突 / 替代状态、缺少已记录来源证据、真实多次读取但无已记录采用，或相同匿名查询在相同范围连续零命中等事实。不据此判定无价值、不执行修订。维护摘要只读现有索引元信息、注册来源和已有报告的时间 / 状态；没有运行新的健康扫描。

## 6. 只读接口

统一响应使用 `tp-spec.workbench/v1`、`context=null` 与 `read` 元信息；各 Runtime / 索引为独立只读快照，实时文档不承诺跨来源原子一致。部分来源失败有 `problems` 和独立来源状态；错误不是成功空列表。

| GET 路径 | 参数 / 行为 |
|---|---|
| `/api/knowledge/overview` | `project, days, purpose`；概况、状态、最近活动、趋势、项目表、常用条目、维护事实 |
| `/api/knowledge/documents` | 上述范围 + `q, layer, kind, maintenance, adopted=1, page`；每页固定 20 篇，默认不限制更新时间 |
| `/api/knowledge/document` | `id, days, purpose`；已注册全局文档全文、来源、局部链接与使用记录 |
| `/api/knowledge/records` | 范围 + `status=all|hit|zero|failed, task, hash, date, page`；哈希小写十六进制前缀至少 4 位，日期按 UTC+8 筛选 |
| `/api/knowledge/records?receipt=...` | 使用返回行的 `key` 定位并按需展开当次结果；保留同一筛选上下文 |

页面 `project` 是接口返回的来源 + 项目组合 key；CLI `--project` 是 Knowledge 注册项目 ID，不能混用。请求参数限制长度 / 页码且 SQL 使用绑定参数；未知路径 404、非法参数 400、写方法 405 / `Allow: GET`。访问日志对 Knowledge query string 进行省略，HTTP 错误不回显原搜索词。返回来源状态不转发完整本机配置或原始注册解析异常。

所有 GET 使用现有库的 `mode=ro` 连接，无 DDL / 迁移 / SQL 业务写入，无 Runtime 事件、使用记录或 Wiki 变更；不调用完整 `projection_status()`、doctor、maintain、verify、build/update。没有 `record_telemetry=False` 后再走普通建表连接的伪只读路径。

**SQLite WAL 的文件层边界：**现有 Runtime 的只读 SQLite 连接仍可能创建或更新 SQLite 协调文件 `-shm` 和空 `-wal`，它们不是新的业务事件或使用回执。因此“业务只读”不等于目录中每个文件都零变化。保持现有只读连接，不用 `immutable=1` 忽略活动 WAL，也不为页面复制整个 Runtime；当期文件对比结果和未满足的严格零写入条件见 [历史验证记录](../CHANGELOG.md#history-knowledge-usage)。

## 7. 本地接入与验收边界

实现批次的输入快照、实际检查、失败与未执行项统一保留在 [CHANGELOG](../CHANGELOG.md#history-knowledge-usage)。该记录只证明当期范围，不代表当前全部页面、Windows 或真实任务已验收；也不能据其早期环境限制断言后来从未验证。

应用源码先按 [安装与升级说明](GETTING_STARTED.md) 核对本次交付基线。仅在依赖需要准备/更新或对应检查尚未完成时使用原锁文件安装，并分别执行类型检查与构建；需要升级实际知识投影时，按第 3 节显式执行 `knowledge index update`。页面本身不代替索引升级；不要修改真实知识来制造统计样本，也不要为了证明采集额外执行研发查询。

现场按本次影响选择：375px 与桌面、明暗主题、长标题、筛选说明、三页签/筛选/分页、全文/内部返回/Escape 焦点、快速切换请求取消、失败/空状态和远程图片不请求；共用导航受影响时再核对 Wiki、配置、Task 搜索及项目导航。Windows 路径大小写、junction/UNC、真实 Vault/Runtime 来源、历史保留、可信采用及真实任务体验需用相应环境验证。

记录实际环境、操作、结果与未执行项，隔离夹具不是产品历史数据。补丁交付不自动关闭 Task，不替用户完成人工验收；需要依靠真实任务证明的体验在代码可供应用后反馈，不全部前置为提供试用代码的门槛。
