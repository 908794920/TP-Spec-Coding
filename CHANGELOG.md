# Changelog

## [5.3.4] Open Release Line — 2026-09-20

### 升级源码交付 — 2026-09-21（非发布/全版验收）

- R1：九角色薄入口、专业方法抽取及精准挂载；视觉方法适配并保留来源/许可，交付与共享 Memory 方法可按需进入。
- R2：显式 Task 步骤、独立角色参与、Work/Fix 结果与精确接收、实际集成候选；父流程前向，修复后在原步骤复验；工作台同源只读详情与筛选。
- R3：Git stable_ref 固定 commit snapshot、增量影响与零 LLM 快路径、成功基线和异常恢复；不切换/污染工作区，保留 FILESYSTEM。
- R4：安全提案/原始人工来源/范围版本绑定，Work/计划/测试/Review/effect 消费约束；不把发现、建议、actor 字符串或已落盘内容当授权。
- R5：只读多缺口预检，真实证据适用性、轻量 L0/L1 Delivery、每 Task 有效输入提炼和项目记忆评估；稳定输入幂等，历史标记兼容。
- R6：紧凑同源接续/终态/工作台派生视图，缺失、过期与生成失败可见，不改写历史原件或增设多套总结。
- P6：修复有效 Work 集成候选在结单预检中因重复 `issues` 参数变成 UNKNOWN 的错误；补验实际 Fix→候选→提炼→正式结单及终态重放，候选缺失/产品或证据变化仍正确拦截。同步公共 Runtime API、安装兼容与能力导航，保留既有 5.3.4 版本和 SQLite schema。
- 本轮只做影响范围内的临时检查并清理，不恢复全仓测试/CI。锁定 npm 依赖在云端不可取得，前端类型检查、构建和真实工作台浏览器交互尚未通过；Windows、现场安装与业务人验另行记录，不以源码交付代签。

### 迁移源支持扩展 — 2026-09-21

- `cli/migrations/__init__.py` 的 `SOURCE_CONTRACTS` 增加 **5.3.2**：`project upgrade-contract` 与 `task migrate` 现可从 5.3.2 收敛到活动契约 5.3.4。此前 5.3.2 不在表内，已升至 5.3.2 的项目只能停在旧契约（`UNSUPPORTED_MIGRATION_SOURCE`），并经 binding/doctor 长期报告 `SYNC_REQUIRED`。
- 依据：在**隔离副本**上用真实项目数据（idc 的 DB 与 `TASK-22513`）完成端到端干跑，`SOURCE_CONTRACTS` 注释要求的四条同时成立 —— schema（副本 `integrity_check=ok`、`schema_version=1`）、身份（project/task 身份与 `status.yaml` 一致）、角色/工件形态（`task.md`/`status.yaml`/`requirement-clarifications.md` 三件 5.3.2 → 5.3.4；`map_active_owner` 对规范角色为 no-op）、事务（journal + 迁移事件 + 非追溯祖父化）。迁移后任务四方校验（`status`/`event_ledger`/`handoff`/`generated`）全 `ok`、`issues=[]`，`release_gate` 由 `BLOCKED` 转 `PASS`，未产生新漂移。
- 语义不变：`SOURCE_CONTRACTS` 仍是"有限支持"集合，采用仍以可信事件为准，不因版本字符串放行；`governance/compat-matrix.yaml` 只声明活动契约，未新增字段（其 schema 拒绝未知顶层键），`schema`/公共 Task 状态未变。
- 已知差异（cosmetic，不影响任何门禁）：模板 footer 的 prose 版本标记（如 `task.md` 的 `> V5.3.2：…`）不随迁移改写 —— 该函数只重写精确的契约/模板引用，按设计不处理自由文本。

### 原开放版本线记录

- 从 **5.3.3** 收敛到 **5.3.4** 版本线：`VERSION`、治理契约、Role Catalog、Agent/Skill frontmatter、CLI/schema 声明与活动模板统一升级；活动模板目录切换为 `templates/5.3.4`，不再保留 `templates/5.3.3`。
- v5.3.3 已正式发布（本地可视化工作台取代卡片 UI + antd v6 界面成熟化 + 侧栏项目树/技能拓扑/中文呈现 + 卡片链 W01-W05 退役）；本行作为后续功能开发的开放版本线，Role-first 产品形态与各 Formal Role 活动契约不变。

## [5.3.3] Open Release Line — 2026-09-14

- W05：完整移除旧 HTML 卡片命令、模板/渲染器、inline/Web Artifact 及专属展示角色，清理路由、快照 card_type 和新 CLI 诊断中的 card 区段；既有历史诊断和用户 HTML 不删除。
- W05：工作台是唯一可视化入口，使用根目录 `npm run dev`；纯文本/JSON 查询与 Runtime 验证/验收/结单规则保留。更新字段去向、入口文档、角色拓扑与源码 Manifest；交付五批增量和原始基线到最终源码的累计 Patch，不代表用户已合并、验收或发布。
- W05 字段覆盖对照补齐 Task 概况的最近 checkpoint、原摘要/来源及已有工作段；未改前端依赖或启动器。此前尚未执行的真实浏览器、锁定构建/完整类型检查及 Windows 项继续留待本地，不因最终交付自动运行全量回归。

- W04：新增按需只读详情接口和四类详情，分别展示 Verification/Review、Owner 逐 AC 处置、验收声明、证据每次引用的哈希、Delivery 与正式状态；按需呈现现有结单预检的完整实际返回，不重写 Runtime 门禁。
- W04：刷新采用上下文与请求身份，失败保留原数据/时间，跨项目同名 Task 与乱序响应不会覆盖当前界面；增加读取版本差异、事件截断和验收声明读取竞态提示。真实 React/Vite/浏览器及 Windows 验证仍待本地，未据局部测试声明全系统通过。

- W03：在 W02 本地只读服务基础上，新增项目总览/任务工作区/全局配置、正式 WorkItem 归属与依赖图、独立实际流程、概况与 Task 时间线；图浏览不改变业务关系，异常关系明确保留。新增 React Flow 精确依赖及唯一轻量分层布局，未新增 Runtime 模型。
- W03 当前仅声明源码和适用局部验证结果，真实 Vite/React Flow 浏览器、锁定构建/类型检查与 Windows 项待本地；W03 交付时详细验收/证据解释及旧卡片完整退役分别安排在 W04/W05；当前 W04 实施见上。

- W01：移除基座历史测试、测试开发依赖、pytest 发现配置及自动测试 CI / PowerShell Full 入口；基座验证策略统一为当前功能的临时局部检查，结束后清理，不因提交、推送或交付自动全量回归。
- 保留 Runtime 验证、业务任务指定测试执行与已有报告接收能力；Role Catalog 和 Manifest 随本次源码清理同步。W01 当期未实现工作台；卡片产品入口仍保留到 W05。

- 从 **5.3.2** 收敛到 **5.3.3** 版本线：`VERSION`、治理契约、Role Catalog、Agent/Skill frontmatter、CLI/schema 声明与活动模板统一升级；活动模板目录切换为 `templates/5.3.3`，不再保留 `templates/5.3.2`。
- v5.3.2 已正式发布（owner acceptance `accept` 模式 + v5.3.2 运行时契约集成 + 卡片渲染修复 + 只读路由在 canonical 工件不可解码时不再崩溃）；本行作为后续功能开发的开放版本线，Role-first 产品形态与各 Formal Role 活动契约不变。

