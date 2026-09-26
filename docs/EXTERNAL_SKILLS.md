# 用户级外部 SKILL

外部 SKILL 是用户维护的 Markdown 方法包，不属于 Base 的内置 Role Catalog，也不是业务项目的 `.tp-spec/memory/skills`。`/tp-spec-coding` 通过共享目录发现并按需读取；工作台后端使用同一读取逻辑。不创建新 Domain、Role、Runtime 表或宿主原生斜杠命令。

## 存放与接入

根目录沿用 `environment.user_tp_spec_root()`：默认 `~/.tp-spec`；已有 `TP_SPEC_USER_ROOT` 时使用该用户级根。不是当前业务工程的 `.tp-spec`。CLI 与工作台进程须使用同一用户根；环境变量不同会读取不同目录。

```text
<用户级 .tp-spec>/
├─ installation.yaml             # 原有安装配置，不添加外部 SKILL 字段
├─ external-skills.yaml          # 可选登记与覆盖
└─ external-skills/
   ├─ java-review/
   │  ├─ SKILL.md
   │  └─ references/
   └─ legacy-tool/
      ├─ 使用说明.md
      ├─ references/
      └─ scripts/
```

用户把原始来源包放入 `external-skills/<目录>/`。默认只发现各包根部的 `SKILL.md`，不递归扫描其他目录或业务仓库。有标准入口无需额外登记；普通 Markdown 或不同入口名使用可选配置。查询不会创建上述目录或配置，也不会执行包内脚本。

目录名决定稳定 ID，例如 `external:local:java-review`。名称相同不等于同一个 ID，也不会覆盖内置能力；改目录名会改变 ID。目录名及配置键必须是单个有效目录名，不接受路径、`.` 或 `..`。原文件无需改名或补齐 TP 内置 Role metadata；保留相对资源结构。

## 可选登记

```yaml
schema: tp-spec.external-skills/v1
skills:
  legacy-tool:
    entry: 使用说明.md
    name: 遗留 Java 工程分析
    description: 用于理解旧 Java 工程的调用链、模块职责与重复代码。
    enabled: true
    applies_to:
      - tp-code-reviewer
  java-review:
    enabled: false
```

登记字段覆盖入口 front matter 的同名字段；未覆盖字段取可用原值。`entry` 是登记文件中的定位字段，相对于对应包根，不从第三方 metadata 的 `entry` 推断入口。

| 字段 | 省略时的含义 |
|---|---|
| `entry` | `SKILL.md`；必须是本包内 Markdown 路径 |
| `name` | 原 metadata 名称，再回退目录名 |
| `description` | 原 metadata 描述，再回退空值；不凭正文猜测用途 |
| `enabled` | 原 metadata 的布尔值，再回退 `true` |
| `applies_to` | 原 metadata 的领域／角色 ID 列表，再回退空列表 |
| `upstream` | 原 metadata 的上游说明，再回退空值；不联网补齐 |
| `version` | 原 metadata 的版本声明，再回退空值；不是 Base 活动版本 |

支持 UTF-8、UTF-8 BOM、LF／CRLF 和多行 YAML 描述。普通 Markdown 不强制 front matter；有 front matter 时必须能够解析，重复键或不闭合不能当作有效配置。入口中的未知第三方字段不要求转换成 TP 字段，也不解释成执行授权；外部登记配置仅接受上表字段和 `schema/skills` 顶层结构。数字目录名或 YAML 隐式布尔名称（如 `on`、`off`）作配置键时需加引号。

`applies_to` 仅声明关联，支持现有领域 Agent 或正式 Role 的 ID。没有关联仍是可独立发现的能力；关联目标未知时报告问题，不生成虚假连线。关联不增加正式角色、不要求该角色必跑，也不是实际调用次数。

## 发现与读取命令

下文 `tp-spec` 表示当前 Base 的 CLI。可在 Base 根运行 `python -m cli.main ...`；从业务工作区运行时使用已解析的 Base 入口，例如 `python "<BaseRoot>/cli/main.py" ...` 或已有 PowerShell 包装器。不要为了能力查询切换项目身份、初始化项目或同步项目入口。

```text
tp-spec skill list
tp-spec skill list --query external:local: --json
tp-spec skill list --query Java --json
tp-spec skill read --id external:local:java-review --json
tp-spec skill read --id external:local:legacy-tool --path "references/调用链.md" --json
```

列表只输出发现信息，不向模型输出所有正文。无筛选时 JSON 保留合成目录的 `root_id/nodes/edges`，schema 为 `tp-spec.skill-catalog/v1`；`problems` 与 `external` 携带外部来源问题和位置。`--query` 对 ID、名称、描述、来源类型、上游及关联字段作文本筛选，不是语义搜索；筛选后的列表不是完整拓扑，也不能用匹配数量充当总数。

