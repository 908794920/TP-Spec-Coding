# 本地工作台：启动、数据接口与开发

## 当前能力与边界

在 TP-Spec-Coding 自身源码根目录启动，不在每个业务仓库复制前端。提供项目总览、任务工作区、全局配置三个页面，以及真实 WorkItem 关系图、实际流程区、四类详情、验收/证据适用性、按需结单预检、时间线和刷新异常处理。W05 已退出旧卡片专属链路，只保留本地 Web 可视化入口和既有纯文本/JSON 查询。源码可供本地安装后验证；文末保留云端浏览器/构建限制，不将源码交付描述为真实交互已通过。

页面只读现有注册表、Binding、Runtime 和工件。没有项目时显示真实空态，不插入演示数据；缺少数据库时返回缺失，不创建、修复或迁移。普通 CLI 运行不会启动工作台。

## 环境与启动

Python 沿用基座 3.10+ 及根 `requirements.txt`。前端 Node.js 范围为 `^20.19.0 || >=22.12.0`，精确依赖以根锁文件为准。

首次准备运行依赖（已有正确环境无需重复安装）：

```bash
python -m pip install -r requirements.txt
npm ci
npm run dev
```

默认浏览器地址 `http://127.0.0.1:5173`；API 自动选择空闲的本机端口。实际地址、源码根和 API PID 会打印到终端。浏览器访问前端地址，由前端代理 `/api` 到本次 Python 实例。不要单独执行 Vite 后期待它自动找到任意已运行的 API。

```bash
npm run dev -- --port 5180
npm run dev -- --port 5180 --api-port 8765
npm run dev -- --help
```

不开放远程监听选项，不安装系统服务，不自动打开浏览器。退出使用 `Ctrl+C`；启动器只停止自己创建的进程，端口冲突时不会杀占用端口的其他服务。单端启动失败会关闭另一端并非零退出。

Python 选择顺序：`TP_SPEC_PYTHON` → 活动 `VIRTUAL_ENV` → 本项目 `.venv` → 系统 `python`（Windows）/`python3`（其他平台）。`TP_SPEC_PYTHON` 是解释器路径或可执行文件名，不是带参数的 shell 命令。路径通过参数数组传递，支持中文与空格；Windows 平台行为仍需在用户本机实际验证。

例如已在项目根创建 `.venv` 时，PowerShell 可显式指定：

```powershell
$env:TP_SPEC_PYTHON = (Join-Path $PWD '.venv/Scripts/python.exe')
npm run dev
```

启动器固定加载本目录的 `cli.workbench.server`，同时校验 Python readiness、实例身份与 `/api/health`。源码位置不是已配置安装位置时，不会自动替换安装配置。全局页面中的 `base` 是安装声明；`active_source_root` 与 health 的 `source_root` 才是本次执行源码；能力拓扑使用本次源码。

## 数据选择与真实性

上下文键由正式 project id、注册项目根、选中工作区和实际 Runtime 路径共同生成。工作区来自 Registry 或现有 Workspace Inventory + Project Binding，不根据 Task 名称或磁盘扫描猜测归属。

Runtime/注册表位置沿用基座现有解析，包括已经支持的 `TP_SPEC_USER_ROOT`、`TP_SPEC_REGISTRY` 等变量。没有配置时工作台不代替用户执行 `project init`。页面每次进入对象或点击“重新读取”发起 GET，不轮询、不生成事件。跨上下文取消旧请求并清空旧显示；同上下文刷新失败保留旧内容与原读取时间，同时提示失败。

Task 的数据及路由共用一次 SQLite 只读事务，项目索引也使用请求内事务。配置、任务工件和证据仍是文件系统实时读取，**不承诺 SQLite 与这些文件形成跨介质原子快照**。响应的 `read.consistency` 与 `read.note` 明确此边界。

任务基础快照的历史验证摘要仍标记 `current_applicability=not_evaluated`，不能仅凭其 PASS 判定当前通过。只有用户打开非概况详情后，才另行读取证据/绑定与当前适用性；画布拖动、缩放和搜索不触发这些检查。WorkItem 来自 `work_item`；Work Session 来自既有事件。基线未提供完整 Work Unit/Agent Thread 绑定时 `data_support` 明确为 `not_provided`，不按 Wxx 名字推断或改名。