## [5.3.2] Open Release Line — 2026-09-06

- 从 **5.3.1** 收敛到 **5.3.2** 版本线：`VERSION`、治理契约、Role Catalog、Agent/Skill frontmatter、CLI/schema 声明与活动模板统一升级；活动模板目录切换为 `templates/5.3.2`，不再保留 `templates/5.3.1`。
- v5.3.1 已正式发布（Graphify Provider M2 No-Go + Requirement Frontier + strict-marker 门禁与 Windows 发布验证）；本行作为后续功能开发的开放版本线，Role-first 产品形态与各 Formal Role 活动契约不变。

## [5.3.1] Open Release Line — 2026-08-31

- 从 **5.3.0** 收敛到 **5.3.1** 版本线：`VERSION`、治理契约、Role Catalog、Agent/Skill frontmatter、CLI/schema 声明与活动模板统一升级；活动模板目录切换为 `templates/5.3.1`，不再保留 `templates/5.3.0`。
- 继续维持 Role-first 产品形态：`tp-spec-coding` 唯一默认产品入口、`tp-software-lifecycle` 软件工程 Domain Agent 与各 Formal Role 的活动契约不变。
- Graphify Provider Spike 在固定 `graphifyy==0.9.53` / commit `33362d969292b57eda82f3fbd9eb5f3f5bc9bbc2` 上因 dangling endpoint 未通过上游 validator；M2 正式 **No-Go**，不实现 Source Graph v1，不增加 Graphify 运行时依赖、Adapter 或替代 AST。
- v5.3.1 后续增量范围收敛为 **Requirement Frontier**：仅在复杂 L2/L3 的前置依赖决策中启用，复用现有 requirement-clarification 与按需 Requirement 工件，L0/L1 默认路径不增加问卷或状态。
- 修复发布测试漂移：公开 Domain Agent 契约纳入既有 `tp-card-display`，v5.2.9 migration 回归面向当前活动契约而非写死 5.3.0。

## [5.3.0] Open Release Line — 2026-08-29

- 从 **5.2.9** 收敛到 **5.3.0** 版本线：`VERSION`、治理契约、Role Catalog、Agent/Skill frontmatter、CLI/schema 声明与活动模板统一升级；活动模板目录切换为 `templates/5.3.0`，不再保留 `templates/5.2.9`。
- 继续维持 Role-first 产品形态：`tp-spec-coding` 唯一默认产品入口、`tp-software-lifecycle` 软件工程 Domain Agent 与各 Formal Role 的活动契约不变。

## [5.2.9] Development & Delivery Governance — 2026-08-29

- 开发习惯收敛为“先调查、优先复用、最小修改、可读实现、真实验证、及时清理”；外部 AI 已完成实现后默认进入只读 Test/Review，无真实 Finding 时允许 `No findings` / 不修改。
- Development / Verification / Code Review / Delivery 统一绑定真实 `change_set_id`；产品内容变化后旧 PASS 自动失效，Code Review 非 PASS 显式返工 Development。
- Completion 要求所有 AC 明确处置；数据库声明升级为可重复 `database_operations`；UI AC 通过 Visual Manifest 绑定真实浏览器 Evidence，Delivery READY 拒绝未清理临时工件。
- 状态投影新增 scope change、blocker/finding、quality facts 与 terminal manifest；终态目录可只读检测漂移，不追溯改写历史。
- Knowledge 收敛改为 `KNOWLEDGE_CONVERGENCE_REQUEST/RESULT` typed effect，由 `tp-knowledge` 执行 targeted project+shared search；旧 `NO_CHANGE/DEFERRED` 不再充当新任务结论。
- 活动契约从 **5.2.8** 升级到 **5.2.9**；`templates/5.2.9` 成为唯一活动模板。已终态 5.2.8 Task 保持只读；在途任务先 `project upgrade-contract`，再显式 `task migrate`，缺少 Change Set 的旧 Development/Verification/Review 事实按 stale 重新执行。

## [5.2.8] Open Release Line — 2026-08-28

- 从 **5.2.7** 收敛到 **5.2.8** 版本线：`VERSION`、治理契约、Role Catalog、Agent/Skill frontmatter、CLI/schema 声明与活动模板统一升级；活动模板目录切换为 `templates/5.2.8`，不再保留 `templates/5.2.7`。
- 继续维持 Role-first 产品形态：`tp-spec-coding` 唯一默认产品入口、`tp-software-lifecycle` 软件工程 Domain Agent 与 9 个 Formal Role 的活动契约不变。

## [5.2.7] Open Release Line — 2026-08-26

- 任务事件展示与工作流判断改为结构化事实：`summary` 仅用于人类阅读，正式 CLI 自动记录 Event Semantics，并保留可信旧契约的确定性兼容。
- 文档入口统一到根 README 与 `docs/README.md`；Domain Agent 导航按 Role Catalog 校验/生成，当前发布面不再承载临时实施计划和迁移过程材料。

- 从 **5.2.6** 收敛到 **5.2.7** 版本线：`VERSION`、治理契约、Role Catalog、Agent/Skill frontmatter、CLI/schema 声明与活动模板统一升级；活动模板目录切换为 `templates/5.2.7`，不再保留 `templates/5.2.6`。
- 继续维持 Role-first 产品形态：`tp-spec-coding` 唯一默认产品入口、`tp-software-lifecycle` 软件工程 Domain Agent 与 9 个 Formal Role 的活动契约不变。
- Role Catalog 新增生成型 `topology` 投影：把 Product Entry → Domain Agent → Formal Role → Capability Skill 关系固化为可校验 `nodes + edges`，节点统一提供稳定 `id` 与显示 `name`；运行时支持按 id/name 直接查询，Global Config 卡片新增 Agent / Role / Skill 关系展示。图谱由既有 catalog/subskills/Skill metadata 生成，不新增第二事实源、数据库、MCP Server 或后台服务。
- 卡片展示契约收敛为 `tp-spec.card-display/v1`：显式 `card global/project/task` 与 Runtime 自动刷新共享 `CARD_DISPLAY` 结果语义，显式 `--inline-output` 优先于单进程 `TP_SPEC_CARD_INLINE_OUTPUT`；Artifact/fragment 失败继续 best-effort 降级且不改变已成功 Runtime 命令，`--json` Runtime stdout 保持纯机器 JSON。
- `tp-card-display` 提升为独立只读卡片 Domain Agent：只在用户明确请求显示卡片时消费官方卡片结果，并按宿主真实能力选择会话内 fragment、固定 Web Artifact 或离线 HTML；`tp-software-lifecycle` 仅保留 Runtime 刷新触发策略，两侧共享当前 Base 的卡片渲染入口。
- 工作流卡片新增治理展示投影：`governance/orchestration.yaml` 统一维护 stage/action/confirmation 的用户显示标签，Role 名称继续复用 Role Catalog；任务卡片改为“当前步骤摘要 + 响应式时间线”，raw id 仅保留在可访问的技术详情中，机器路由字段保持不变。
- 任务卡片“依据”升级为只读 Evidence View：优先使用结构化 `evidence_items`，legacy 裸路径保持未验证而不再猜测“项目根目录”，绝对/越界/根逃逸路径显式标为不安全；按 `(anchor, normalized_path)` 聚合来源，并展示原始路径、可复制路径、关联事件与当前可验证状态，不修改历史 event 或正式 Evidence PASS 语义。