`read` 按精确 ID 读取，不按同名回退；默认读取入口，`--path` 是所属来源根内的 Markdown 路径。正文 JSON 为 `tp-spec.skill-document/v1`，包含实际 `id/path/content`、`source_kind/source_root`、`status/enabled`、`entry_path`、名称、上游、版本及 SHA-256。不可用目标返回非零退出码；JSON 中提供 `error_code/message`。不存在外部配置不影响内置读取。

`content_sha256` 是本次实际读取文件原始字节的 SHA-256（含 BOM、CRLF）；`content` 去除 UTF-8 BOM 后返回正文。外部 `entry_sha256` 对应目录读取时的入口字节，不代表整个来源包或脚本集。多文件读取不是原子快照；如用户同时修改来源，应重新查询，不把目录描述与随后读取的不同内容强行解释成同一版本。内置目录没有外部入口指纹时保留空值，不生成虚假指纹。

<a id="entry-handoff"></a>
## 入口选择与领域转交

开始或继续实际工作时，先按既有规则识别 Domain，再用一次 `skill list --query external:local: --json` 获取当前外部摘要；在同一轮向角色转交时复用结果，不逐工具重复查询。纯状态查询不强制加载外部目录；用户询问外部能力时再定向读取。恢复会话、新一轮使用或明确发生来源变化时重新发现，不能用旧会话的可用状态继续使用已停用或移除的内容。

选择顺序：用户显式 ID 优先；否则仅依据可用项的名称、非空用途描述及已声明适用范围选择相关候选。缺描述（`auto_selectable=false`）不能靠猜正文用途自动采用，但用户可按精确 ID 点名。显示名称重名、用途冲突或确实无法定位时只澄清影响选择的事项；没有匹配时继续已有内置路径，不为凑外部调用而强选。元数据选择不是专业正确性结论，目标领域仍判断方法是否适用。

选中后执行 `skill read --id <精确ID> --json`，只加载需要的正文和引用。向 Domain／执行 Role 传递以下已有读取结果，而不是另建持久登记：原始用户请求、能力 ID、`source_kind/source_root`、`entry_path/path`、`status/enabled`、`content_sha256`，以及当前需要的方法正文或准确定位。当前上下文已包含这次真实读取结果时不重复读取；执行前发现目标已改变则重新读取。

领域转交到具体 Role、子工作或既有专业 Skill 时保留选中的外部能力与来源，不因重回内置 Catalog 而丢弃它。直接调用领域、未经过产品入口时，也在开始实际工作时使用同一摘要与读取步骤。若外部方法不适用或与已确认任务约束冲突，说明具体原因，不静默换成另一个同名能力。

停用、缺失、无效、读取失败时不得以缓存旧正文或人工浏览接口替代执行读取；只停止依赖该能力的动作，其他已有授权且不依赖它的工作可继续。读取不自动执行脚本、安装依赖、扩大工作范围、替代专业判断或取得新的写入／审批权限。`route` 的领域识别职责与参数不变，不把外部能力注册为独立 Domain。

## 来源状态与刷新

| 状态 | 解释与处理 |
|---|---|
| `available` | 当前入口可读；不代表内容正确、依赖齐备或宿主执行已验证 |
| `disabled` | 用户已停用；正常 CLI／入口读取拒绝，仅支持显式人工只读检查 |
| `missing` | 仍有登记，但入口文件缺失；不返回上次正文 |
| `invalid` | 配置、metadata 或来源定位无效；按具体原因修正该来源 |

未登记且已移除的来源在下次列表中消失；仍登记的缺失来源留在列表中说明原因。单条错误不影响其他有效项；整份配置损坏或存在重复键时明确报告外部异常，不忽略配置并重新启用本来停用的自动发现项。内置目录仍可读。

每次 CLI 查询、工作台目录读取或正文请求解析当前来源，不用跨请求正文缓存，不需要重启服务。切换进程的用户根环境变量则需要以相同环境重新启动进程。既有宿主会话是否缓存了旧入口指令须在本地新会话确认；TP 的目录发现不等于宿主已自动注册每个外部 SKILL。

## 工作台后端与正文接口

`GET /api/global` 的 `data.skill_topology` 使用与 CLI 相同的合成目录，保留内置 ID、边及顺序。`source_root` 指当前活动 Base，外部来源根看 `external.root` 和各节点 `source_root`。外部 `problems` 留在能力来源区域；可选配置异常不把仍可读的内置拓扑标成整体不可用。

正文继续使用 `GET /api/skill-documents/{id}`。客户端须分别编码整个 ID 和查询值，不把 ID 中冒号、中文或空格当作路径结构。

| 参数 | 语义 |
|---|---|
| `path` | 可选，内置内容相对 Base 且须在发布清单中；外部内容相对该包根 |
| `allow_disabled` | 默认 `0`；仅人工检查停用内容时显式传 `1`，响应仍为 `status=disabled`、`enabled=false` |

重复的 `path/allow_disabled`、无效的检查标志返回 `400 INVALID_QUERY`。检查标志不允许读取缺失、无效或越界内容；CLI 没有借用此标志执行停用能力的入口。