字段敏感键处理复用旧展示策略，不另建账户、权限或数据脱敏框架。HTTP 接口不接受任意文件路径，不提供命令执行或写入动作。

## 三页面与关系图使用

| 页面 | 内容 |
|---|---|
| 项目总览 | 项目身份、Binding、任务统计、搜索/状态筛选索引、Wiki/Knowledge 及注册表来源 |
| 任务工作区 | Task 上下文、当前/下一步和实际适用阶段、WorkItem 关系图、四类详情、可折叠 Task/明确绑定 WorkItem 事件 |
| 全局配置 | 安装与活动源码、Wiki、Knowledge、Workspace、Resolver、Registry、自主配置、能力来源及已注册项目字段 |

图中的 `WorkItem` 不改名为 Work Unit。每条已取得工作记录的 `task_id` 来自既有查询 `WHERE task_id=?` 的正式范围；节点身份还包含上下文键、Task ID 和对象类型。归属边框不表示执行依赖，依赖箭头从前置工作指向后续工作。Task 自身状态只读其正式记录，不根据所有工作项完成自动变绿。

没有工作项时仍显示 Task；没有实际阶段时不套用完整 L3。ID 类似 Wxx 不产生关系。悬空引用、重复身份、循环、记录类型异常会列出问题：不制造占位工作，不把歧义边画成已确认边，原始记录保留在详情/异常区。循环中的原边仍显示；异常布局不代表该流程可执行。

画布支持放大/缩小、拖动平移、适配、重排、搜索定位、选中项上下游高亮、收起工作项或下游、展开全部，以及视觉坐标调整。节点/边的业务新增、删除和重连均关闭；图内不运行命令、不写事件。定位隐藏结果会先展开再定位。`current` 工作项标志不解释为执行者在线，也不据此猜测正在处理哪项工作。

节点可聚焦，Enter/空格打开概况；Escape 或“关闭”返回节点，节点已隐藏时返回搜索框。实际流程与工作依赖分区显示；“定位当前步骤”只定位 Resolver 的当前阶段，当前缺失时不拿下一步填充。时间线明确标注读取范围：Task 基础响应最多最近 50 条。选中 WorkItem 时，仅按正式 `work_item_id` 在已取得记录中筛选，不按摘要猜测；没有筛选结果不等于没有其他历史。Verification/Review/Owner/Delivery 各自最多展示最近 20 条结果历史，均标明总数与返回数。

布局采用 `graph/layout.ts` 单一、确定性的从左到右分层算法；只处理本 Task 的工作依赖，不把阶段/归属混入依赖排序，也不增加 Dagre/ELK 多引擎。相同拓扑更新状态时保留坐标、缩放和选择；首次打开、手动重排或正式拓扑改变才重新布局。此处坐标不是 Runtime 字段。

宽屏使用导航/画布/详情组合；1100px 以下详情改原生对话框抽屉，800px 以下导航折叠，520px 以下进一步收敛工具栏和字段布局。目标视口为 1440/1024/715/480 CSS px；规则已实现，但四档真实浏览器检查本批尚未执行。详情和表格独立滚动，状态有文字，不只靠颜色；系统字体，无外部字体/CDN。

## 详情、证据和结单解释

点击节点后提供“概况 / 阻塞 / 验证与验收 / 证据与交付”。概况使用当前 Task 快照；首次进入其他标签才请求 `/details`，之后可以手动重新读取。WorkItem 概况属于所选对象，但验收、验证、交付和预检明确属于父 Task，不借用父结果替 WorkItem 签字。