## [5.2.6] Open Release Line — 2026-08-21

- 从 **5.2.5** 收敛到 **5.2.6** 版本线：`VERSION`、治理契约、Role Catalog、Agent/Skill frontmatter、CLI/schema 声明与活动模板统一升级；活动模板目录切换为 `templates/5.2.6`，不再保留 `templates/5.2.5`。
- 继续维持 Role-first 产品形态：`tp-spec-coding` 唯一默认产品入口、`tp-software-lifecycle` 软件工程 Domain Agent 与 9 个 Formal Role 的活动契约不变。
- 新增只读离线 HTML 信息卡片：`tp-spec card global/project/task` 从现有 Installation/Registry/Binding/Wiki/Knowledge/Runtime/Orchestration 事实生成一次性快照；正式 Runtime 步骤成功后 best-effort 刷新单一 Task 预览，不新增状态机、数据库、后台服务或网络依赖，卡片失败不改变原命令结果。
- 稳定化卡片宿主展示：继续保留既有离线 HTML，同时覆盖当前工作区固定 `.tp-spec-preview/card/index.html` 作为 Web Artifact；导航与时间线统一使用 `button`/`hidden`，移除程序化滚动恢复并改为卡片内部滚动，降低嵌入宿主时的页面跳动；不引入 MCP Server、后台服务或第二套事实源。
- 新增会话内 HTML 片段输出：三种显式卡片支持 `--inline-output`，正式 Runtime 白名单步骤支持单进程 `TP_SPEC_CARD_INLINE_OUTPUT`；Skill 在命令返回 `INLINE_VISUALIZATION` 后于同一次回复输出宿主引用，优先显示在会话中，并保留 Web Artifact/离线 HTML 两级降级；片段严格限制在 1 MB 内，超限时仅截断片段并显示提示。
- 临时测试工件治理：`execution-temp` 迁移到系统 Temp 下按 `project/task/run` 隔离的 machine-owned 根，使用 `~/.tp-spec/temp-artifacts` JSON ownership manifest 记录 `ACTIVE/CLEANED/CLEANUP_PENDING`；`work end` 与 Task `complete/cancel` 做幂等清理，崩溃/重启后的已登记残留可通过只读 `temp orphan-check` 识别并显式重试清理，历史/未登记 `.tmp` 只报告不自动删除。
- 临时工件安全边界：创建与清理均拒绝路径穿越、父级 symlink/Junction/reparse point 与所有权冲突，递归清理不跟随链接目标；用户原始输入、intake、正式 Task/evidence/Memory/Runtime 投影不纳入临时清理。并发 run 使用独立 run_id，`CLEANUP_PENDING` 仅为临时工件状态，不扩展五态 Task Runtime。
- Work Session 耗时修正：`report stage-time` 改为按既有 `detail_json.session_id` 配对交错的 `WORK_SESSION_STARTED/ENDED`，按 `actor_role` 汇总可测 session 时长并显式报告 unmatched session；不再把事件间隔或 waiting end reason 伪装成工作/等待耗时，SQLite schema 与事件模型保持不变。

## [5.2.5] Open Release Line — 2026-08-20

- 从 **5.2.4** 收敛到 **5.2.5** 版本线：`VERSION`、治理契约、Role Catalog、Agent/Skill frontmatter、CLI/schema 声明与活动模板统一升级；活动模板目录切换为 `templates/5.2.5`，不再保留 `templates/5.2.4`。
- 继续维持 Role-first 产品形态：`tp-spec-coding` 唯一默认产品入口、`tp-software-lifecycle` 软件工程 Domain Agent 与 9 个 Formal Role 的活动契约不变。
- `tp-spec-coding` 的用户可见 Skill 名称校准为 `tp-软件生命周期`；稳定 `id` / `role` / 物理路径与内部 `tp-software-lifecycle` Domain Agent 均不改名。
- 直接接入 Microsoft MarkItDown 0.1.7 作为本地文件→Markdown 转换运行时：新增显式 `tp-spec document convert` 与 Knowledge batch `ingest convert`，成功转换只生成 machine-owned intake、不越权决定 canonical truth，源文件 hash 漂移 fail-closed，单文件转换失败进入 quarantine。

## [5.2.4] Role-first Personal AI Software Engineering System — 2026-08-18

- 将软件研发能力从 **Action-first** 正式迁移为 **Role-first**：需求分析、架构设计、开发、验证等旧 Action Role 归位为正式软件工程角色拥有的能力；旧 7 步的轻量流程经验继续通过 L0～L3 / lifecycle preset 保留。
- 新增 `tp-spec-coding` 作为唯一默认产品入口，使用 signal-driven / low-context Domain routing；新增 `tp-software-lifecycle` 作为唯一软件工程 Domain Agent，不建立第二套 Workflow Runtime。
- 物理目录同步收敛为产品层级：`entry/tp-spec-coding` 单独承载产品入口，`agents/` 只保留 Domain Agent，正式工程角色迁入 `skills/roles/`，共享能力迁入 `skills/capabilities/`，Autonomy 专项能力迁入 `skills/autonomy/`，`role-catalog.yaml` 归入 `governance/` 活动契约；不保留旧物理路径兼容层。
- 建立 9 个 canonical Formal Role：`tp-product-manager`、`tp-software-architect`、`tp-tech-lead`、`tp-security-engineer`、`tp-development-engineer`、`tp-database-engineer`、`tp-test-engineer`、`tp-code-reviewer`、`tp-integration-engineer`。
- 保持五态 `NEW/ACTIVE/BLOCKED/COMPLETED/CANCELLED`、phase-as-fact、Record-first、CLI-first、L0～L3、UltraPlan、UltraReview、Autonomy Execution Envelope、Wiki/Knowledge/Base 与恢复/迁移安全边界；未引入 Lifecycle/Gate/Role 第二状态机。
- Requirement Ready 之前允许 Product Manager 在 pre-task 阶段规范化客户一句话/文档；已有成熟 Requirement 可直接进入 Task，简单 Bug/Code Task 仍允许 L0 快速路径。
- 将 Test、Code Review、Security、Database、Integration 责任拆成正式角色；Architecture Review 继续由 Architect capability 承担，但正式 PASS 必须使用 isolated execution context 与 subject binding。
- Orchestration 的 `mode` 从旧 Role ID 硬绑定迁移到 capability contract；`effects` 继续按 assignment 维持 `repo_mutation` 等 fail-closed 边界。
- Code Review 增强确定性 Review Package / line locator 与 machine-readable `REVIEW_COMPLETED`；Delivery 与 Knowledge qualification 解耦，Task-scoped Knowledge convergence 归 `tp-knowledge`。
- v5.2.3 旧 Role、legacy long-state transition/commit 逻辑仅保留于 migration/history；active Runtime 执行 repo-wide no-tail DEFAULT DENY。历史 Task/Event 原始 actor_role 不追溯改写。
- 活动契约通过 `project upgrade-contract --to 5.2.4` + `task migration-plan` + `task migrate --to 5.2.4` 正式迁移；`templates/5.2.4` 为唯一当前模板契约。
- 继续以治理增量开销 `<=5%` 为产品预算：Role/Sub-Skill 不因存在就强制执行，不为 Sub-Skill 调用建立独立账本，不因可推导非关键 metadata 缺失回退补账。

## V5.2.3 Autonomous Maintenance + Runtime Hardening — 2026-08-16