成功结果保持 `tp-spec.workbench/v1`，直接返回 `{schema, id, path, content, ...来源字段}`，**不是** `{context, read, data}` envelope。错误继续为 `{schema, error:{code,message}, failed_at}`；响应 `Cache-Control: no-store`。完整工作台边界见 [工作台说明](WORKBENCH.md#只读-api)。

相对 Markdown 链接由客户端基于当前文档的 `path` 解析到同一 `source_root`，URL 解码与锚点处理在客户端完成；不要将原始 `#锚点` 拼入文件参数，也不要把外部相对路径解释到 Base。只读文本上限为 512 KiB。图片和脚本保留在包内，不通过此接口执行或提供任意二进制预览。

## 页面阅读与来源跟踪

在全局配置打开“能力定义与来源”，可切换拓扑图和层级树。两种视图使用同一目录，并显示内置／外部、来源状态和精确 ID；关系数量是声明数量，不是调用统计。外部配置问题在此区域说明，不隐藏仍可读的内置节点。

已声明关联的外部能力随对应领域／角色展示；“外部能力（未关联）”在图的独立列和树的独立区域展示，不伪造拥有关系或执行连线。图中同一个来源只画一个节点，树中共享来源会在各个声明父节点下出现。名称相同的来源按 ID 区分。

图中选择节点后点“查看设定”；树中每个节点均可直接查看。详情使用同一个来源感知阅读器，展示来源目录、入口与当前文档、声明上游／版本、实际正文指纹和入口指纹。用途及关联属于最近一次目录声明，不把它们当成执行事实。节点选择和详情按钮可通过键盘操作。

相对 Markdown 可在所属来源内跳转、定位锚点及返回上一篇；中文、空格及编码后的特殊字符按来源内路径解释。跨来源路径、非 Markdown 和带查询参数的文档链接不在此阅读器中打开。外部网页仍以普通网页链接打开；图片只显示替代文字，脚本不执行。

页面顶部“重新读取”重新查询目录；来源新增、停用、移除后用此入口刷新。目录重新读取或发生失败时不继续打开旧目录的设定。详情内“重新读取正文”独立查询当前文件；读取中或失败后不把上次正文显示为本次成功内容。两种读取均不轮询、不要求服务重启；需要切换用户根环境变量时重新启动相应进程。

已停用来源默认不加载正文。人工明确点击“只读查看停用内容”才传入检查标志，成功后仍醒目标明停用；这不会启用来源或产生采用记录。缺失或无效来源只能看到实际错误，不使用上一次正文兜底。

上述为实现与操作说明，不是浏览器、Windows 或真实宿主的验收结论。类型检查、构建、实际页面交互与真实采用分别验证。

## 解耦与排错

新增、更新、停用或移除外部 SKILL 不需要修改 Base 源码、内置 Catalog、Manifest、业务项目 `AGENTS.md` 或项目 binding。不复制能力到业务工程、不创建安装用软链接。Base 升级和源码回滚不清理用户的外部包及配置；不会自动撤销真实任务中已授权执行的业务修改。

共享能力加载器和工作台查询不写 Registry、Binding、Runtime、外部原件、安装配置或使用统计。CLI 主进程仍按现有机制在用户级 `diagnostics/cli/` 写计时回执；不要把“能力只读”解释成整个 CLI 进程没有任何文件写入。查询不代表 `adopted`，不把外部方法自动归为项目 Memory、Knowledge 条目或 Wiki 事实。

| 现象 | 定向核对 |
|---|---|
| 列表找不到能力 | 确认进程用户根；标准文件须在包根叫 `SKILL.md`，其他入口须登记；不要扫描业务仓库补目录 |
| `SKILL_DISABLED` | 检查来源是否确实停用；执行者不能用 `allow_disabled` 绕过它 |
| `SKILL_MISSING`／`NOT_FOUND` | 前者是登记仍在但入口缺失，后者是 ID 已不在当前目录；核对真实来源，不使用旧正文 |
| `EXTERNAL_CONFIG_INVALID`／`SKILL_INVALID` | 根据列表问题核对 YAML、重复键、字段类型和来源路径；不要删掉配置来掩盖错误 |
| 内置相对引用 `DOCUMENT_NOT_PUBLISHED` | 链接必须在当前 Base Manifest 中；外部原件无需加入该 Manifest |
| CLI 可见而页面不同 | 核对工作台 health 的活动源码、用户根及实际请求；用页面顶部“重新读取”更新目录，并检查来源区域的局部问题 |
| 入口未采用 | 核对是否是新会话、入口指令已更新、描述是否为空、实际选中 ID 和读取错误；不声称目录读取已证明宿主集成成功 |

Windows 原生路径、既有宿主缓存及真实业务任务效果由用户在本地验证。只读目录、HTTP 接口、前端交互和真实采用是不同证据层级。