| 信息 | 展示含义 |
|---|---|
| Task 正式状态 | 读取 Runtime；工作项都完成、Delivery READY 或预检 ready 不会改变它 |
| Verification | 原记录结论与当前适用性分列；复用当前验证读取、subject 与产品 ChangeSet 校验，保留 technical/full 范围 |
| Review | 复用现有可信 CODE Review 判定；不跳过新失败去续用旧 PASS，不将未细分错误猜成具体 stale 原因 |
| Owner | 原始 accept/defer/waive、有效 AC、视觉 AC、来源和绑定分别展示；不扩大实际人验覆盖范围 |
| 验收矩阵 | 来自 acceptance.md 的声明、见证、方法和证据；文件写 PASS 不等于可信验收通过 |
| 证据引用 | 每次引用保留事件、字段与原哈希；可定位的任务内文件核对实际字节，旧裸路径不猜锚点；哈希相等不证明内容或验收结论 |
| Delivery | 当前匹配与历史 READY 分开；没有单独“用户接收交付”事实时不从 Owner 验收或 READY 推断 |

在“阻塞”标签中点击“读取结单预检”才调用现有 `record_first.completion_check()`。页面完整保留其实际返回的 blockers、acceptance_issues、route，不自行计算门禁，不运行 Verify/Review/Complete。没有返回责任方或恢复条件时显示未记录；路由责任方不能套给所有问题。当前 Runtime 没有细分的原因仍以原始返回表达，也不承诺此接口已穷举所有独立门禁。

读取时间分别对应画布、详情、预检。`read.task_revision` 仅是 Task 行与最新事件 ID 的账本观察摘要，不是产品/证据文件的原子版本。标识不同时页面提示不能拼为同次快照；即使相同，也不承诺文件系统原子性。读取中已发现验收声明变化/消失时，返回部分结果，并撤回“当前适用”的展示结论，提示重新读取，不修改账本。

页面上的“重新读取”会更新已打开的数据；从未请求的详情/预检不会为了刷新后台预先运行。读取失败保留原内容、原读取时间和失败提示。接口返回其他上下文/Task、过时请求或不匹配展示契约时不会覆盖当前页面。跨 Task 清除旧选择与详情；同 Task 状态刷新沿用 W03 的同拓扑坐标/视图，不自动重排或抢焦点。实际 React 生命周期、焦点和四档宽度仍待本地浏览器验证。

## 只读 API

| GET 路径 | 数据 |
|---|---|
| `/api/health` | 本次源码、版本、Python、Registry 路径及实例身份；不代表所有项目都可读 |
| `/api/global` | 全局配置、注册项目/工作区上下文及读取问题 |
| `/api/projects/{context_key}` | 指定上下文项目概况及完整 `task_index` |
| `/api/projects/{context_key}/tasks/{task_id}` | 正式任务、WorkItem、Work Session、现有流程和基础证据投影 |
| `/api/projects/{context_key}/tasks/{task_id}/details` | 按需读取验收声明、可信结果、适用性、等待及证据文件核对 |
| `/api/projects/{context_key}/tasks/{task_id}/closeout` | 显式调用既有 `completion_check()`；不运行 verify 或 complete |

`health` 以外的成功结果为 `{schema, context, read, data}`；schema 为 `tp-spec.workbench/v1`，不是 Runtime schema 升级。错误为 `{schema, error:{code,message}, failed_at}`，读取失败不附伪成功时间。缺对象 404；上下文/工件冲突 409；不可读 503 或 500；非 GET 动作返回 405。响应 `Cache-Control: no-store`。

`/details` 与 `/closeout` 使用各自请求内只读事务，并沿用既有 Runtime 判断。没有用户显式请求时，不执行结单预检。

## 开发、构建与 Git

```bash
npm run dev
npm run check:types
npm run build
```

三者相互独立，不串联测试。`build` 仅生成 `ui/workbench/dist/`，不是生产部署，也不等于 `file://` 可用；本版默认使用本地工作台启动入口。没有安装依赖时先 `npm ci`，不应为了通过命令临时换依赖版本。

修改页面见 `ui/workbench/src/`；统一样式变量见 `styles/tokens.css`；查询见 `cli/workbench/`。只维护 `cli/workbench/` 这一份展示查询和敏感键处理，不再保留旧 cards 调用者或 HTML/宿主适配。

`package.json`、`package-lock.json`、前后端源码及配置入 Git。`node_modules`、`dist`、`.vite`、虚拟环境、`*.tsbuildinfo`、`workbench-logs` 不进入 Git 和基座无 Git 产物扫描；没有默认持久服务日志。Wiki 源码枚举沿用已配置的排除目录并在进入目录前剪枝。