- 按项目所有者明确要求，活动契约从 **5.2.2** 收敛到 **5.2.3**；该版本承载 Runtime Hardening 与长期项目自治维护，不因功能体量自动改名为 5.3.0。
- Runtime Hardening：补齐 Project Identity 防串账、Task Create crash recovery、same-task writer serialization，并收窄 durability 声明为 process-crash recovery。
- 新增 `tp-project-autonomy` 薄控制入口与 `tp-autonomy-setup/cycle/review/integrate` Skills；Autonomy 不复制 `tp-workflow-orchestrator`，普通研发 Task 继续走现有治理。
- 新增用户级 Autonomy Profile、独立 Git clone 的长期 Autonomous Workspace、canonical Wiki/Knowledge 只读复用、generation-fenced Cycle、Task discovery/dedup、薄 Batch、Task→Git commit 绑定与累积 staging line。
- 新增 Stage Effects / Execution Envelope：`repo_mutation` 表示 mutable repo 的任何 git-visible 写入；无人值守 `requires_human` 一律 fail-closed，用户确认最快下一 Cycle 生效。
- 新增只读 Inbox/Review 与 Canonical Integration Prepare/Verify/Apply；多 Repo Apply 使用 journaled recoverable Integration Set，拒绝目录覆盖和未验证 Apply。
- 外部 Scheduler 只负责触发；真正 Executor 必须能访问本地 Workspace/Git/Python/Agent。`max_new_tasks_per_cycle` 是上限而不是 quota，0 Task 是合法结果。

## V5.2.2 Context Effectiveness + Runtime/Wiki Hardening — 2026-08-15

- 正式将单活动契约从 **5.2.1** 收敛到 **5.2.2**：`VERSION`、治理契约、Role Catalog、Agent/Skill frontmatter、CLI/schema 声明与活动模板统一升级；活动模板目录切换为 `templates/5.2.2`，不再保留 `templates/5.2.1`。
- Workflow Confirmation Hardening：用户级 `material` / `each_stage` 策略统一走可信 `WORKFLOW_CONFIRMATION`，普通边界与 material 边界使用不同 confirmation kind；确认绑定上游事实与 route digest，返工或上游变化后旧确认自然失效；Wake Prompt 保持短指针，不复制完整上下文。
- Structured Delivery Convergence：L2/L3 只有结构化 `DELIVERY_RESULT` 才能完成交付；`CREATED/UPDATED/NO_CHANGE/DEFERRED/BLOCKED` 具有明确机器语义并绑定当前 Verification subject；Knowledge 检索/校验/index 均为 targeted 路径，普通 delivery checkpoint 不再解锁完成。
- Wiki Daily Hardening：`base namespace-migrate` 覆盖 resolved central Wiki machine metadata 的 namespace/schema token；新增 `wiki anchors-doctor` 与受控 `wiki anchors-repair`，仅在 committed source baseline 仍当前时允许重建缺失 anchor，source drift 时继续 fail-closed。
- Context Effectiveness / Retrieval Observability：正式 Task 可在既有 checkpoint/review/verify/delivery 写入中附加 best-effort Context Usage receipt，统一观测 Wiki、Knowledge、Project Memory、Project Skill 的 Retrieved/Adopted；只读 `report context-effectiveness` 通过 Runtime 事实推导 Effectiveness proxy，telemetry 失败永不成为 correctness gate。
- SQLite Runtime schema 与公开 Workflow state **不变**；没有新增 Context DB、Context Gateway、后台 Miner/Daemon、Workflow Stage 或审批。Knowledge 中央 retrieval telemetry 因没有 project/task attribution，不被错误归因到项目级报告。
- 旧项目和在途 Task 不由 Base Release 自动改写：项目继续通过 `project upgrade-contract --to 5.2.2` 与现有 `task migrate` 显式升级；历史 release/Task/evidence 由 Git 与既有迁移边界保留。
- Release Convergence 重建 Role Catalog 内容哈希与 `manifest.sha256`，并以 Version Purity、Role Catalog、Manifest、Portability、pytest Full Gate 与 Windows Full Gate 作为发布门禁。

## V5.2.1 Hardening + Opportunistic Project Memory — 2026-08-14

- 正式将当前单活动契约从 5.2.0 收敛到 **5.2.1**；`VERSION`、治理契约、Role Catalog、Agent/Skill frontmatter、CLI/schema 声明与活动模板统一升级，活动模板目录切换为 `templates/5.2.1`。
- Workflow Hardening：普通角色切换提供轻量 transition notice 后自动继续；material confirmation 未解决时保持 fail-closed，不允许静默进入 Development；UltraPlan 仅由 Architecture Design 组织，UltraReview 仅由 Verification Engineering 组织。
- Development 边界收紧：新增测试必须可追溯到 AC/直接改动/回归/已发现缺陷/明确风险；禁止开发阶段自行扩张为独立 Review/UltraReview；注释聚焦 Why / Constraint / Risk，避免机械注释。
- 新增项目级 **Opportunistic Project Memory**：`.tp-spec/memory/INDEX.md` + `PROJECT.md` + `skills/`；Memory 是可重建热缓存/项目经验层，不替代 Source、Runtime、Knowledge 或 Git 真源。
- Memory 采用 **No Evidence, No Memory** 与机会式捕获：只有自然出现高价值、跨会话可复用且重新发现成本高的事实/方法时，流程角色才按需加载内部 `tp-memory-capture`；不暴露 `tp-learn`、不加定时器、Miner、队列、Memory DB 或新的 Workflow 阶段。
- `tp-delivery-convergence` 只对本 Task 已触碰的 Memory fragment 做轻量去重/压缩/证据检查；未触碰 Memory 时 0 额外动作，Memory 缺失或失败永不成为研发 blocker。
- SQLite Runtime schema **不变**；历史 Task/evidence 不重写。已有 5.2.0 在途项目/Task 按现有 `project upgrade-contract` + 显式 task migration 链迁移，不建立第二状态机。
- 发布收敛重新生成 Role Catalog 内容哈希与 `manifest.sha256`，并以 Version Purity / Role Catalog / Portability / Full Gate 作为最终发布门禁。

## V5.2.0 TP-Spec-Coding Public Release — 2026-08-12

- Windows 发布适配收口：统一 machine-local path identity（包含 symlink/Junction/Windows 8.3 短路径别名），修复 Project bootstrap 与 Runtime Registry migration 的字符串路径误判；CLI/版本扫描器建立 UTF-8 stdio 边界，GitHub Windows CI 显式启用 UTF-8；字节门禁以仓库 `.gitattributes` + manifest 为权威，不再强制用户全局 `core.autocrlf=false`。
- 项目正式更名为 **TP-Spec-Coding**，对外首页、治理名称、CLI 帮助与核心 Agent/Skill 说明统一品牌。
- 正式开源采用 MIT License，新增 `LICENSE`、`CONTRIBUTING.md`、`SECURITY.md`、`CODE_OF_CONDUCT.md`、GitHub Actions CI 与可复现 Python requirements。
- README 重写为公开项目入口：先说明项目价值与优势，再提供快速开始、4 个对外 Agent、开发组长 + 7 个内部专业 Skill、Record-first、UltraPlan/UltraReview、跨机器迁移和安全边界。
- GitHub 发布面补齐贡献、安全、行为准则、PR/Issue 模板与 Linux + Windows CI；`project init` 同时创建 portable `project-binding.yaml`，并在已有 binding 身份冲突时 fail-closed，保证 README 的“初始化 → sync-project → 跨机器恢复”路径真实可执行。
- 新增 `docs/GETTING_STARTED.md`，覆盖全新机器空配置、AI 辅助路径配置、项目接入、Workspace Inventory、项目搬迁与跨机器恢复。
- 公共配置示例清空：Installation roots、Workspace Inventory、Runtime Registry 默认均不携带样例项目或作者机器路径；空 Installation profile 作为合法“未配置模板”可被 loader 读取，再由 `base configure` 填充。
- 清理公共仓库发布面：移除旧内部升级报告与个人 Knowledge legacy filename，portable 检查不再携带用户指纹 token；公共默认不包含 Runtime DB、机器 Registry、用户 Wiki/Knowledge 数据。
- 单活动契约切换到 5.2.0：治理文件、Role Catalog、Agent/Skill frontmatter 与 `templates/5.2.0` 同步升级，SQLite Runtime schema 不变，旧在途 Task 继续走官方 project/task contract migration 链。
- Version Purity 扫描器补齐“上一 minor”检测：当前 5.2.x 活动面出现 5.1.x 等旧 5.x token 会被识别，历史证据仍通过精确 allowlist 保留。
- 正式发布面补强：恢复首发提交遗漏的 `.github/` Actions / PR / Issue 模板，并新增 Git-index 级 `update_manifest.py --verify-release`；发布候选必须已 `git add -A`，防止“本地工作树验证通过，但新增点目录未进入最终 commit”的假绿。
- 修复 B18 cutover 回归在普通用户/Linux CI 下的清理权限缺陷：目录解除只读时保留 execute/search 位，避免 root 本地测试假绿、GitHub Actions 因临时目录无法遍历而失败。
- 完成命名空间收敛（`ai-work` → `tp-spec`）：新增一次性 `base namespace-migrate`（plan/apply）把 `.ai-work/`、`~/.ai-work` 与 `ai-work.*` schema 迁移到 `.tp-spec/`、`~/.tp-spec` 与 `tp-spec.*`；新旧命名空间共存时 fail-closed，不猜测权威副本。正常运行时不再回退到 legacy namespace。
- 新增稳定 machine-local `tp-spec` 启动器（`cli/launcher.py` + `scripts/tp-spec{.ps1,.cmd,}`）与 Windows 用户级 PATH 持久化；新增 `cli/namespace_migration.py`、`docs/MIGRATION_V520_NAMESPACE.md` 与 `project-entry/tp-spec-readme.md`。
- 新增 PowerShell 交接/基座自检脚本 `scripts/Invoke-TpSpecHandoff.ps1`、`Invoke-TpSpecHandoffFlush.ps1`、`Test-TpSpecTask.ps1`、`ci/Test-TpSpecBase.ps1`。
- 新增命名空间迁移/收敛/最终一致性三组回归：`test_v520_namespace_migration.py`、`test_v520_namespace_purity.py`、`test_v520_final_convergence.py`；全仓既有测试同步收敛到 tp-spec 命名空间。

## V5.1.4 Workflow Orchestrator — 2026-08-12

- 新增 `tp-workflow-orchestrator` 作为研发流程默认控制入口：基于现有 Task 事实与 `max(risk_level, flow_level, machine_risk_floor)` 解析 L0～L3，只决定下一阶段、下一角色、深度模式与关键确认，不编写业务方案/代码、不承担 Review、不直接写 Runtime。
- 新增 `governance/orchestration.yaml` 与只读 `ai-work workflow next|doctor`；`workflow.yaml` 继续只负责公开状态/phase/Runtime 边界，不恢复旧微状态机，也不新增 workflow DB/task/event system。
- 正式收敛开发入口：`tp-workflow-orchestrator` 是唯一开发流程 Agent；7 个研发专业 role ID 保持稳定并迁入 `skills/tp-*`，由 `agents/role-catalog.yaml` 继续作为唯一 role → `skill_path` 权威。`tp-base-maintenance` / `tp-knowledge` / `tp-wiki` 继续作为独立专业 Agent，框架仍允许使用者扩展新的专业 Agent。
- UltraPlan / UltraReview 保留在 `tp-architecture-design` / `tp-verification-engineering`：支持隔离并发子代理时优先并发，不支持时采用相同 evidence pack 的隔离顺序降级，避免答案污染且不因缺并发能力阻塞。
- 默认确认策略收敛为 `material`：普通阶段切换不记账；真实用户决策复用既有 `DECISION`，真实阻塞复用 `task block/resume`，阶段/验证事实继续复用 `checkpoint/verify`。
- 修复 V5.1.3 发布基线：3 个 human-owner Skill frontmatter、Role Catalog 结构化校验/Hash 刷新、README 断链、Full CI 缺少完整 pytest 等问题。
- Cutover snapshot/rollback 纳入 `governance/orchestration.yaml`，确保未来契约升级可完整回滚；活动模板切换至 `templates/5.1.4`，SQLite schema 保持不变。
- Workflow 返工路由按事件新鲜度失效旧下游完成事实：Architecture Review `REVISE`、Verification `NEEDS_FIX/FAIL` 完成返工后可继续复审/复验，上游新事实也会使旧 material confirmation 失效，避免循环或误跳阶段。
- 新增 V5.1.4 Orchestration contract/router/integration/adversarial/upgrade 回归；完整 Python 回归全绿。
- 修复 Windows Full CI 的机器态污染：Wiki 标准化回归显式隔离用户级 `installation.yaml`，Base Convergence 回归隔离真实 `registry.local.json`，避免开发机现有 `~/.ai-work` 配置覆盖临时 fixture 造成假红。
- 修复真实 V5.1.3 在途任务迁移漏项：凡根工件显式声明 `artifact_contract.version` 都纳入迁移集合，迁移后再次检查全部显式 contract；`tech-design.md` 不再遗留旧版本却错误报告 SUCCESS。
- 风险下限增加权限/安全/敏感信息访问控制 L3 信号；Orchestrator 只读提高路由等级，真正的风险升级由 `tp-architecture-design` 专业 checkpoint 持久化，保持 `owner_role` / `actor_role` 可溯源。

## V5.1.3 Runtime Portability + Installation Lifecycle — 2026-08-12

- Runtime SQLite `project.root_path` 明确定义为 machine-local locator/cache，不再作为 portable identity；`base sync-project --apply` / `base migrate --apply` 在旧 root 已失效且 identity 唯一时安全 rebind，并同步 machine-local Runtime Registry 与已有 Workspace Inventory。
- 同 project ID 的旧 root 仍存在或 registry 指向另一 live workspace 时 fail-closed，避免把复制出来的第二工作区误当成“移动”。
- Runtime Registry 默认从 Base checkout `db/registry.local.json` 迁出到 `~/.ai-work/registry.local.json`；旧位置只作为兼容输入，`base installation-migrate --apply` 在无冲突时迁移并移除旧 machine-state 文件；未显式指定 registry 的后续 mutation 也采用 machine-local copy-on-write，避免重新把机器状态写回 Base。
- `base configure` 补齐 create/update/repair 语义：合法旧配置允许只更新某一 root，损坏配置要求显式提供完整 roots；新增 `base installation-doctor` 与 `base installation-migrate` 生命周期命令。
- 新增 ACTIVE formal artifact portability 检查：只扫描 `NEW/ACTIVE/BLOCKED` 当前任务顶层 Markdown，报告具有执行语义的旧 Junction 路径；`tasksHistory` / evidence 不做历史清洗。
- SQLite `*.db-wal` / `*.db-shm` 明确定义为 transient runtime，不参与 portable truth / identity。
- Wiki `SCHEDULER_BOOTSTRAP.md` 与 Knowledge 统一通过 `~/.ai-work/installation.yaml` / `AI_WORK_INSTALLATION_CONFIG` 解析 Base；Scheduler 可在 Wiki System Root 运行，但必须按 Workspace Inventory + Repo Registry 逐 workspace 保持 scope。
- 主版本保持 `5.1.3`。