验证按 [TESTING.md](TESTING.md) 只覆盖当前改动，临时测试执行后清理。不创建永久测试套件，不因 commit/push/构建/交付自动运行全量测试。

## 依赖及验证边界

第三方依赖与锁文件来源见根 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。W02/W03 云端已分别执行当期改动的局部验证；W04 定向覆盖真实 CLI 夹具的详情/预检/Owner 范围、文件变化、只读不变性、接口身份和请求乱序。临时用例执行后移除；合成夹具不是用户人验结果，纯函数/请求替身检查也不是浏览器交互证明。W02—W04 因云端无法取得 npm 包体，**没有真实 Vite/React 浏览器运行、生产构建或锁定工具链完整类型检查的通过结论**。W05 仅为字段覆盖补齐 Task 概况中的最近 checkpoint、原摘要/来源及已有工作段，不改前端依赖或启动器；该处只做局部语法/字段接入核对，未把它写成浏览器或完整类型检查通过。此前环境缺口仍留在本地验证清单。

锁文件经 npm 离线归一化和 `ci --dry-run` 图检查，不代表包体已下载。首次联网 `npm ci`、真实 `npm run dev`、构建/类型检查及 Windows 体验，随本地统一合并阶段验证；这一环境缺口不会被写成 PASS，也不要求每批先本地验收才能继续。

## 旧展示退出与信息去向

W05 删除 `cli/cards/`、`tp-spec card global/project/task`、`tp-card-display` 及对应角色/导航。旧 `TP_SPEC_CARD_*` 输出变量、inline fragment、Web Artifact marker 与宿主降级不再消费，也不增加同义 CLI 或隐藏模式。唯一可视化启动是仓库根 `npm run dev`；`task get`、`workflow next`、`report` 和其他纯文本/JSON 查询保持原职责。

| 原有效信息/呈现字段 | 当前承载位置或删除理由 |
|---|---|
| 全局 base/version/user_root、安装声明与实际源码 | 全局配置“当前读取身份”与“安装与基座”；health 给出本次解释器与实例 |
| 全局 wiki/knowledge/workspace/resolver/registry | 全局配置对应字段组，保留 configured/source/缺失与错误原值 |
| 全局 registered_projects/autonomy/skill_topology | 全局配置已注册项目、自主配置和能力来源；拓扑仅移除已退役展示角色 |
| 项目 project、Binding、版本、registry | 项目总览身份与 Binding、注册表来源 |
| 项目 wiki/knowledge、task_statistics、summary | 项目总览内容系统字段、统计和说明 |
| 项目进行中/归档/完成任务集合 | 同一查询的完整 task_index＋状态筛选；不需要维护重复任务表 |
| Task 身份/状态、summary/来源、latest_checkpoint、已有工作段 | 任务上下文、节点“概况”的 Task 最近记录与工作段及原始事实；负责人缺失不补造 |
| workflow 当前/下一步、阶段和来源 | 独立实际流程区；不拿下一步填充缺失的当前步骤 |
| blockers/verification | 阻塞、验证与验收详情；历史摘要与当前可信结果分开 |
| evidence/timeline | 证据列表与按需时间线，保留来源/原哈希和读取截断范围 |
| title/generated_at/health/problems | 页面标题、读取时间、数据问题和部分/不可用提示 |
| card_type、HTML路径、fragment、截断宿主样式 | 旧渲染选择和输出载体，删除；页面类型由前端导航决定，不是 Runtime 事实 |

历史 `.tp-spec/card/` 的 Git/目录扫描排除继续保留，只为防止旧 HTML 重新进入源码集合，不是可调用的兼容链；不在用户磁盘清理旧预览。Wiki 的 `concept-card` 是独立内容类型，与本次退出的 HTML 卡片不是同一对象，保持不变。历史 Changelog、已有测试报告、旧 CLI 诊断也不改写为新事实。

项目 `.tp-spec/README.md` 的源模板已更新；已安装业务项目不会在打开工作台时被改写。需要同步时仍由用户明确授权后使用现有 Base 同步流程，不把本次源码 Patch 当成现场迁移授权。