## V5.1.3 Portability + Project Entry Surface Convergence — 2026-08-12

- `tp-base-maintenance` 正式接管项目根 `AGENTS.md` / `README.md` 的 Base managed block 与 `.ai-work/README.md`；补回 Knowledge Skill 拆分时遗漏的 Project Integration Surface 职责。
- 新增 deterministic `base sync-project`：只改 managed block、保留项目自有 README/AGENTS 内容；marker 畸形 fail-closed。
- project-local `content-systems.yaml` 只保留真实项目语义 override；与 machine Installation 重复的 Wiki/Knowledge root 可确定性删除，无法证明安全的绝对路径阻塞。
- Base 程序、Prompt、Skill、模板与普通文档清除 machine-local 指纹和固定解释器路径；新增 `scripts/check_portability.py` 作为回归 Gate。
- Base 与 machine profile 分层：`~/.ai-work/installation.yaml` / `workspaces.yaml` 是可重新 configure/inventory 的薄机器配置，不是产品逻辑；项目文件不得复制这些绝对路径。
- 项目入口模板移至独立 `project-entry/`，不污染 `templates/5.1.3` 单活动 Task contract 目录。
- Knowledge projection 默认文件名 generic 化；历史数据文件名仅作为配置化 compatibility candidate，不进入执行代码硬编码。
- 主版本保持 `5.1.3`。

## V5.1.3 Base Convergence + Knowledge Legacy Normalization — 2026-08-11

- 新增用户级 `~/.ai-work/installation.yaml` 与 Workspace Inventory：Base/Wiki/Knowledge 系统根只配置一次，多项目通过 registry + project binding 解析项目级 scope。
- 新增 `ai-work base configure|resolve|doctor|inventory|migration-plan|migrate`；`tp-base-maintenance` 可批量检查/迁移多个项目根。
- 项目 Junction 降为迁移兼容面：只有 link target 与 Resolver target 完全一致时才移除链接对象；真实项目目录永不自动删除。
- Wiki 继续保持 workspace/repository scope；Knowledge 默认保持 `project + shared`，全库检索必须显式 `--scope global`，不会因为中央 root/全局 DB 扩大日常召回范围。
- Knowledge legacy registry 无 `workspace_roots` 时，可在迁移期从现有 `.ai-work/knowledge` Junction 精确反推出已注册 project id，写入 binding 后即可移除链接。
- 新增 `knowledge migrate-normalize`：dry-run 默认，仅自动处理 relations dict、`relates_to`、`ops`、ID 可推导 kind、旧定性 confidence、数字 alias 等单义机械迁移；未知 relation、缺 evidence/真实验证事实进入 review queue。
- `part_of` 契约以 additive 方式允许 `feature`/`data` 作为真实层级 target，避免为过窄 schema 降级真实 containment 语义。
- Knowledge Vault 的已配置 local-editor/personal-note roots 标准分类为 `KEEP_LOCAL_OUT_OF_SCOPE`，不进入项目 Knowledge lint/index/automation；个人资料只能通过显式 ingest 选择性沉淀。
- 主版本保持 `5.1.3`。

## V5.1.3 — Record-first 减负

### V5.1.3 Knowledge Standardization（2026-08-11，版本号不变）

- 将原 `tp-knowledge` 的“Base 健康/同步”职责拆分为独立 `tp-base-maintenance` human-owner Skill；默认健康检查只读，`project bootstrap --check-only` 不初始化项目，显式同步/修复仍需 human_owner 授权。
- `tp-knowledge` 收敛为纯 Knowledge Content System 角色：维护外部文档、Task/code evidence、source/canonical、检索投影、质量验证与无人值守增量维护，不再承担 Base VERSION/Junction/受管块同步。
- 扩展共享 `Content Systems`：Knowledge root、project registry、canonical/source layout、SQLite projection、retrieval、ingest、quality、evidence、Golden evaluation 均由 `governance/content-systems.yaml` 与项目 override 管理，避免绝对路径和第二权威。
- 新增标准 `cli/knowledge/`：doctor/init/scan/maintain/lint/verify/status/snapshot-commit、index build/update/status、canonical-first search、telemetry、Golden eval、audit/audit-record、external ingest 与 read-only migrate-plan。
- 保留成熟 `SQLite FTS5 + canonical-first + source fallback` 路线；Embedding/vector 明确为 `retired-compatible`，旧向量表存在不代表活动能力，未来仅在当前 Golden Query 显示显著性价比收益时才考虑恢复。
- Knowledge projection DB 正式定位为可删除重建的 Retrieval Projection；Canonical Markdown + 注册 evidence/source 才是 Knowledge truth。Graph 保持 optional projection。
- Knowledge ingestion 采用 Registered Source Accountability，而非“Source→Canonical 覆盖率”：每个已注册 Source 必须有 terminal disposition，但 duplicate/source_only/quarantined/excluded 均是合法结果，避免为了数字制造垃圾知识。
- 新增 Knowledge L1-L4、结构化 `evidence_refs`、统一 schema/templates、source registry、增量 baseline 与检索 telemetry；标准搜索不保存 raw query，只记录 hash/mode/fallback/count/latency。
- Knowledge Scheduler 正式按对话模型设计：外部 Scheduler 仅保存短 bootstrap，每次读取 Base 当前 `automation/knowledge/daily-maintenance.md`；无人值守禁止交互式询问，歧义/破坏性操作 fail-closed，旧可信 baseline 不前推。
- 新增 `knowledge migrate-plan` 迁移矩阵，将旧 Knowledge Vault 中 runtime/rules/schema/templates/fixtures 从数据仓迁回 Base；业务 canonical/source/evidence、用户 registry/dictionaries 与 Golden Query 数据继续留在 Vault。

- Wiki semantic calibration maintenance：面向低成本模型补强 Current/Compatibility/Recovery/Historical 判定、Existence≠Authority、责任层归因与 pipeline stage owner；L4 改为对抗式 challenge，首建/增量 rebuild plan 同时暴露 Wiki eligibility，目标是在不增加文档灌水的前提下提升代码认知质量。
- `manifest-refresh` 现在从正文 `<cite>` 的实际所在标题确定性推导 dependency section targeting；模型无需手填 manifest 语义 bookkeeping，也能让后续 planner 精确命中受影响章节。
- 修正一条遗留 V5.1.2 回归测试：不再要求已删除的旧角色 Runtime 文档/`commit --refresh` 主链，改为验证当前 `governance/runtime-api.yaml` 的 V5.1.3 Record-first 日常 API 与 legacy compatibility 边界。
- Wiki P0 closure: full affected/full-repo L4 scope, truthful Effective Wiki Coverage with current Wiki+source provenance and section-bound semantic dependencies, plus coverage CLI/reporting.
- Effective coverage eligibility treats behavior-defining `governance/*.md` contracts as Wiki-worthy sources while keeping generic documentation artifacts outside the denominator.

### V5.1.3 Wiki Standardization Maintenance（2026-08-10，版本号不变）

- 将代码理解 Wiki 从外部中央 Wiki 的 legacy tools 脚本集合收敛为 AI Work Base 内置子系统；Wiki 数据目录不再携带工具代码。
- 新增 Wiki/Knowledge 共用 Content Systems 配置与 logical/physical path resolver：空 root 默认 `.ai-work/wiki` / `.ai-work/knowledge`，外部中央 root 继续支持，Junction 降为兼容/浏览入口。
- 新增 Python Wiki CLI：doctor/init/build/scan/plan/maintain/manifest-refresh/verify/audit/audit-record/snapshot-commit/status。
- 快照变更检测同时使用 raw SHA-256 与 normalized fingerprint；显式吸收 CRLF/LF、BOM、UTF-8/UTF-16/GB18030 等可确认编码/格式漂移，并对不可可靠解码 fail-closed 为 UNCERTAIN。
- 新增 Mass Change Guard 与 Source Topology Diff，避免重新下载/formatter/编码漂移触发 Token 爆炸，也避免新核心文件因旧 dependency graph 无 edge 而漏维护。
- 修正旧维护链“Wiki 尚未由 AI 更新就先推进 snapshot”的危险窗口；新不变量固定为 `SCAN → PLAN → AI UPDATE → VERIFY → L4(if required) → SNAPSHOT COMMIT`。
- 新增 L1 Integrity / L2 Traceability / L3 Content Quality / L4 Semantic Audit 四层质量体系；L4 抽样范围由确定性 `wiki audit` 生成，避免定时模型每次自行发明审计方法。
- 新增版本化 AI Scheduler canonical protocols；外部定时任务只保存短 bootstrap，每次读取 Base 当前协议。
- 更新 `tp-wiki` 与 `tp-knowledge`：统一走 Content Systems Resolver，移除绝对路径/Junction 强依赖，并为后续 Knowledge 标准化预留公共底座。
- 新增 committed cite-anchor baseline：COSMETIC 注释/空行位移只做确定性 `<cite line>` 重定位与 hash/provenance 刷新，不调用模型；无法安全重定位时 fail-closed，避免“行号仍合法但已指错代码”的假精确。
- 新增项目侧通用 `scripts/Invoke-AiWorkCli.ps1`：定时 AI 从 `AI_WORK_BASE_ROOT`、真实 Base 或 `.ai-work/scripts` Junction 解析 physical BaseRoot，再调用统一 Python CLI，降低 cwd/PYTHONPATH 漂移。
- L2 精确引用覆盖率按配置阈值执行（默认 90% 且不足为 ERROR）；Golden Migration 进一步修复 H1 标题误命中七段式章节、合法父级 Wiki 导航被误判路径逃逸两类质量门假阳性。

### V5.1.3 SKILL Maintenance（2026-08-10，版本号不变）

- 对 7 个研发角色 SKILL 做语义补强：恢复事实/假设/决策边界、产品异常场景、架构风险与自检矩阵、独立评审检查项、开发范围/生产访问安全、验收独立 review 矩阵、知识真实性边界；不恢复旧 handoff/phase-exit/refresh/CLOSING 主路径。
- 7 个研发角色由过度压缩后的约 157 行恢复为约 265 行高密度专业协议，仍显著小于 V5.1.2 的治理重协议。
- 9 个 `skills/*` 公共方法 Skill 全部迁移为 V5.1.3 Record-first 语义，移除旧工具角色名、旧微状态、handoff/next_prompt 等活动流程残留。
- 新增 SKILL semantic regression，防止“流程减负”再次误删专业判断；版本纯度扫描不再把活动 `skills/` 当历史白名单。

- 主状态收敛为 `NEW / ACTIVE / BLOCKED / COMPLETED / CANCELLED`；研发阶段改由 `task.current_stage/current_phase` 与事实事件记录，不再作为权限门禁。
- 新增日常 API：`task checkpoint / verify / block / resume / complete / cancel`；每个业务阶段最多一次有意义记录，Runtime 自动更新 SQLite 与全部可读投影。
- 移除正常主链的独立 `CLOSING`；`tp-delivery-convergence` 改为按需知识/交付辅助，knowledge DEFERRED 默认不阻止 COMPLETED。
- Architecture Review 从 L2/L3 默认硬门禁改为风险触发的独立第二意见。
- 新 Task 不再预生成一组空模板工件；只有真实内容才产生可选工件。
- intake 接管由 Runtime 自动补/纠正 `artifact/task_id/artifact_contract/provenance` 机器 metadata，不因 front matter 缺失让业务角色返工。
- 技术验收新增 Record-first `VERIFICATION_COMPLETED`：PASS 仍必须绑定真实 `evidence/*`，但验证事实不再承担阶段状态推进职责。
- `generated/continuation.md` / `final-result.md` 自动展示 state/phase/owner/真实 verification；COMPLETED 不暗示未执行验证为 PASS。
- V5.1.2 在途任务通过现有官方迁移链进入 5.1.3，旧微状态折叠为 ACTIVE/BLOCKED + phase，历史事件不改写。
- 正常角色协议明确退出 `commit --refresh`、phase-exit dry-run、手工 handoff、为了门禁执行 refs-validate 等纯记账动作。

---

## v5.1.2

V5.1.2 将真实任务压测后的修复统一收敛为个人研发模式下的单一活动契约，并引入可选 UltraPlan Lite。

### V5.1.2 Maintenance（2026-08-09，版本号不变）

- 修复 `commit` 对架构阶段 `stage_handoff` 的同 owner 污染：`NEW → TECH_DESIGNING` 等内部微循环不再把 `task.md.stage_handoff.intended_next` 改成内部状态；只有真实跨 owner 退出时才刷新 ready/intended_next，L0 `NEW → DEVELOPING` 仍保持合法出口标记。
- 修复 `Test-AiWorkTask.ps1` 的基座根推导：不再要求项目 `.ai-work/cli` Junction；优先 `AI_WORK_BASE_ROOT`、完整基座路径或 `scripts` Junction Target，并用 `VERSION + cli/main.py + governance/workflow.yaml` 验证候选根。
- `refs-validate` 新增 `--schema` / `--example` 发现入口，公开 kind/verification/confidence/evidence_hash_reason 枚举与 `scope-dirs / approved-scope / ref.value` 路径语义；命令注册表同步更新双锚点。
- `commit --help` 公开 `--payload-json` 字段类型；`commit --refresh` 缺省 summary 由 Runtime 确定性生成 `refresh generated projections`。
- 正式接入已有 `work start/end` 作为角色真实时间证据：新会话记录 `session_id`，同一 Task+role 禁止重复 open session，孤立 END fail-closed；角色契约明确 pre-task 不补造时间事实。

### V5.1.2 Maintenance（2026-08-08）

- 新增 `project bootstrap`：供 `tp-knowledge` 首次健康检查调用，严格判断 pristine project；仅在无 DB、无活动 Task、无历史 ledger、无 stale registry 时委托官方 `project init`，已有健康项目幂等返回 `PROJECT_READY`，歧义状态 fail-closed 为 `PROJECT_BOOTSTRAP_UNSAFE`。
- `task create` 在 DB 缺失或 schema 未初始化时改为 `PROJECT_NOT_INITIALIZED` 可行动错误，不再泄漏 `unable to open database file` 让业务 AI 排查底层 SQLite；已有 DB 使用 read-only 预检，错误路径不改写现场文件。
- 明确需求分析可发生在正式 Task 之前；没有 TaskId 是正常状态，正式 Task 只在 blocking 清零并进入开发准备时创建。
- 新增 `task create --from-intake <DIR>`：自动接管需求分析工件、绑定 TaskId/当前契约并记录来源 SHA-256 provenance；默认保留 intake 源目录，避免隐式破坏性清理。
- 补齐发布包缺失的角色侧 Runtime API 与 V5.1.2 升级报告文档，并新增 maintenance 回归。

### V5.1.2 Hotfix（2026-08-08）

- 修复 `Test-AiWorkTask.ps1` 对官方 `task acceptance-override` 产物的缩进假设：`yaml.safe_dump` 标准输出使用 2 空格子字段缩进，PowerShell 健康检查不再固定要求 4 空格。
- `deferred_acceptance` 与 `owner_waivers` 两条解析路径同步修复；未改变 YAML 生产格式、Runtime 账本语义或验收门禁。
- 新增回归覆盖 PyYAML 2 空格输出，防止 Python 官方 gate 通过而 PowerShell 健康检查产生 `DEFERRED_RECORD_MISSING` / `OWNER_WAIVER_RECORD_MISSING` 假阳性。

### Owner 与验收

- 技术 Review 与后续人工测试解耦：`PASS / NEEDS_FIX / FAIL` 分别对应技术通过、VERIFYING 内定点修复与正式开发返工。
- 新增 `task acceptance-override`，human_owner 可审计地将人工测试后置（`DEFERRED_ACCEPTED`）或明确跳过（`OWNER_WAIVED`），均保留残余风险且不伪造 PASS。
- `codex-review.md` 改用 `review.next_state`，消除“下一状态/下一角色”歧义。

### Runtime 与升级链

- 新增 `project upgrade-contract`，与 `task migration-plan` / `task migrate` 组成项目契约 + 在途任务的完整非追溯升级链。
- 明确官方 Runtime 写账与人工直接改 SQLite 的边界；generated stale 统一由 `commit --refresh` 生成可审计投影。
- 新增角色侧 `docs/AI_WORK_RUNTIME_API.md`，正常业务任务无需读取 Runtime Python 源码理解命令。

### 规划与成本控制

- 新增可选 `UltraPlan Lite`：仅复杂/高风险且存在多条架构路线时启用正交方案 fan-out、事实核验和评分综合；默认仍为 DIRECT，能力不可用时不阻断。
- 不新增 TESTING_PENDING 等常驻 workflow state，避免为了测试后置重新增加流程治理成本。

## v5.1.1

V5.1.1 面向个人研发协作收敛为单一活动执行契约，并依据真实 L2/L3 任务压测完成治理减负与可靠性修复。

### 真实任务加固

- VERIFYING 使用 working 语义，消除“开始验收前先要求验收完成”的循环门禁。
- `commit --dry-run` 与 `commit --review-only --dry-run` 一次聚合交接/验收出口 blocker，减少治理性反复 PASS。
- 验收 decision 统一为 `PASS / FAIL / NEEDS_FIX`；普通实现缺陷可在可信失败 review 后 `VERIFYING → DEVELOPING` 直返开发。
- CLOSING/COMPLETED 统一要求绑定当前 review、subject 与真实 evidence 的可信 verification PASS。
- 评审 subject digest 忽略 BOM/CRLF 及 Runtime 自管 test-guide 元数据，但继续保护业务正文、实现、验收标准与 evidence。
- CLOSING 增加高置信文本完整性检查，拦截非法 UTF-8、明显 mojibake、NUL 与 PowerShell 换行转义泄漏。

### 在途升级与历史恢复

- 新增 `task migration-plan` 深一致性扫描与 `task migrate` 事务化、幂等、非追溯迁移/当前契约投影修复。
- 迁移投影从 SQLite canonical history 重建，避免文件侧脏 events/handoff 成为第二事实源。
- 新增 `task retire`，允许 human_owner 将 orphan/superseded 历史实例退出 active gate，同时保留其最后真实 workflow state，不伪造 COMPLETED。

### 流程成本与工件

- 新增 `task create --scaffold`、Runtime API、`task artifact-path`；验证 SQL 默认进入 `evidence/sql/`。
- 同 owner 微状态不强迫逐步 commit；test-guide lifecycle/owner 由 Runtime 维护。
- test-guide 回归测试人员视角，不再作为第二份验收账本；无真实 decision 时不强制制造 decision。
- 状态流转只校验目标状态真正依赖的工件；未来阶段坏草稿不提前阻断。

## v5.1.0

V5.1.0 在上一版本工程化加固基座上新增结构化引用、复用告警、无损可回溯摘要、溯源 Schema、归档报告、Cutover 机制、审查预检与 S1 声明拒绝校验器，并完成版本一致性修复与发布工程升级。

### 新增能力

- B12 Structured References
- B13 Reuse Warning
- B14 Lossless Summary
- B16 Provenance Schema
- B17 Archiving Report
- B18 Cutover Design
- C1 Review Preflight
- C5 S1 Declaration Rejection

### 工程优化

- 完成版本迁移
- 完成测试基线升级
- 完善发布验证流程

## 历史版本

以下版本为本仓库的历史发布记录，详细正文由 Git release 分支承担，不再在常驻上下文中保留旧协议号：

- ## v5.0.6 — 历史版本，详见 release/v5.0.6 分支
- ## v5.0.5 — 历史版本，详见 release/v5.0.5 分支
- ## v5.0.4 — 历史版本，详见 release/v5.0.4 分支
- ## v5.0.3 — 历史版本，详见 release/v5.0.3 分支
- ## v5.0.2 — 历史版本，详见 release/v5.0.2 分支
- ## v5.0.1 — 历史版本，详见 release/v5.0.1 分支
- ## v5.0.0 — 历史版本，详见 release/v5.0.0 分支
- ## v4.4.2 — 历史版本，详见 release/v4.4.2 分支
- ## v4.4.1 — 历史版本，详见 release/v4.4.1 分支
- ## v4.4.0 — 历史版本，详见 release/v4.4.0 分支
- ## v4.3.2 — 历史版本，详见 release/v4.3.2 分支
- ## v4.3.1 — 历史版本，详见 release/v4.3.1 分支
- ## v4.3.0 — 历史版本，详见 release/v4.3.0 分支
- ## v4.2.2 — 历史版本，详见 release/v4.2.2 分支
- ## v4.2.1 — 历史版本，详见 release/v4.2.1 分支
- ## v4.2.0 — 历史版本，详见 release/v4.2.0 分支
- ## v4.1.0 — 历史版本，详见 release/v4.1.0 分支
- ## v4.0.0 — 历史版本，详见 release/v4.0.0 分支
- ## v3.0.0 — 历史版本，详见 release/v3.0.0 分支
- ## v2.2.0 — 历史版本，详见 release/v2.2.0 分支
- ## v2.1.0 — 历史版本，详见 release/v2.1.0 分支
- ## v2.0.1 — 历史版本，详见 release/v2.0.1 分支
- ## v2.0.0 — 历史版本，详见 release/v2.0.0 分支
