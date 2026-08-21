# TP-Spec-Coding v5.2.4 正式角色化软件工程体系升级计划（实施基线 R3）

> **基线源码**：v5.2.3
> **当前升级分支**：`v5.2.4`
> **基线 HEAD**：`6ae4259`（tag: `v5.2.3`）
> **目标版本**：v5.2.4
> **版本主题**：**Role-first Personal AI Software Engineering System**
> **核心目标**：把 TP-Spec-Coding 从“按下一步要做什么组织能力的 AI 开发流程”，升级成“按正式软件工程角色组织能力的一人项目组 / 个人 AI 软件工程团队”，同时完整保留 v5.2.3 已验证有效的轻量执行、Record-first、L0～L3、UltraPlan、UltraReview、自治、Wiki、Knowledge、Base、迁移与恢复能力。


> **评审状态**：R2 已通过架构与源码一致性评审，可进入实施。R3 只吸收最终非否决项：显式补齐 `legacy_workflow.py` 在 active runtime 中的两个调用者耦合点，不改变既有架构裁决与 Phase 0→11 的实施主线。

---

# 本轮评审修订说明（R2）

> 本节针对源码复核后的第二轮评审逐项裁决。以下裁决已经并入正文，不是附录建议。

| 评审项 | 裁决 | 本版处理 |
|---|---|---|
| P0-1 旧 Role ID active 硬编码范围低估 | **接受，而且实际范围比评审列出的还大** | 第 48 节改为“机器生成 Role Reference Inventory + 分层源码热点”，不再依赖手工 10 文件清单；Release Gate 加入 repo-wide no-tail scanner |
| P0-2 legacy 层与 no-tail 矛盾 | **接受，采用删除 active legacy runtime 的方案** | `legacy_workflow.py` 迁入 migration/history-only；`transition_service.py` 拆分通用能力后从 active runtime 退役；旧 long-state `tp-spec commit` 不进入 v5.2.4 canonical runtime |
| P1-3 `mode` / `effects` 迁移缺失 | **接受** | 第 32 节明确 mode 是执行策略、effects 是安全边界；由 capability contract 替代旧 role-id 硬校验；`repo_mutation` fail-closed 语义完整保留 |
| P1-4 Architecture Review 独立性缺少可验证 Gate | **接受** | 第 10、52 节增加 isolated review contract 与自动 isolation proof；正式 Architecture Review PASS 不允许与 design execution context 相同 |
| P2-5 `discovery` phase 去向不明 | **接受，保留** | `discovery` 继续作为“技术事实发现”phase fact，不是角色、不收费；与 Autonomy discovery、Product discovery 语义分离 |
| P2-6 Integration Engineer 膨胀 | **接受并进一步收敛** | Knowledge convergence 从 Integration Engineer 移出，由 `tp-knowledge` 提供 task-scoped convergence；Integration 只负责交付事实和 handoff |
| P2-7 `tp-spec-coding` routing 成本未定义 | **接受** | 路由限定为 signal-driven / low-context；不得读全 Task、仓库、需求正文来判断 Domain；Product Cost Tests 增加 router cost 约束 |

## R2 额外源码发现

对当前源码做 repo-wide 旧 Role ID 搜索后，除评审指出的：

```text
cli/commit_cmd.py
cli/receipt_cmd.py
cli/orchestration.py
cli/delivery_contract.py
cli/context_effectiveness.py
cli/autonomy_integration.py
```

还确认 active/near-active 路径中存在：

```text
cli/review_cmd.py
cli/record_first.py
cli/workflow_records.py
cli/workflow_loader.py
cli/task_cmd.py
cli/work_session_cmd.py
cli/rework_cmd.py
cli/projection_cmd.py
cli/review_preflight.py
cli/reuse_warnings.py
cli/anchor_check.py
cli/main.py
```

以及明确 frozen/compatibility 路径：

```text
cli/legacy_workflow.py
cli/transition_service.py
```

因此本版不再把“源码热点清单”作为一个可以手工穷举的静态列表。

正式要求改为：

> **Phase 0 机器生成全部旧 Role Reference Inventory；Release 前机器扫描 tracked source；默认 deny，只有 migration/history 明确白名单可保留旧 Role ID。**

这样避免实施期间继续发现漏网硬编码，也避免 no-tail 假绿。

---

# R3 最终非否决修订

R2 已通过评审。R3 只增加一个实施前必须显式纳入 Phase 0 的技术事实：

```text
cli/config_loader.py
  └─ active import: LEGACY_STATE_OWNERS

cli/workflow_loader.py
  └─ active import: LEGACY_STATE_OWNERS, LEGACY_TRANSITIONS
```

裁决：

> 这两处 active fallback 不是可长期保留的 compatibility tail。它们与 legacy long-state owner/transition matrix 一并迁出 active config/workflow 解析路径，归入 migration/history-only。正常 v5.2.4 runtime 不允许继续读取这些 legacy mapping。

该修订不改变 R2 已通过的架构结论，也不新增新的兼容层。

---

# 0. 【评审员必读】本计划为什么会主动与当前源码结构不一致

这一节是本计划的**架构裁决说明**。评审时必须先阅读本节，再对照 v5.2.3 源码。

如果只按“当前代码是什么”判断“计划应该继续保持什么”，会错误地把本次升级真正要修复的旧抽象当成必须兼容的目标。

## 0.1 这不是一次普通功能扩展，而是一次有意识的 Canonical Model Cutover

当前 v5.2.3 的软件研发能力主要按“动作/步骤”建模：

```text
tp-requirement-analysis
tp-product-design
tp-architecture-design
tp-architecture-review
tp-development-engineering
tp-verification-engineering
tp-delivery-convergence
```

它们在现有代码里同时承担了：

- workflow stage；
- Runtime role identity；
- Skill；
- 某些情况下还近似承担“人员角色”。

这是历史上为了快速建立一个高效 AI 开发流程形成的模型。

**v5.2.4 的目标不是继续把这些 Action Role 做大，而是把它们重新归位到正式软件工程角色下面。**

例如：

```text
旧：
tp-requirement-analysis = 顶层 workflow role

新：
Product Manager
└── requirement-analysis = 该角色的一项 Skill
```

```text
旧：
tp-architecture-design = 顶层 workflow role

新：
Software Architect
├── system-analysis
├── architecture-design
├── technology-selection
├── interface-design
└── architecture-review
```

```text
旧：
tp-verification-engineering
同时承担测试、技术 Review、安全检查、验收

新：
Test Engineer
Code Reviewer
Security Engineer
各自承担正式责任
```

因此：

> **“当前源码没有这些正式角色”不是拒绝本计划的理由；这恰恰是本次升级要解决的问题。**

---

## 0.2 为什么现在允许做一次大的内部迁移

当前项目尚未实际推广，主要用户就是项目所有者本人。

项目所有者明确接受：

- 一次性较大的内部模型迁移；
- Role ID / Skill 组织方式的 breaking change；
- governance contract 的一次完整升级；
- active Task 的正式迁移。

项目所有者不接受：

- 用户项目数据丢失；
- Knowledge / Wiki / Memory 丢失；
- 已有配置意图丢失；
- v5.2.3 成熟能力倒退；
- 为兼容旧错误抽象长期保留两套活跃模型；
- 升级后仍然存在“旧 7 Role + 新 Role Pool”双轨运行。

本次升级原则是：

> **兼容真实用户资产，不兼容错误抽象。**

> **保留历史事实，不保留旧模型作为活动运行时。**

---

## 0.3 当前 7 步不是被否定，而是被“职责归位”

项目所有者已经明确：

> 旧的 7 步之所以长期能够覆盖约 95% 的开发工作，是因为在进入 TP-Spec-Coding 之前，用户往往已经与其他 AI 把客户的一句话/文档拆成了较成熟的需求。

过去真实工作链是：

```text
客户一句话 / 文档
    ↓
用户 + 其他 AI
    ↓
产品理解 / 需求分析 / 需求拆分 / 初步规划
    ↓
Requirement Ready
    ↓
TP-Spec-Coding Task
    ↓
现有轻量研发流程
```

因此旧 7 步真正证明的是：

> **在 Requirement Ready 的前提下，现有轻量 Task Delivery 流程非常有效。**

v5.2.4 不会丢掉这一点。

本次升级是把原来外包给“用户 + 其他 AI”的上游软件工程职责也纳入 TP-Spec-Coding，并且把旧 7 个 Action Role 重新放进正式人员职责树。

因此：

```text
旧 7 步的“流程经验”继续保留
旧 7 Role 的“顶层角色身份”不继续保留
```

这两件事不冲突。

---

## 0.4 为什么必须 Role-first，而不能继续 7 Role + Sub-Skill

如果继续：

```text
tp-requirement-analysis
  └── 更多需求 Skill

tp-development-engineering
  └── frontend / backend / database / security / ...
```

短期改动最小，但会继续产生三个长期问题：

### 问题 A：动作被错误当成责任主体

“需求分析”是工作动作，不是一个完整软件团队里的责任身份。

真正责任主体是：

```text
Product Manager
```

其能力包含：

```text
产品规划
需求分析
需求澄清
需求拆解
范围管理
验收标准
产品设计
```

### 问题 B：一个 Action Role 会越来越膨胀

例如当前 `tp-verification-engineering` 已经同时检查：

- 需求覆盖；
- 工程正确性；
- 安全权限；
- 数据；
- 兼容运行；
- 测试证据；
- UltraReview。

继续扩展会自然把：

```text
测试工程师
安全工程师
代码 Reviewer
```

继续塞进同一个 Skill。

### 问题 C：未来无法自然扩展到“一人项目组”

用户当前已经实际承担：

1. 部分产品经理；
2. 软件架构师；
3. 技术主管；
4. 安全工程职责；
5. 开发 / 数据库；
6. 测试；
7. 他人代码 Review。

因此 TP-Spec-Coding 必须从“AI Coding Workflow”演进为：

> **Personal AI Software Engineering Team**

---

## 0.5 本次评审必须保护什么，允许改变什么

### 必须保护

- `NEW / ACTIVE / BLOCKED / COMPLETED / CANCELLED` 五态；
- phase 是事实而不是收费站；
- Record-first；
- CLI-first 记账；
- L0～L3 风险/流程裁剪思想；
- UltraPlan；
- UltraReview；
- Material / each_stage confirmation；
- Delivery fast path 的增量开销预算；
- Wiki；
- Knowledge；
- Project Memory；
- Base Maintenance；
- Project Autonomy；
- Workspace fencing / recovery；
- SQLite 权威事实；
- official contract migration chain；
- 历史任务可读；
- 用户配置与用户数据；
- 简单任务的低交互成本。

### 允许并且要求改变

- 现有 7 个 Action-based workflow role ID；
- `tp-workflow-orchestrator` 作为用户软件开发入口的产品定位；
- Role Catalog 的 active role model；
- Agent / Role / Skill 的层级；
- 旧 Skill 物理目录；
- `task create` 对旧角色的硬编码；
- Orchestration pipeline 中“stage == role”的绑定；
- README 对“7 个专业 Skill”的产品表述；
- 测试中把旧 Role ID 当作永恒契约的断言。

---

## 0.6 本计划明确不接受的“假兼容”

以下做法评审应判定为 **FAIL**：

```text
新建 Product Manager
但仍让 tp-requirement-analysis 做真实 Runtime owner
```

```text
新建 Software Lifecycle Agent
但 tp-workflow-orchestrator 仍是另一套并行开发入口
```

```text
新角色只做展示层名字
内部仍以旧 7 Action Role 作为永久主模型
```

```text
旧 Role 通过 alias 永久留在 active role-catalog
```

```text
新旧 pipeline 长期双轨运行
```

允许保留的只有：

```text
migration-only mapping
historical read-only rendering
CHANGELOG / release documentation
```

这些不得被正常 Runtime 加载成 active routing contract。

---

## 0.7 版本号不是本次评审的拒绝点

项目所有者明确决定目标版本仍为：

```text
v5.2.4
```

虽然本次属于架构级升级，但版本编号属于项目发布策略。

评审应关注：

- contract 是否完整 cutover；
- migration 是否安全；
- capability 是否完整保留；
- 新模型是否只有一个 canonical truth；
- Runtime 是否仍可靠。

不应因为“体量看起来像 5.3.0”拒绝方案。

---

# 1. 升级背景：用户职责已经从开发者扩展成一支小型软件团队

TP-Spec-Coding 最早主要解决：

```text
需求已明确
→ 分析怎么改
→ 写代码
→ 验证
→ 交付
```

用户过去主要负责代码。

现在实际职责已经扩展到：

| 实际职责 | 当前需要补齐的 AI 工程能力 |
|---|---|
| 产品规划 / 需求分析 | Product Manager |
| 系统设计 / 架构规划 / 技术选型 / 接口设计 | Software Architect |
| 代码规范 / 技术规划 / 技术把关 | Tech Lead |
| 安全审计 / 扫描 | Security Engineer |
| 代码开发 | Development Engineer |
| 数据库 | Database Engineer |
| 单元 / 集成 / 接口测试 | Test Engineer |
| 他人提交代码 Review | Code Reviewer |
| 集成 / 收敛 / 交付 | Integration Engineer |

因此 v5.2.4 的产品目标变成：

> **让一个人通过 TP-Spec-Coding 获得一支完整 AI 软件项目组的能力。**

---

# 2. v5.2.4 四条不可突破的产品底线

## 2.1 底层可以非常复杂，用户体验层必须简单

内部可以存在：

- Domain Agent；
- Lifecycle；
- Role Pool；
- Role Skill；
- Sub-Skill；
- Resolver；
- Runtime；
- Event；
- Evidence；
- Recovery；
- Migration；
- Gate result；
- Workspace fencing。

但普通用户默认只面对：

```text
tp-spec-coding
```

用户只需要表达：

```text
帮我规划这个需求。
客户给了这份文档，先拆清楚。
直接做这个已经明确的需求。
继续。
现在做到哪里了？
为什么要做这个检查？
Review 一下别人提交的代码。
可以集成了吗？
```

复杂度由 TP-Spec-Coding 吸收。

---

## 2.2 纯治理 / 记账额外消耗目标仍然 < 5%

当前源码已经存在：

```yaml
execution:
  delivery_fast_path:
    max_incremental_ai_overhead_percent: 5
```

v5.2.4 不新造第二套指标，而是把该产品原则继续扩大到完整软件工程体系。

要求：

- AI 不能为了 Role 切换手写一堆状态文档；
- AI 不能维护 `status.yaml / events.jsonl / SQLite`；
- Runtime 继续负责机器 metadata；
- 一个有意义工作结果最多一次原子 CLI 记录；
- Sub-Skill 调用不默认记账；
- Role Resolver 不为“解释自己”消耗大量上下文；
- Product Entry 不重复分析业务内容。

**产品/架构/测试/Review 本身属于真实软件工程工作，不算治理开销。**

---

## 2.3 配置优先，升级不损失用户资产

原则：

```text
Policy       → YAML/config
Mechanism    → Python/Runtime
User facts   → Project Runtime / Wiki / Knowledge
History      → Immutable
```

适合配置化：

- Role Catalog；
- Role → Skill 映射；
- Lifecycle presets；
- L0～L3；
- Risk → Role trigger；
- Optional Role trigger；
- 深度模式；
- confirmation policy；
- Domain routing；
- Skill capability metadata。

不得因为 v5.2.4：

- 要求用户重新配置 Base/Wiki/Knowledge；
- 要求重建项目；
- 要求重新录入个人偏好；
- 丢失 active Task；
- 丢失 Knowledge / Memory；
- 重写历史证据。

---

## 2.4 不为记账而记账

继续坚持：

```text
真实软件工程工作
→ 形成有意义事实
→ CLI 原子记录
→ Runtime 投影
```

不得变成：

```text
做了一点工作
→ 更新 Role 状态
→ 更新 Skill 状态
→ 更新 Phase 状态
→ 更新 Gate 状态
→ 补 Artifact
→ 才允许继续
```

缺少可推导/非关键 metadata：

```text
AUTO REPAIR / WARN / DEFER
```

只有影响：

- 真实性；
- 数据完整性；
- 高风险授权；
- 关键业务决策；
- 验证可信度；

时才 BLOCK。

---

# 3. 当前源码基线事实

基于上传源码，本计划确认以下事实。

## 3.1 当前 Agent 共 5 个

```text
tp-workflow-orchestrator
tp-project-autonomy
tp-base-maintenance
tp-knowledge
tp-wiki
```

## 3.2 当前 Skill 共 21 个

其中软件开发主链 7 个：

```text
tp-requirement-analysis
tp-product-design
tp-architecture-design
tp-architecture-review
tp-development-engineering
tp-verification-engineering
tp-delivery-convergence
```

已有通用/子能力：

```text
requirement-clarification
assumption-management
delivery-planning
task-decomposition
implementation-control
systematic-debugging
testing-strategy
technical-review
knowledge-capture
tp-memory-capture
```

自治：

```text
tp-autonomy-setup
tp-autonomy-cycle
tp-autonomy-review
tp-autonomy-integrate
```

---

## 3.3 当前状态模型已经足够轻，不能回退

当前：

```text
NEW
ACTIVE
BLOCKED
COMPLETED
CANCELLED
```

`workflow.yaml` 明确：

> phase is a query/audit fact, not a workflow permission state

v5.2.4 继续保持。

---

## 3.4 当前已有正式 pre-task 语义

`tp-requirement-analysis` 已明确：

> 需求分析允许发生在正式 Task 创建之前；pre-task 没有 TaskId 合法，不得为了记账提前创建 Task。

`task create --from-intake` 已支持接收 pre-task requirement artifacts。

因此本次不是“把 Task 往后移”，而是：

> **把 pre-task 上游职责正式角色化、产品化、纳入统一入口。**

---

## 3.5 当前 Task Create 存在旧模型硬编码

当前 `cli/task_cmd.py` 在 Task 创建时写入：

```text
current_stage = intake
owner_role    = tp-architecture-design
```

多个代码路径还以：

```text
tp-architecture-design
```

作为 owner fallback。

这正是新模型必须迁移的具体代码热点之一。

---

## 3.6 当前 Orchestrator 把 stage 与 action-role 直接绑定

例如 L1：

```text
requirement  -> tp-requirement-analysis
architecture -> tp-architecture-design
development  -> tp-development-engineering
verification -> tp-verification-engineering
```

这是 v5.2.3 的正确实现，但也是 v5.2.4 要拆开的主要结构：

```text
Stage / Phase
      !=
Formal Role
      !=
Skill
```

---

# 4. 目标产品架构

```text
┌──────────────────────────────────────────────────────────┐
│ L1  Product Entry                                        │
│                                                          │
│                     tp-spec-coding                       │
│                                                          │
│     唯一默认用户入口 / 意图识别 / 状态 / Explain          │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│ L2  Domain Agents                                        │
│                                                          │
│  tp-software-lifecycle     软件工程生命周期               │
│  tp-wiki                   代码理解 Wiki                  │
│  tp-knowledge              长期 Knowledge                 │
│  tp-base-maintenance       基座 / 安装 / 迁移              │
│  tp-project-autonomy       项目自治维护                    │
└──────────────────────────┬───────────────────────────────┘
                           │
                           │ software intent
                           ▼
┌──────────────────────────────────────────────────────────┐
│ L3  Formal Engineering Role Pool                         │
│                                                          │
│ Product Manager        Software Architect                │
│ Tech Lead              Security Engineer                 │
│ Development Engineer   Database Engineer                 │
│ Test Engineer          Code Reviewer                     │
│ Integration Engineer                                    │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│ L4+ Role Skills / Sub-Skills / Specialist Skills         │
│                                                          │
│ requirement-analysis / interface-design / api-testing... │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│ Shared Runtime / CLI                                     │
│                                                          │
│ 5-state Task / phase fact / SQLite / events / evidence   │
│ orchestration / migration / recovery / workspace fencing │
└──────────────────────────────────────────────────────────┘
```

---


# 5. L1：`tp-spec-coding` 唯一产品入口

## 5.1 定位

`tp-spec-coding` 是用户视角的一等入口。

它不是：

- Product Manager；
- Workflow Orchestrator；
- Runtime；
- 超级开发 Agent。

它负责：

```text
理解用户现在想做什么
↓
以低成本信号识别 Domain
↓
读取极少量当前 Project / Task 摘要事实
↓
路由到 Domain Agent
↓
向用户提供统一 Status / Continue / Explain
```

---

## 5.2 用户不再需要先选择内部 Agent

普通使用：

```text
使用 tp-spec-coding 处理这个需求。
```

系统自行判断：

```text
软件研发
Wiki
Knowledge
Base
Autonomy
```

高级用户仍可直接调用 L2 Domain Agent，但不作为默认产品体验。

---

## 5.3 Domain Routing 必须是 signal-driven / low-context

`tp-spec-coding` 的 Domain Router 只允许使用低成本信号：

```text
当前用户输入
显式 Agent / command 指示
当前 Project identity
当前 active Task 的轻量摘要 / domain 标记
文件名 / MIME / 用户明确描述
```

默认**不得**为了判断 Domain：

- 扫描仓库；
- 读取完整 Task；
- 读取完整需求文档；
- 查询 Wiki / Knowledge；
- 做需求分析；
- 做代码理解；
- 启动子 Agent。

Router 输出保持极小：

```json
{
  "domain": "software",
  "confidence": "high",
  "reason_code": "software_task_explicit"
}
```

路由后，原始用户输入尽量原样交给 Domain Agent，避免 Product Entry 二次复述/压缩造成信息损失。

### 模糊输入

优先级：

```text
explicit domain instruction
> active task domain
> project product context
> shallow classifier
> one concise clarification
```

在明确 TP-Spec 软件项目上下文且无冲突信号时，可默认进入 `tp-software-lifecycle`。

**Domain Router 不能因为“更智能”而变成第二次需求分析。**

---

# 6. L2：Domain Agent 架构

## 6.1 `tp-software-lifecycle`

新建：

```text
agents/tp-software-lifecycle/SKILL.md
```

它成为唯一的软件工程 Domain Agent。

它负责：

- pre-task 软件需求生命周期；
- Task Delivery 生命周期；
- L0～L3；
- Formal Role Resolver；
- Role 调度；
- 深度模式触发；
- 关键确认；
- 返工路由；
- Task complete 前的软件工程路由判断。

它不负责具体专业产出。

---

## 6.2 `tp-workflow-orchestrator` 的去向

v5.2.4 **不再保留 `tp-workflow-orchestrator` 作为 active Agent**。

其有效能力分成两部分：

### 产品/领域职责

迁入：

```text
tp-software-lifecycle
```

### 纯编排机制

继续由：

```text
cli/orchestration.py
cli/orchestration_cmd.py
workflow next
workflow confirm
```

等 Runtime/CLI 实现。

也就是说：

```text
“Workflow Orchestrator”
从用户可见 Agent 身份
↓
变成 Software Lifecycle Agent 内部使用的编排机制
```

这样不会产生：

```text
tp-spec-coding
→ software-lifecycle
→ workflow-orchestrator
```

三个用户可见编排层。

---

## 6.3 其余 Domain Agent 保留

继续：

```text
tp-wiki
tp-knowledge
tp-base-maintenance
tp-project-autonomy
```

本次只做必要的入口统一与契约版本迁移，不借机重写已经成熟的专项能力。

---

# 7. 软件生命周期分成两个工作区段

## 7.1 Definition Lifecycle（Task 之前）

解决：

> 客户到底要什么？

```text
Raw Request
    ↓
Product Planning
    ↓
Requirement Analysis
    ↓
Clarification / Decomposition
    ↓
Scope / Business Rules
    ↓
Acceptance Criteria
    ↓
Requirement Ready
```

主要责任角色：

```text
Product Manager
```

按风险可以提前邀请：

```text
Software Architect
Security Engineer
Database Engineer
```

---

## 7.2 Task Delivery Lifecycle（Requirement Ready 之后）

```text
Task
 ↓
Architecture
 ↓
Technical Planning
 ↓
Implementation
 ↓
Testing / Verification
 ↓
Code Review
 ↓
Integration / Closure
```

不是所有 Task 都必须完整走完。

L0～L3 继续做裁剪。

---

# 8. 正式 Engineering Role Pool

v5.2.4 建立 9 个 canonical 软件工程角色。

| Canonical Role ID | 中文角色 | 主要责任 |
|---|---|---|
| `tp-product-manager` | 产品经理 | 产品规划、需求分析、拆解、范围、验收 |
| `tp-software-architect` | 软件架构师 | 系统设计、技术选型、接口与架构 |
| `tp-tech-lead` | 技术主管 | 技术规划、规范、任务组织、技术把关 |
| `tp-security-engineer` | 安全工程师 | 安全设计、审计、扫描、验证 |
| `tp-development-engineer` | 开发工程师 | 前后端实现、Debug、Refactor、性能 |
| `tp-database-engineer` | 数据库工程师 | 模型、SQL、DDL、Migration、数据库质量 |
| `tp-test-engineer` | 测试工程师 | 单测、集成、接口、回归、验收 |
| `tp-code-reviewer` | 代码审查员 | 独立 Code Review / Diff Review |
| `tp-integration-engineer` | 集成交付工程师 | 变更检查、集成、Git、交付收敛 |

---

# 9. Role 1：Product Manager

## 9.1 为什么正式叫 Product Manager

用户现在实际承担：

- 产品规划；
- 客户输入理解；
- 需求分析；
- 需求拆分；
- 产品行为设计。

当前 `tp-requirement-analysis + tp-product-design` 本质上已经是 Product Manager 的部分工作，只是按动作拆开了。

因此 v5.2.4 正式归位：

```text
tp-product-manager
```

---

## 9.2 Skill Tree

```text
Product Manager
│
├─ request-intake
├─ product-planning
├─ requirement-analysis
├─ requirement-clarification
├─ requirement-decomposition
├─ scope-management
├─ business-rule-analysis
├─ acceptance-criteria
├─ requirement-impact-analysis
├─ product-design
├─ interaction-flow-design
└─ requirement-review
```

---

## 9.3 现有能力迁入

```text
tp-requirement-analysis
→ requirement-analysis

requirement-clarification
→ requirement-clarification

assumption-management
→ assumption-management（共享子 Skill）

tp-product-design
→ product-design
```

旧内容不能丢。

---


# 10. Role 2：Software Architect

## 10.1 责任

回答：

> 系统应该怎么设计？

```text
tp-software-architect
│
├─ system-analysis
├─ architecture-design
├─ architecture-planning
├─ technology-selection
├─ module-design
├─ interface-design
├─ dependency-design
├─ data-flow-design
├─ compatibility-design
├─ reliability-design
├─ migration-architecture
├─ architecture-decision
└─ architecture-review
```

---

## 10.2 Architecture Review 不再是独立“动作角色”

当前：

```text
tp-architecture-review
```

在新模型中：

```text
Software Architect
└─ architecture-review
```

但独立性要求继续保留：

```text
设计执行上下文
!=
正式 Architecture Review 上下文
```

独立性来自**执行上下文和输入隔离**，而不是继续制造一个名为“架构评审”的永久人员角色。

---

## 10.3 Architecture Review 独立性成为可验证 Contract

正式 `architecture-review` 必须声明：

```yaml
execution_policy:
  context: isolated
  subject_binding: required
  design_scratchpad_visible: false
```

正式 Review 输入只允许：

```text
Canonical Requirement
Architecture Artifact / Decision
Project Truth
Risk Signals
必要的代码/接口/数据事实
```

不得直接把设计执行者的内部思考、未验证结论、私有 scratchpad 当作 Review 上下文。

Runtime / Orchestrator 应自动产生 isolation proof，例如：

```text
design_execution_context_id
review_execution_context_id
review_subject_digest
context_policy=isolated
```

要求：

```text
review_execution_context_id != design_execution_context_id
```

该证明由 Runtime 自动绑定，不要求 AI 手工写账。

### 两类检查必须区分

```text
Architect self-check
```

可以发生在设计过程中，但不得写入正式 Architecture Review PASS。

```text
Formal Architecture Review
```

在 L2/L3 或 architecture-risk 要求独立评审时，必须满足 isolated context contract，否则不得产生可信 `REVIEW_COMPLETED / ARCHITECTURE / PASS`。

---

# 11. Role 3：Tech Lead

## 11.1 责任

回答：

> 架构方案怎样变成一套可靠的工程执行计划？

```text
tp-tech-lead
│
├─ technical-planning
├─ coding-standard
├─ engineering-guideline
├─ task-decomposition
├─ dependency-planning
├─ execution-planning
├─ risk-assessment
├─ work-parallelization
├─ implementation-constraint
├─ technical-conformance
└─ engineering-decision
```

---

## 11.2 现有能力迁入

```text
delivery-planning
task-decomposition
planning-strategy
```

中属于“实施计划”的部分迁入 Tech Lead。

`tp-architecture-design` 中混在一起的：

```text
系统设计
实施拆解
```

必须在 v5.2.4 拆开：

```text
Architecture → Software Architect
Execution Plan → Tech Lead
```

---

# 12. Role 4：Security Engineer

```text
tp-security-engineer
│
├─ threat-analysis
├─ security-design-review
├─ authentication-review
├─ authorization-review
├─ data-security-review
├─ input-validation-review
├─ dependency-scan
├─ secret-scan
├─ static-security-scan
├─ vulnerability-analysis
├─ security-code-review
└─ security-verification
```

Security 是 cross-cutting role。

它可以参与：

```text
Requirement
Architecture
Implementation
Testing
Review
```

但绝不是每个任务固定调用。

---

# 13. Role 5：Development Engineer

```text
tp-development-engineer
│
├─ implementation-control
├─ frontend-engineering
├─ backend-engineering
├─ api-implementation
├─ business-logic
├─ error-handling
├─ systematic-debugging
├─ refactoring
├─ performance-engineering
├─ concurrency-engineering
└─ developer-self-test
```

Technology Context：

```text
Java
Spring
Python
FastAPI
JavaScript
TypeScript
Vue
React
...
```

技术栈不是新的顶层 Role。

---

# 14. Role 6：Database Engineer

```text
tp-database-engineer
│
├─ data-modeling
├─ schema-design
├─ sql-engineering
├─ query-analysis
├─ index-design
├─ migration-design
├─ migration-implementation
├─ transaction-analysis
├─ data-consistency
├─ rollback-design
├─ historical-data-repair
└─ database-performance
```

Database Engineer 可以同时出现在：

```text
Architecture
Implementation
Testing
Review
```

---

# 15. Role 7：Test Engineer

当前 `tp-verification-engineering` 里的测试职责正式迁入：

```text
tp-test-engineer
│
├─ test-analysis
├─ test-strategy
├─ unit-testing
├─ integration-testing
├─ api-testing
├─ regression-testing
├─ acceptance-testing
├─ runtime-verification
├─ browser-ui-verification
├─ failure-reproduction
└─ test-evidence-validation
```

现有：

```text
testing-strategy
```

直接迁入。

---

# 16. Role 8：Code Reviewer

用户已经明确承担他人提交代码 Review，因此它必须成为正式角色。

```text
tp-code-reviewer
│
├─ diff-analysis
├─ correctness-review
├─ coding-standard-review
├─ maintainability-review
├─ architecture-conformance-review
├─ error-handling-review
├─ regression-risk-review
├─ performance-review
├─ technical-debt-detection
└─ review-finding
```

当前：

```text
technical-review
```

迁入 Code Reviewer，并扩展。

---

## 16.1 Code Reviewer 与 Tech Lead 的边界

```text
Tech Lead
→ 制定规范、工程原则、实施约束

Code Reviewer
→ 使用这些规范检查实际提交
```

---

## 16.2 Code Reviewer 与 Test Engineer 的边界

```text
Test Engineer
→ 证明行为是否正确

Code Reviewer
→ 判断实现质量、风险、规范与可维护性
```

二者可以并行。

---


# 17. Role 9：Integration Engineer

```text
tp-integration-engineer
│
├─ change-inspection
├─ integration-readiness
├─ git-state-validation
├─ conflict-analysis
├─ git-integration
├─ post-integration-verification
├─ release-readiness
├─ residual-risk-summary
└─ task-delivery-result
```

不扩展到：

- Kubernetes；
- 云基础设施；
- 外部部署平台；
- 通用 DevOps 平台。

本 Role 只覆盖软件研发项目的**集成、交付与关闭事实**。

---

## 17.1 Integration Engineer 不负责 Knowledge 判断

为避免重新形成新的“大交付角色”，以下能力**不属于** Integration Engineer：

```text
knowledge qualification
knowledge normalization
knowledge promotion
knowledge system update policy
```

Integration Engineer 只提供当前 Task 已验证的交付事实：

```text
changed subjects
verification/review bindings
integration result
residual risk
delivery result
```

然后由 `tp-software-lifecycle` 按策略向：

```text
tp-knowledge
```

发起 task-scoped knowledge convergence。

因此职责边界是：

```text
Integration Engineer
→ “这次交付事实是什么？”

Knowledge Agent
→ “这些事实哪些值得进入长期知识体系？”
```

二者不能再次合并。

---

# 18. 旧 7 Action Role 到新角色模型的完整迁移

| v5.2.3 Action Role | v5.2.4 正式归属 | 说明 |
|---|---|---|
| `tp-requirement-analysis` | `tp-product-manager` | 需求分析变成 Product Manager Skill |
| `tp-product-design` | `tp-product-manager` | 产品设计变成 Product Manager Skill |
| `tp-architecture-design` | `tp-software-architect` + `tp-tech-lead` | 系统设计与实施规划拆开 |
| `tp-architecture-review` | `tp-software-architect` | Review 是 Architect Skill + isolated mode |
| `tp-development-engineering` | `tp-development-engineer` + `tp-database-engineer` | DB 职责正式独立 |
| `tp-verification-engineering` | `tp-test-engineer` + `tp-code-reviewer` + `tp-security-engineer` | 原 Skill 中混合责任正式拆开 |
| `tp-delivery-convergence` | `tp-integration-engineer` | 交付/集成归位，Knowledge 只保留 Task-driven convergence |

**这一表是迁移的主语义，不允许在实现时退回“旧 Role 上挂新 Role”。**

---

# 19. Lifecycle 与 Role 是两条正交轴

## 19.1 Lifecycle 回答

> 现在正在解决什么阶段的问题？

## 19.2 Role 回答

> 哪个正式工程角色对这个问题负责？

因此：

```text
Lifecycle Phase
       ↓
Role Resolver
       ↓
0..N Formal Roles
       ↓
Role Skill Resolver
       ↓
0..N Sub-Skills
```

---


# 20. 推荐 Lifecycle Phase

仍保持 phase 是事实，不是状态。

建议 v5.2.4 使用：

```text
intake
requirement
product
discovery
architecture
planning
development
verification
review
delivery
other
```

其中：

- `planning`、`review` 可成为新的事实标签；
- **保留 `discovery`**；
- 不产生新的 public state；
- 不要求每个 Task 都出现每个 phase；
- 历史旧 phase 不追溯改写。

---

## 20.1 `discovery` 的正式语义

`discovery` 在 v5.2.4 继续表示：

> **为了获得足够可靠的软件/技术事实而进行的技术发现工作。**

典型情况：

- 老项目代码结构不明；
- 真实依赖链不明；
- 数据模型事实不明；
- 接口/调用路径不明；
- 现有实现与文档冲突；
- 风险判断前缺少必要事实。

它不是新的 Role。

可能由：

```text
Software Architect
Tech Lead
Development Engineer
Database Engineer
Security Engineer
```

根据 discovery subject 承担。

---

## 20.2 与其他 “discovery” 概念隔离

以下概念不得混淆：

```text
Lifecycle phase: discovery
→ 技术事实发现

Product Manager 的 product/requirement discovery
→ 归 intake / requirement / product

Project Autonomy discovery
→ Autonomy Domain 内部概念
```

因此不删除现有 `discovery` phase，也不因为名字相同把 Autonomy discovery 接入软件生命周期 phase。

---

# 21. Lifecycle / Role Matrix

| Phase | Primary Role | Conditional Roles |
|---|---|---|
| Intake | Product Manager | Architect / Security |
| Requirement | Product Manager | Architect / Security / Database |
| Product | Product Manager | Architect |
| Architecture | Software Architect | Tech Lead / Security / Database |
| Planning | Tech Lead | Architect / Database / Development |
| Development | Development Engineer | Database / Security |
| Verification | Test Engineer | Security / Database / Development |
| Review | Code Reviewer | Architect / Tech Lead / Security |
| Delivery | Integration Engineer | Test / Development / Database |

Role 可以重复出现。

Role 也可以跨 Phase。

这正是 v5.2.4 与旧“一个阶段 = 一个 Action Role”最大的区别。

---

# 22. 三层裁剪模型

v5.2.4 继续保留“95%任务轻量”的核心原因。

## 第一层：Phase 裁剪

L0～L3 决定哪些生命周期区域值得进入。

## 第二层：Role 裁剪

同一 Phase 只选择实际需要的角色。

## 第三层：Skill 裁剪

同一 Role 只加载当前需要的 Skill。

因此：

```text
完整软件工程能力很大
↓
单个 Task 实际执行图仍然很小
```

---

# 23. L0～L3 不删除，而是从 Action Pipeline 变成 Lifecycle Preset

## L0

典型：

```text
Development Engineer
→ Test Engineer（行为变化时）
```

例如：

- 小 Bug；
- 小重构；
- 单点配置；
- 明确代码修复。

---

## L1

典型：

```text
Product Manager（轻量 requirement）
→ Software Architect（轻量）
→ Development Engineer
→ Test Engineer
```

---

## L2

典型：

```text
Product Manager
→ Software Architect
→ Tech Lead（按需）
→ Development / Database
→ Test
→ Code Review
→ Integration
```

---

## L3

按风险动态加入：

```text
Security Engineer
Independent Architecture Review
Database Engineer
UltraPlan
UltraReview
更多验证
```

没有“所有 9 Role 必经”的设计。

---

# 24. 旧 7 步的价值怎样被保留

旧流程的 Happy Path 继续作为 routing policy 的重要经验。

例如当前 L1：

```text
requirement
architecture
development
verification
```

目标模型不是删除它，而是改成：

```text
requirement phase
→ Product Manager / requirement-analysis

architecture phase
→ Software Architect

development phase
→ Development Engineer

verification phase
→ Test Engineer
```

原来的步骤语义保留。

只是“动作”不再冒充“人员角色”。

---

# 25. Pre-Task：把原来外包给用户和其他 AI 的能力正式收回系统

## 25.1 输入成熟度可以不同

`tp-spec-coding` / `tp-software-lifecycle` 必须能处理：

### A. 原始一句话

```text
“客户想做一个会议室预约功能。”
```

进入 Product Manager。

### B. 一份客户文档

Product Manager：

```text
理解
拆分
澄清
规范化
形成可开发 Requirement
```

### C. 已经成熟的需求

快速判断 Requirement Ready：

```text
直接进入 Task
```

### D. 明确 Bug / Code Task

可以直接：

```text
L0 Task
```

---

## 25.2 不为了标准化强制长文档

标准化需求是：

```text
强制语义
```

不是：

```text
强制文件数量
```

简单需求可以只产生很短的 Requirement Result。

复杂客户文档才生成正式 requirement artifact。

---

# 26. Intake / Requirement Artifact 规范化

当前 intake 支持：

```text
requirement-knowledge.md
requirement-clarifications.md
requirement-decisions.md
```

v5.2.4 建议收敛成：

```text
requirement.md              # 有实际需求内容时的 canonical requirement
requirement-clarifications.md   # 仅真实澄清
requirement-decisions.md        # 仅真实决策
source/ or source refs          # 客户原始材料的来源/provenance
```

`requirement-knowledge.md` 的“需求事实”应重新评估：

- 当前项目长期事实 → Knowledge / Wiki；
- 当前需求引用的已知事实 → requirement refs；
- 不应再把 Knowledge 与 Requirement 混成一个概念。

迁移必须先做内容语义盘点，不能机械删除。

---

# 27. Task 创建边界

Task 仍然保持：

> **Requirement Ready 后创建。**

不是把 Task 往后移动。

不是让原始客户一句话立刻建 Task。

---

## 27.1 `task create` 不能再硬编码 Architect owner

当前：

```text
owner_role = tp-architecture-design
```

v5.2.4 必须删除这一旧模型假设。

目标：

```text
Task NEW
owner_role = tp-software-lifecycle
```

作为极短的 routing ownership；

首次 dispatch 后：

```text
owner_role = 实际 Formal Role
```

也可以由实现评估采用原子 create+route，但不得再硬编码某一专业角色。

---

# 28. Role Skill 层级

层数不是产品约束。

可以：

```text
Role
  ↓
Skill
  ↓
Sub-Skill
  ↓
Specialist
```

只要：

- 用户看不到复杂度；
- AI lazy load；
- 不默认全部调用；
- 不为每层记账。

---

# 29. 物理目录建议

v5.2.4 可以趁 canonical cutover 正式把软件工程 Skill 与其他领域隔离。

建议：

```text
agents/
├─ tp-spec-coding/
├─ tp-software-lifecycle/
├─ tp-project-autonomy/
├─ tp-base-maintenance/
├─ tp-knowledge/
└─ tp-wiki/

skills/
├─ software/
│  ├─ roles/
│  │  ├─ tp-product-manager/
│  │  ├─ tp-software-architect/
│  │  ├─ tp-tech-lead/
│  │  ├─ tp-security-engineer/
│  │  ├─ tp-development-engineer/
│  │  ├─ tp-database-engineer/
│  │  ├─ tp-test-engineer/
│  │  ├─ tp-code-reviewer/
│  │  └─ tp-integration-engineer/
│  │
│  └─ capabilities/
│     ├─ requirement-analysis/
│     ├─ task-decomposition/
│     ├─ interface-design/
│     ├─ testing-strategy/
│     ├─ technical-review/
│     └─ ...
│
└─ autonomy/
   └─ ...
```

前提：

- catalog 使用显式路径加载；
- Host 自动发现不是运行依赖；
- validator / doctor 能递归验证。

如果某宿主工具必须 flat skill layout，可在实施时验证后调整物理目录，但**逻辑模型不能退回 Action Role**。

---

# 30. Role Catalog v5.2.4

当前 `agents/role-catalog.yaml` 应继续作为单一角色目录，不新造第二 Registry。

但 schema 应升级。

建议：

```yaml
catalog_version: "5.2.4"
base_version: "5.2.4"

domain_agents:
  - id: tp-software-lifecycle
    type: domain-agent
    skill_path: agents/tp-software-lifecycle/SKILL.md

roles:
  - role_id: tp-product-manager
    domain: software
    skill_path: skills/software/roles/tp-product-manager/SKILL.md
    phases: [intake, requirement, product]
    capabilities:
      - requirement.analysis
      - requirement.clarification
      - requirement.decomposition
      - product.planning
      - product.design

  - role_id: tp-software-architect
    ...
```

Sub-Skill 是能力，不默认成为 Runtime owner。

---

# 31. Skill metadata

建议每个 capability Skill 声明：

```yaml
id: requirement-analysis
domain: software
type: capability
parent_roles:
  - tp-product-manager

capabilities:
  - requirement.analysis

load_policy:
  default: conditional
```

共享 Skill 可以：

```yaml
parent_roles:
  - tp-software-architect
  - tp-tech-lead
```

不强制单父节点。

---


# 32. Orchestration v5.2.4

## 32.1 Orchestration 不再维护“stage -> 唯一 Action Role”

目标：

```text
Stage / Phase
→ Role Policy
→ Role Resolver
→ 0..N Formal Roles
```

但 v5.2.3 已有两个与“角色”正交的重要维度必须完整保留：

```text
mode
effects
```

Role-first 不能把它们在重构中丢掉。

---

## 32.2 建议配置表达

示意：

```yaml
pipelines:
  L1:
    - phase: requirement
      primary_role: tp-product-manager
      mode: DIRECT
      effects: []

    - phase: architecture
      primary_role: tp-software-architect
      mode: AUTO_PLANNING
      effects: []

    - phase: development
      primary_role: tp-development-engineer
      mode: DIRECT
      effects: [repo_mutation]

    - phase: verification
      primary_role: tp-test-engineer
      mode: DIRECT
      effects: []

    - phase: review
      primary_role: tp-code-reviewer
      required: contextual
      mode: AUTO_REVIEW
      effects: []
```

L2/L3 可增加：

```yaml
- phase: planning
  primary_role: tp-tech-lead
  required: contextual
  mode: DIRECT
  effects: []

- phase: review
  primary_role: tp-code-reviewer
  required: true
  mode: AUTO_REVIEW
  effects: []
```

数据库 / 安全：

```yaml
conditional_roles:
  - role: tp-database-engineer
    trigger: database_risk

  - role: tp-security-engineer
    trigger: security_risk
```

---

## 32.3 `mode` 是执行策略，不再硬编码具体 Role ID

当前源码存在：

```text
AUTO_PLANNING must be owned by tp-architecture-design
AUTO_REVIEW must be owned by tp-verification-engineering
```

v5.2.4 必须删除这种：

```text
mode == specific old role id
```

的耦合。

改为 capability contract：

```yaml
tp-software-architect:
  orchestration_capabilities:
    - auto_planning_host

tp-code-reviewer:
  orchestration_capabilities:
    - auto_review_host
```

校验变成：

```text
AUTO_PLANNING
→ assigned primary role must declare auto_planning_host

AUTO_REVIEW
→ assigned primary role must declare auto_review_host
```

### 初始 canonical owner

```text
AUTO_PLANNING → tp-software-architect
AUTO_REVIEW   → tp-code-reviewer
```

Tech Lead、Security、Database、Test 等角色可以作为参与者，但不因为参与就自动获得主持权。

### Verification 与 Review 分离后的迁移

当前 `AUTO_REVIEW` 挂在旧 verification stage。

目标：

```text
verification
→ tp-test-engineer / DIRECT

review
→ tp-code-reviewer / AUTO_REVIEW
```

UltraReview 的候选审查、并行 Reviewer、收敛机制保留，但 host 从旧 `tp-verification-engineering` 迁到正式 `tp-code-reviewer`。

---

## 32.4 `effects` 是安全/执行边界，不是展示字段

当前：

```text
effects: [repo_mutation]
```

已经是 Autonomy Stage Effects / Execution Envelope 的关键 fail-closed 约束。

v5.2.4 必须保留：

```text
required_effects
allowed_effects
effect_not_allowed
```

完整语义。

多 Role 后，effects 应绑定到**具体 assignment / action**，而不是简单绑定 phase 名称。

默认示例：

| Role / Action | effects |
|---|---|
| Product Manager | `[]` |
| Software Architect | `[]` |
| Tech Lead | `[]` |
| Development Engineer 实现 | `[repo_mutation]` |
| Database Engineer 仅分析/设计 | `[]` |
| Database Engineer 执行 DDL/代码变更 | `[repo_mutation]` |
| Test Engineer | `[]` |
| Code Reviewer | `[]` |
| Security Engineer audit/scan | `[]` |
| Integration readiness | `[]` |
| Integration Engineer 实际 apply/merge | `[repo_mutation]` |

要求：

> **Role Resolver 增加条件角色，绝不能绕过 Execution Envelope。**

如果任何候选 assignment 需要：

```text
repo_mutation
```

而当前 `allowed_effects` 不允许，必须继续：

```text
CONFIRM / BLOCK / fail-closed
```

不能因为“这个角色是新角色”就跳过现有 Autonomy 安全边界。

---

## 32.5 Mode / Effects Migration Tests

至少验证：

1. `AUTO_PLANNING` 不再依赖旧 Role ID；
2. 无 `auto_planning_host` capability 的角色不能主持 Auto Planning；
3. `AUTO_REVIEW` 由 Code Reviewer 主持；
4. Verification 不因为从旧 Review 拆出而失去真实测试；
5. `repo_mutation` 在 Development 路径继续被要求；
6. Database 条件角色的写操作不能绕过 `allowed_effects`；
7. Integration 实际 Git mutation 不能绕过 `allowed_effects`；
8. Autonomy unattended route 在 effect 不允许时继续 fail-closed；
9. 重构前后的 Execution Envelope safety behavior parity PASS。

---

# 33. Adaptive Role Resolver

输入：

```text
Task facts
Requirement facts
Risk level
Flow level
Machine risk floor
Current phase
Current code impact
Verified events
User request
Config
```

输出：

```text
primary_role
conditional_roles
recommended_skills
depth_mode
reason_codes
```

Resolver 不建立新 DB。

Resolver 不建立新 public state。

Resolver 结果默认是当前路由事实。

---

# 34. Runtime 状态模型保持不变

仍然只有：

```text
NEW
ACTIVE
BLOCKED
COMPLETED
CANCELLED
```

以下不建立状态机：

```text
Lifecycle State
Role State
Skill State
Gate State
Artifact State
Review State
```

Review/Test 通过是：

```text
可信 event / evidence fact
```

不是 public workflow state。

---

# 35. Runtime 记录到什么粒度

默认只记正式责任角色：

```text
actor_role = tp-test-engineer
```

不需要把：

```text
unit-testing
api-testing
regression-testing
```

分别记成 owner。

如果对效果评估有价值，可 best-effort 写：

```json
{
  "capabilities_used": [
    "test.api",
    "test.regression"
  ]
}
```

但：

- 可缺；
- 不阻断；
- 不需要历史 migration；
- 不作为完成 Gate。

---

# 36. CLI-first 继续沿用现有成熟能力

继续复用：

```text
task checkpoint
task verify
task block
task resume
task complete
workflow next
workflow confirm
task delivery-converge
project upgrade-contract
task migration-plan
task migrate
```

本次不要重新造：

```text
role checkpoint
skill checkpoint
lifecycle checkpoint
gate checkpoint
```

---

# 37. Test / Review Runtime 语义需要拆开

当前 `task verify` 主要由 `tp-verification-engineering` 写最终 PASS。

新模型建议：

## Test Engineer

负责可信：

```text
TEST_RESULT
PASS / FAIL / NEEDS_FIX
```

可以复用现有 `VERIFICATION_COMPLETED` 事件语义，避免增加 DB 对象。

## Code Reviewer

负责可信：

```text
REVIEW_COMPLETED
PASS / NEEDS_FIX / FAIL
```

当前 Runtime 已经存在 `REVIEW_COMPLETED` trusted completion source，因此优先复用，不增加新表。

## Security

安全验证可以作为：

- REVIEW_COMPLETED 的 specialized review；
- 或 VERIFICATION_COMPLETED detail/evidence；

按现有 Runtime 能力选择，不为了角色完整增加状态。

---

# 38. UltraPlan 迁移

当前：

```text
UltraPlan
由 tp-architecture-design 启动并收敛
```

目标：

```text
UltraPlan
由 Software Architect 主持
必要时邀请：
Tech Lead
Database Engineer
Security Engineer
Development Engineer
```

候选方案仍保持隔离。

Orchestrator/Software Lifecycle 只决定：

```text
是否触发深度规划
```

不替 Architect 做结论。

---

# 39. UltraReview 迁移

当前：

```text
tp-verification-engineering
→ completeness / correctness / impact reviewers
```

目标：

```text
Code Reviewer 主持代码 Review
Test Engineer 主持行为验证
Security Engineer 负责安全专项
Software Architect 负责架构符合性
```

UltraReview 可以升级成“多正式角色隔离 Review”。

主收敛角色根据 Review 类型决定：

```text
代码质量 → Code Reviewer
测试事实 → Test Engineer
安全专项 → Security Engineer
架构专项 → Software Architect
```

最终 Task 能否进入 Delivery 由 Software Lifecycle Agent 根据可信结果组合判断。

---


# 40. Knowledge Convergence 重构原则

当前 `tp-delivery-convergence` 已经把：

```text
Task 驱动的 canonical Knowledge 内容收敛
```

与独立 `tp-knowledge` 系统维护区分开。

v5.2.4 继续保留“Task-driven convergence”这项能力，但**正式责任归位到 Knowledge Domain，而不是 Integration Engineer。**

---

## 40.1 目标边界

```text
Integration Engineer
        ↓
产生 verified delivery facts
        ↓
tp-software-lifecycle
        ↓
按策略触发 task-scoped knowledge handoff
        ↓
tp-knowledge
        ↓
task-knowledge-convergence
```

Integration Engineer 不判断：

```text
什么应该成为长期 Knowledge
什么应该 promote
什么应该 merge / supersede
```

它只提供事实。

---

## 40.2 `tp-knowledge` 增加 task-scoped convergence mode

独立 `tp-knowledge` 继续负责：

- Knowledge system；
- source ingest；
- normalization；
- audit；
- projection；
- global maintenance。

同时接管一个明确受限的 task-scoped capability：

```text
task-knowledge-convergence
```

输入只能是：

```text
Canonical Requirement refs
Architecture/Decision refs
Verified Test/Review facts
Delivery Result
Residual Risk
Task Findings marked reusable
```

输出继续沿用已有轻量 disposition 语义：

```text
CREATED
UPDATED
NO_CHANGE
DEFERRED
BLOCKED
```

---

## 40.3 不允许 Knowledge 重新成为交付收费站

默认：

```text
NO_CHANGE
```

必须是合法且低成本结果。

Knowledge convergence：

- 不重读整个 Task；
- 不重新做 Review；
- 不重新总结所有代码；
- 不阻塞普通 Delivery，除非 Knowledge Runtime 本身出现可信数据完整性问题；
- 继续受现有 fast path / <=5% 增量治理预算约束。

这样既保留 v5.2.3 已成熟的 Task-driven Knowledge 能力，又避免把 Integration Engineer 做成第二个 `tp-delivery-convergence` 巨型角色。

---

# 41. 为什么新的上游生命周期会改善 Knowledge

过去：

```text
客户输入
→ 用户+其他AI在系统外讨论
→ 只把结果送入 Task
```

TP-Spec-Coding 缺少：

```text
原始输入
→ Requirement
→ Decision
→ Architecture
```

的完整正规事实链。

v5.2.4 后：

```text
Source / Request
     ↓
Product Manager
     ↓
Canonical Requirement
     ↓
Architecture Decision
     ↓
Task
     ↓
Implementation / Test / Review
     ↓
Integration
     ↓
Knowledge Convergence
```

Knowledge Agent 将更容易判断：

```text
什么是客户原始描述
什么是确认需求
什么是架构决策
什么只是过程讨论
什么是可复用经验
什么是真正长期 Knowledge
```

---

# 42. 一次性 Canonical Cutover 原则

v5.2.4 完成后，active runtime 只存在一套 Role Model：

```text
Product Manager
Software Architect
Tech Lead
Security Engineer
Development Engineer
Database Engineer
Test Engineer
Code Reviewer
Integration Engineer
```

以下旧 Role 不得继续存在于 active role-catalog：

```text
tp-requirement-analysis
tp-product-design
tp-architecture-design
tp-architecture-review
tp-development-engineering
tp-verification-engineering
tp-delivery-convergence
```

---

# 43. 历史数据怎么处理

## 43.1 Completed Task

不重写历史 event。

例如：

```text
actor_role = tp-development-engineering
```

仍然保留。

这是历史事实。

历史展示层可读取 migration metadata，把它解释为：

```text
Legacy Development Action Role
```

但不把旧 Role 加回 active catalog。

---

## 43.2 Active Task

必须正式迁移。

推荐默认映射：

| Old current owner | New canonical owner |
|---|---|
| `tp-requirement-analysis` | `tp-product-manager` |
| `tp-product-design` | `tp-product-manager` |
| `tp-architecture-design` | `tp-software-architect` |
| `tp-architecture-review` | `tp-software-architect` |
| `tp-development-engineering` | `tp-development-engineer` |
| `tp-verification-engineering` | `tp-test-engineer` |
| `tp-delivery-convergence` | `tp-integration-engineer` |

注意：

`tp-development-engineering` 不自动猜测成 Database Engineer。

如果现有证据不足：

```text
先迁为 Development Engineer
→ 下一次 Role Resolver 再决定是否加入 Database Engineer
```

不为迁移猜事实。

---

# 44. Migration Mapping 不允许成为 Runtime 尾巴

可以存在：

```text
migrations/5.2.3-to-5.2.4/role-map.yaml
```

但正常 Runtime：

```text
不得加载
```

它只服务：

```text
upgrade-contract
task migrate
historical rendering tests
```

这是迁移资产，不是 active compatibility layer。

---

# 45. Contract Migration 必须使用仓库现有正式链

本次即使做大迁移，也不能绕过已经成熟的 contract discipline。

正式路径：

```text
Base v5.2.4 cutover
    ↓
project upgrade-contract --to 5.2.4
    ↓
task migration-plan
    ↓
task migrate --to 5.2.4
    ↓
doctor / verify
```

---

# 46. v5.2.4 Active Contract

发布完成后：

```text
VERSION = 5.2.4
```

`compat-matrix.yaml`：

```text
只保留唯一 active contract 5.2.4
```

历史版本继续由 Git release/tag 承担。

---

# 47. `templates/5.2.4`

必须新建。

原则：

- 复制并迁移真正仍有价值的 5.2.3 模板；
- 不为了 Role 多了就增加 9 套模板；
- Capability / Sub-Skill 默认不对应固定 Markdown；
- Requirement Artifact 做真正需要的标准化；
- Machine metadata 继续由 Runtime 处理。

---


# 48. 具体源码改造热点与 Role Reference Inventory

第二轮源码复核证明：

> **不能再用“手工列出 10 个热点文件”作为迁移边界。**

当前旧 Role ID 分布在 active runtime、兼容层、CLI 白名单、可信事件、Mode 校验、Review 工具、Execution Package 路径、文档/注释等多个维度。

因此 Phase 0 必须先机器生成：

```text
V523_ROLE_REFERENCE_INVENTORY.json
V523_ROLE_REFERENCE_INVENTORY.md
```

Inventory 至少包含：

```text
path
line
old_role_id
reference_kind
runtime_classification
replacement_target
migration_action
```

`runtime_classification`：

```text
ACTIVE_RUNTIME
ACTIVE_CLI
ACTIVE_GOVERNANCE
LEGACY_COMPAT
MIGRATION_ONLY
TEST
FIXTURE
DOC_CURRENT
DOC_HISTORY
COMMENT
```

Release no-tail scanner 使用该分类，而不是复用手写文件列表。

---

## 48.1 已确认的 Active Runtime / CLI 热点

### `cli/commit_cmd.py`

这是当前最集中的旧 Role 绑定之一，必须作为 P0 hotspot。

已确认包括：

- `_ALLOWED_ACTORS`；
- Architecture 同 owner 微循环；
- Development / Verification / Delivery actor 判断；
- `--review-only` 限制；
- CLOSING owner；
- COMPLETED owner；
- DIRECT_CHANGE actor；
- trusted Verification PASS；
- `transition_service` legacy writer 调用。

该文件不能只做字符串替换。

必须裁决：

> v5.2.4 是否还保留 legacy `tp-spec commit` 作为 active command。

本计划裁决：

```text
不保留。
```

Record-first 原子 API 已经是 canonical 日常写入口。

`tp-spec commit` 的 legacy long-state 写能力进入 migration/admin history scope，不继续参与正常 v5.2.4 routing。

---

### `cli/receipt_cmd.py`

处理：

```text
_ALLOWED_ACTORS
```

以及任何 old role ownership/receipt validation。

---

### `cli/review_cmd.py`

当前正式 Architecture Review CLI 强绑定：

```text
tp-architecture-review
```

必须迁为：

```text
tp-software-architect
+ architecture-review capability
+ isolated context proof
```

不能因为角色 ID 合并而降低独立评审约束。

---

### `cli/orchestration.py`

除 stage->role 外，还必须处理：

```text
AUTO_PLANNING role hard check
AUTO_REVIEW role hard check
UltraPlan capability ownership
UltraReview capability ownership
VERIFICATION_COMPLETED actor hard check
REVIEW_COMPLETED architecture actor hard check
rework source role
role maps
effects
allowed_effects
required_effects
```

---

### `cli/record_first.py`

已确认包含：

```text
旧 allowed actor set
architecture role special case
verification actor hard check
technical verification owner
```

必须整体按正式 Role / trusted result contract 迁移。

---

### `cli/workflow_records.py`

已确认包含：

```text
tp-delivery-convergence
tp-verification-engineering
DELIVERY_RESULT actor/owner
delivery current_stage update
trusted verification record
```

---

### `cli/workflow_loader.py`

已确认包含：

```text
completion_owner = tp-delivery-convergence
legacy state owner map import
```

Role-first 后 completion owner 必须改用新的 canonical contract。

---

### `cli/delivery_contract.py`

已确认包含：

```text
verification actor
delivery actor
```

迁移为 Test / Integration / Knowledge 的新边界。

---

### `cli/context_effectiveness.py`

当前有效性统计对：

```text
tp-verification-engineering
```

存在 actor hard check。

必须迁移，否则 telemetry 会在新角色模型下静默失真。

---

### `cli/autonomy_integration.py`

当前写入 verification actor：

```text
tp-verification-engineering
```

必须迁移，同时保持 Autonomy canonical apply 的可信 Verification 绑定。

---

## 48.2 已确认的 Task / Session / Projection 热点

### `cli/task_cmd.py`

处理：

- Task create 硬编码 `tp-architecture-design`；
- verify 默认 actor；
- old owner migration；
- phase validation；
- discovery 保留；
- v5.2.4 active contract。

---

### `cli/work_session_cmd.py`

移除：

```text
tp-architecture-design
```

fallback。

---

### `cli/rework_cmd.py`

移除旧 owner fallback，改为新 Role Resolver / current owner。

---

### `cli/projection_cmd.py`

历史旧 actor 可原样显示。

active owner fallback 不得再使用旧 Role。

---

## 48.3 Review / Evidence / Execution Package 热点

### `cli/review_preflight.py`

当前路径和提示包含：

```text
.execution/<TASK-ID>/tp-development-engineering/review/
tp-verification-engineering handoff
```

必须迁为与正式 Role / review session 绑定的 neutral execution layout，例如：

```text
.execution/<TASK-ID>/review/<review-session-id>/
```

避免物理路径继续固化旧 Role 模型。

---

### `cli/reuse_warnings.py`

用户/AI 警告文案仍以旧 Verification Role 为主语。

应改成正式：

```text
Test Engineer / Code Reviewer
```

语义。

---

### `cli/anchor_check.py`

finding handoff 仍引用旧 Verification Role，需要迁移。

---

### `cli/main.py`

当前 Architecture Review command 注释/Help 仍引用旧 Role。

current product docs/help 不允许残留旧 canonical role。

---

## 48.4 Legacy Compatibility Layer：正式裁决

### 当前事实

`cli/legacy_workflow.py` 明确自述：

```text
Frozen pre-Record-first workflow decoder
```

虽然目标用途是旧 ledger history / migration / forensics，但当前源码仍有 active 解析路径直接依赖其常量：

```text
cli/config_loader.py
→ import LEGACY_STATE_OWNERS

cli/workflow_loader.py
→ import LEGACY_STATE_OWNERS, LEGACY_TRANSITIONS
```

这两处是 `legacy_workflow.py` 迁出 active runtime 的直接阻碍，必须进入 Phase 0 `V523_LEGACY_CALL_GRAPH.md` 与迁移工作项，不能被视为“只是历史代码”。

`cli/transition_service.py` 明确自述：

```text
legacy transition compatibility / recovery service
```

但它仍被：

```text
commit_cmd
event_cmd admin-recover
review_cmd utility import
validator
```

等路径调用，因此**当前还不能简单视为“纯历史文件”**。

---

## 48.5 v5.2.4 Legacy 策略：Split → Migrate → Retire

本计划不把二者加入永久 active allowlist。

### A. `legacy_workflow.py`

迁入 migration/history-only，例如：

```text
cli/migrations/v5_2_3/legacy_workflow.py
```

用途限定：

```text
task migrate
old ledger decode
historical rendering
forensics
migration tests
```

迁出前必须先消除 active caller：

```text
cli/config_loader.py
→ 删除对 LEGACY_STATE_OWNERS 的 active fallback 依赖

cli/workflow_loader.py
→ 删除对 LEGACY_STATE_OWNERS / LEGACY_TRANSITIONS 的 active workflow 回填依赖
→ 该 legacy state 回填逻辑迁入 migration/history-only
```

active Runtime 不允许 import `legacy_workflow`，也不允许通过复制旧 long-state owner/transition matrix 的方式变相保留相同兼容逻辑。

---

### B. `transition_service.py`

不能直接删除，因为里面混有：

- legacy long-state transition；
- trusted gate validation；
- YAML/frontmatter 辅助；
- durable journal 写入；
- admin recovery；
- 当前部分 CLI 复用的通用函数。

实施必须先拆分：

```text
通用且仍需要的能力
→ 中性 current-runtime 模块

legacy long-state transition matrix / old role rules
→ migration/history-only 模块
```

完成后：

```text
cli/transition_service.py
```

作为 active compatibility service 退役。

---

### C. legacy `tp-spec commit`

v5.2.4 canonical Runtime 不继续暴露旧 long-state commit 作为正常研发写入口。

正常研发只使用 Record-first：

```text
task checkpoint
task block
task resume
task verify
task complete
workflow next
workflow confirm
```

若迁移期间需要解释/修复旧 long-state：

```text
migration/admin command
```

必须显式进入 legacy scope，不得让正常 Task 路由触发。

---

## 48.6 No-tail Scanner 必须全仓扫描

Release 前新增机器检查，例如：

```text
tp-spec base doctor --role-references
```

或独立 CI script。

它对 tracked files 扫描全部旧 Role ID。

默认策略：

```text
DENY
```

允许目录/文件必须显式 allowlist。

允许：

```text
CHANGELOG.md
migrations/5.2.3-to-5.2.4/**
cli/migrations/v5_2_3/**
tests/migration/**
tests/fixtures/history/**
docs/history/**   （若仓库确有）
```

禁止：

```text
cli active runtime
governance active contract
agents active catalog
skills active model
README current architecture
current CLI help
active tests expected behavior
```

不再用“第 48 节列到的文件”作为 scanner 白名单。

---

## 48.7 Hotspot Inventory 是动态 Gate

如果实施过程中 scanner 新发现旧 Role：

```text
必须分类
↓
ACTIVE → 迁移
HISTORY/MIGRATION → 明确白名单
UNKNOWN → FAIL
```

不能：

```text
为了让 no-tail 绿
→ 临时追加整个目录到 allowlist
```

这条是 P0 Release Discipline。

---

# 49. Governance 文件目标

## `governance/ai-role.yaml`

从：

```text
Action role definitions
```

升级成：

```text
Formal engineering roles
Domain agents
role responsibilities
boundaries
```

---

## `governance/orchestration.yaml`

从：

```text
stage -> action role
```

升级成：

```text
lifecycle preset
phase policy
formal role resolution
conditional role triggers
```

---

## `governance/workflow.yaml`

继续负责：

- 5 public states；
- transitions；
- phase-as-fact；
- Record-first；
- hard block / warn-only。

不承担 Formal Role Catalog。

---

## `agents/role-catalog.yaml`

成为：

```text
Domain Agent + Formal Role + Skill path
```

的单一目录。

---

## `governance/risk-rule.yaml`

保留当前风险价值。

新增/调整：

```text
security role trigger
database role trigger
code review depth
architecture depth
testing depth
```

优先配置化。

---

## `governance/planning-strategy.yaml`

拆开：

```text
Architecture planning
Technical execution planning
```

UltraPlan 主持人改为 Software Architect。

Tech Lead 负责实施计划。

---

# 50. Product Experience

## 50.1 用户默认入口

```text
tp-spec-coding
```

---

## 50.2 用户默认不需要知道

- Role ID；
- Skill path；
- Lifecycle preset；
- phase；
- event id；
- contract digest；
- actor agent；
- Sub-Skill；
- Workspace fencing generation。

---

## 50.3 Status

用户看到：

```text
任务：园区门禁授权调整
当前：开发
负责：开发工程师
风险：L2

已完成：
✓ 需求
✓ 架构
✓ 技术规划

进行中：
● 实现

后续：
○ 测试
○ Code Review
○ 集成

阻塞：无
需要你：无
```

不是 Runtime dump。

---

## 50.4 Explain

用户：

```text
为什么调用安全工程师？
```

系统基于：

```text
risk-rule
route reason
当前修改范围
```

解释。

不另建 Explain Ledger。

---

# 51. Upgrade Implementation Plan

---


## Phase 0 — Freeze v5.2.3 Truth

### 目标

在重构前固定所有必须保留的现有行为，并把旧 Role ID 的真实依赖面一次扫描完整。

### 工作

1. Full test baseline；
2. Role / Skill inventory；
3. CLI inventory；
4. Runtime event inventory；
5. L0～L3 route snapshots；
6. UltraPlan snapshot；
7. UltraReview snapshot；
8. Delivery snapshot；
9. Autonomy snapshot；
10. Wiki / Knowledge / Base snapshot；
11. active Task inventory；
12. 用户项目 / Config / Memory / Knowledge 备份；
13. **repo-wide old Role ID reference scan**；
14. 每个 reference 分类为 ACTIVE / LEGACY / MIGRATION / HISTORY / TEST / DOC；
15. 生成 replacement/migration action；
16. 冻结 `mode` / `effects` 当前语义与 safety tests；
17. 冻结 `discovery` phase 当前语义；
18. 记录 `legacy_workflow.py` / `transition_service.py` 所有 active callers；
19. **显式确认 `cli/config_loader.py` 对 `LEGACY_STATE_OWNERS` 的 active fallback 依赖**；
20. **显式确认 `cli/workflow_loader.py` 对 `LEGACY_STATE_OWNERS / LEGACY_TRANSITIONS` 的 active workflow 回填依赖**；
21. 为上述两处定义“迁出 active parser、归入 migration/history-only”的 replacement action；
22. 冻结 architecture review independence 当前行为证据；
23. 冻结 Product Entry 不存在时的当前调用成本基线。

### 输出

```text
V523_BASELINE_CAPABILITY_MATRIX.md
V523_ACTIVE_TASK_MIGRATION_INVENTORY.json
V523_ROLE_REFERENCE_INVENTORY.json
V523_ROLE_REFERENCE_INVENTORY.md
V523_MODE_EFFECTS_BASELINE.json
V523_LEGACY_CALL_GRAPH.md
```

这些是实施/迁移证据，不是日常产品模板。

### Gate

Phase 0 未完成 repo-wide Role Reference Inventory 前：

> **禁止开始 active Role ID 批量替换。**

否则 no-tail 与 workload estimate 都不可信。

---

## Phase 1 — Target Role Contract

### 目标

先把 v5.2.4 正式角色模型写成 contract，不改 Runtime 行为。

### 工作

- formal role catalog；
- role responsibility；
- role boundaries；
- Skill mapping；
- old->new capability parity map；
- lifecycle/role matrix；
- L0～L3 target presets；
- migration role map。

### Gate

评审必须确认：

> 每一个 v5.2.3 软件开发能力都有明确新归属。

---

## Phase 2 — Build New Role Skills

建立：

```text
tp-product-manager
tp-software-architect
tp-tech-lead
tp-security-engineer
tp-development-engineer
tp-database-engineer
tp-test-engineer
tp-code-reviewer
tp-integration-engineer
```

第一轮主要做：

```text
迁移现有能力
```

而不是急着扩能力。

### Gate

现有能力 parity PASS。

---

## Phase 3 — Expand Role Capabilities

在 parity 后再增加真正新能力。

### Product Manager

- product-planning；
- requirement-decomposition；
- requirement-impact；
- acceptance；
- requirement-review。

### Architect

- technology selection；
- interface design；
- compatibility；
- reliability；
- migration architecture。

### Tech Lead

- coding standard；
- technical planning；
- engineering guideline；
- dependency planning。

### Security

- audit；
- scanning；
- authn/authz；
- secret/dependency scan。

### Development

- frontend；
- backend；
- refactoring；
- performance；
- concurrency。

### Database

- modeling；
- migration；
- index；
- consistency；
- performance。

### Test

- unit；
- integration；
- API；
- regression；
- acceptance。

### Reviewer

- diff；
- correctness；
- standards；
- maintainability；
- regression risk。

### Integration

- readiness；
- Git；
- post integration；
- release readiness。

---

## Phase 4 — Product Entry & Domain Agent

### 工作

新增：

```text
tp-spec-coding
tp-software-lifecycle
```

迁移：

```text
tp-workflow-orchestrator
→ software lifecycle domain responsibilities
```

保留 CLI orchestration mechanism。

### Gate

active agents 中不能同时存在两个软件开发入口。

---


## Phase 5 — Orchestration Role-first Cutover

### 工作

把 L0～L3：

```text
stage -> old action role
```

改成：

```text
phase -> role policy -> formal roles
```

实现：

- Role Resolver；
- conditional role；
- Skill lazy load；
- rework route；
- UltraPlan route；
- UltraReview → Code Reviewer host；
- Architecture Review isolated route；
- `mode` capability-based validation；
- `effects` assignment-level preservation；
- Autonomy Execution Envelope parity。

### Mode Cutover

```text
AUTO_PLANNING
old owner hardcode: tp-architecture-design
new: requires auto_planning_host capability
default host: tp-software-architect
```

```text
AUTO_REVIEW
old owner hardcode: tp-verification-engineering
new: requires auto_review_host capability
default host: tp-code-reviewer
```

### Effects Cutover

`repo_mutation` 必须原样保留安全语义。

多 Role 路径中：

```text
每个 assignment 独立声明 required effects
```

不能用 phase 是否可写来替代。

### Gate

- 五态不变；
- DB schema 默认不变；
- `new_public_states == false`；
- `new_database_objects == false`；
- Autonomy effect fail-closed parity PASS；
- UltraPlan parity PASS；
- UltraReview parity PASS；
- Architecture Review isolation PASS。

---

## Phase 6 — Pre-task Product / Requirement Integration

### 工作

- Product Manager 接管 raw request；
- standard Requirement Ready；
- intake artifact 规范化；
- `task create --from-intake` 迁移；
- 不强制空文档；
- 已成熟输入快速进入 Task。

### Gate

同一明确 L1 需求，相比 v5.2.3 不得显著增加交互成本。

---

## Phase 7 — Test / Review / Security Separation

### 工作

把当前 `tp-verification-engineering` 真实职责拆出：

```text
Test Engineer
Code Reviewer
Security Engineer
```

并定义可信结果怎样写入现有 Runtime。

### Gate

不得出现：

```text
开发者自称 PASS
→ 直接完成
```

独立审查质量不得下降。

---

## Phase 8 — Delivery / Knowledge / Integration Cutover

### 工作

`tp-delivery-convergence` 迁入：

```text
Integration Engineer
```

保留：

- structured Delivery Result；
- targeted Knowledge search；
- CREATED/UPDATED/NO_CHANGE/DEFERRED/BLOCKED；
- latest Verification binding；
- <=5% fast path。

### Gate

Knowledge 系统维护与 Task-driven convergence 仍然分离。

---

## Phase 9 — One-time Migration Rehearsal

必须在**真实用户项目副本**上演练。

### 流程

```text
copy project/runtime
→ upgrade-contract
→ migration-plan
→ migrate active tasks
→ doctor
→ workflow next
→ continue task
→ verify
→ complete
```

### 验证

- active Task 可继续；
- old history 可读；
- old role 不进入 active routing；
- Config 不丢；
- Wiki/Knowledge/Memory 不丢；
- project binding 不丢；
- Runtime integrity PASS。

---

## Phase 10 — Canonical Contract Cutover

更新：

- `VERSION`;
- `compat-matrix.yaml`;
- `workflow.yaml`;
- `ai-role.yaml`;
- `orchestration.yaml`;
- `risk-rule.yaml`;
- `planning-strategy.yaml`;
- `role-catalog.yaml`;
- `runtime-api.yaml`（如契约内容变化）；
- `config_schemas.py`;
- Agent / Skill frontmatter；
- `templates/5.2.4`;
- manifest / snapshot；
- README / docs。

---


## Phase 11 — Remove Active Legacy Model

删除 active：

```text
agents/tp-workflow-orchestrator/
skills/tp-requirement-analysis/
skills/tp-product-design/
skills/tp-architecture-design/
skills/tp-architecture-review/
skills/tp-development-engineering/
skills/tp-verification-engineering/
skills/tp-delivery-convergence/
```

同时完成 Legacy Runtime 退役：

```text
cli/legacy_workflow.py
→ 移入 migration/history-only

cli/transition_service.py
→ 拆分通用 current-runtime 能力
→ legacy long-state 规则移入 migration/history-only
→ active compatibility service 退役

legacy tp-spec commit long-state path
→ 从 canonical daily runtime 移除
```

前提：

- 内容已经迁入；
- parity test PASS；
- migration rehearsal PASS；
- active role-catalog 无旧 Role 引用；
- active orchestration 无旧 Role 引用；
- current docs/help 无旧 Role 引用；
- active CLI 无旧 Role actor whitelist；
- active Runtime 无旧 Role trusted-event hardcode；
- admin recovery 已有 five-state/current replacement；
- historical ledger 仍可 raw-read；
- migration tools 仍可解释 v5.2.3 legacy data；
- repo-wide role-reference scanner PASS。

**不允许通过把整个 `cli/` 或 compatibility 文件加入 no-tail allowlist 来跳过迁移。**

---


# 52. 测试策略

## 52.1 Capability Parity Tests

必须证明：

```text
v5.2.3 会做的
v5.2.4 都会做
```

包括：

- pre-task requirement；
- product design；
- risk；
- technical discovery；
- UltraPlan；
- architecture review；
- development self test；
- debugging；
- verification；
- UltraReview；
- delivery convergence；
- task-scoped knowledge disposition；
- memory capture。

---

## 52.2 Role Separation Tests

### Product Manager

不得修改业务代码。

### Architect

不得代替 Developer 写实现。

### Tech Lead

不得静默改变产品需求。

### Security

不得自动执行未授权高风险操作。

### Developer

不得给自己写最终 Code Review PASS。

### Test Engineer

必须基于真实 Evidence。

### Code Reviewer

必须独立读取真实 Diff/Code。

### Integration

不得重新裁决测试 PASS，也不得自行判断长期 Knowledge。

### Knowledge Agent

task-scoped convergence 只能基于已验证 Task/Delivery 事实，不能重新执行开发/测试/Review。

---

## 52.3 Architecture Review Independence Tests

必须增加独立测试，不允许只由“capability parity”间接覆盖。

至少验证：

1. architecture design execution 与 formal review 使用不同 execution context；
2. same context id 时 formal Architecture Review PASS 被拒绝；
3. Review 输入不包含 design scratchpad / private chain；
4. Review subject digest 与被评审 architecture artifact 绑定；
5. stale architecture artifact 不能复用旧 Review PASS；
6. Architect self-check 不等于 formal Review PASS；
7. required architecture review 缺 isolation proof 时 fail-closed。

---

## 52.4 Mode / Effects Tests

必须验证：

- `AUTO_PLANNING` capability host；
- `AUTO_REVIEW` capability host；
- old role-id hard checks 消失；
- Development repo mutation effect 保留；
- Database/Integration 条件写操作声明 effect；
- Autonomy allowed_effects 继续限制新角色；
- conditional role 不能绕过 effect confirmation；
- no-effect read/review role 不被误判为 repo mutation。

---

## 52.5 Legacy Removal Tests

必须验证：

- current runtime 不 import `legacy_workflow`；
- `config_loader.py` 不再读取 `LEGACY_STATE_OWNERS`；
- `workflow_loader.py` 不再读取 `LEGACY_STATE_OWNERS / LEGACY_TRANSITIONS`；
- current runtime 不 import legacy long-state transition matrix；
- normal user flow 不调用 legacy `tp-spec commit`；
- migration tooling 仍能读取 v5.2.3 legacy history；
- historical actor_role 可原样展示；
- completed historical events 不要求映射到 active catalog 才可读。

---

# 53. 场景测试

至少覆盖：

## Scenario A — 一句话产品需求

```text
“做一个会议室预约功能。”
```

验证 Product Manager 能先规范化。

---

## Scenario B — 客户长文档

验证：

```text
source
→ requirement decomposition
→ requirement ready
→ task
```

---

## Scenario C — 明确简单 Bug

应快速走：

```text
L0
Development
→ Test
```

不能强制 Product Manager / Architect 全部重新走。

---

## Scenario D — 数据库迁移

调用：

```text
Architect
Tech Lead
Database Engineer
Developer
Test
Code Reviewer
Integration
```

按实际风险裁剪。

---

## Scenario E — 权限 / 敏感数据

必须正确触发 Security Engineer。

---

## Scenario F — Review 别人代码

用户可以直接：

```text
tp-spec-coding:
Review 这个提交
```

无需伪造一条“开发任务”。

系统进入：

```text
Code Reviewer
+ Test/Security/Architect（按需）
```

---

## Scenario G — 现有成熟 Requirement

系统应识别：

```text
Requirement Ready
```

快速进入 Task，不重复做产品分析。

---

# 54. Migration Tests

必须测试：

- 5.2.3 project → 5.2.4；
- active requirement task；
- active architecture task；
- active development task；
- active verification task；
- active delivery task；
- BLOCKED task；
- no-op repeated migration；
- interrupted migration recovery；
- project contract switch but task not migrated；
- task migrate before project switch（应拒绝）；
- completed history immutable。

---


# 55. No-tail Tests

No-tail 不再是一个手写 grep 清单，而是 repo-wide machine gate。

## 55.1 扫描对象

对 Git tracked files 扫描以下旧 Role ID：

```text
tp-requirement-analysis
tp-product-design
tp-architecture-design
tp-architecture-review
tp-development-engineering
tp-verification-engineering
tp-delivery-convergence
```

---

## 55.2 默认规则

```text
DEFAULT = DENY
```

旧 Role 只允许出现在：

```text
CHANGELOG.md
migrations/5.2.3-to-5.2.4/**
cli/migrations/v5_2_3/**
tests/migration/**
tests/fixtures/history/**
docs/history/**（若存在）
```

允许范围必须**精确到用途**。

---

## 55.3 明确禁止

不得出现在：

```text
active role-catalog
active orchestration
active ai-role
active workflow/current config
active Agent/Skill frontmatter
task create fallback
work session fallback
record_first actor validation
commit/receipt current actor whitelist
current review CLI actor whitelist
Runtime trusted event rule
workflow completion owner
context effectiveness current actor logic
Autonomy current integration binding
README current architecture
CLI current help
current product warnings
current execution package path
```

---

## 55.4 Legacy 文件不再自动白名单

以下当前文件：

```text
cli/legacy_workflow.py
cli/transition_service.py
```

**不能因为名字叫 legacy 就直接加入 no-tail allowlist。**

R2 裁决是：

```text
迁出 active runtime
→ migration/history-only
```

完成后它们的 legacy 内容必须位于允许的 migration/history 路径。

---

## 55.5 Scanner 行为

新发现引用：

```text
ACTIVE / UNKNOWN
→ FAIL

MIGRATION / HISTORY
→ 必须命中显式 allowlist
```

CI 输出：

```text
path
line
old_role
classification
reason
```

禁止使用：

```text
ignore whole cli/
ignore whole tests/
```

这类大范围逃逸规则。

---


# 56. Product Cost Tests

普通 L0/L1 Task：

- 用户额外确认不增加；
- 固定 Markdown 数不增加；
- Sub-Skill 不全加载；
- Role 切换不生成额外账本；
- Status/Explain 不触发全 Task 重读；
- pure governance incremental overhead 目标 <=5%。

---

## 56.1 `tp-spec-coding` Router Cost Tests

对明确 Domain 输入：

```text
“Review 这个提交”
“更新 Wiki”
“继续当前开发任务”
“检查 Knowledge”
```

Router 必须：

- 不扫描 repo；
- 不读取完整 Task；
- 不读取需求正文；
- 不查询 Knowledge/Wiki；
- 不启动子 Agent；
- 不执行深度需求分析；
- 只返回轻量 domain decision；
- 原始 payload 不被二次总结丢失。

测试可以通过 mock/spies 断言：

```text
repository_reader not called
knowledge_search not called
task_full_load not called
subagent_spawn not called
```

对于模糊输入，最多先进行一次浅层分类；需要用户澄清时只问 Domain 层面的最小问题。

---

## 56.2 Role / Skill Lazy-load Cost Tests

- Product Manager 不默认加载全部产品 Skill；
- Architect 不默认加载 Database/Security；
- Developer 不默认加载 Frontend+Backend+DB 全套；
- Test Engineer 不默认执行所有测试类型；
- Code Reviewer 不重新读取不相关全仓内容；
- Integration 不重新做 Verification；
- Knowledge task convergence 不重新总结完整 Task。

---


# 57. Release Gate

发布前至少要求：

1. Full pytest PASS；
2. role catalog doctor PASS；
3. workflow doctor PASS；
4. active contract PASS；
5. migration rehearsal PASS；
6. real-project copy rehearsal PASS；
7. capability parity PASS；
8. **repo-wide role-reference no-tail PASS**；
9. **legacy active-runtime removal PASS**；
10. **mode / effects parity PASS**；
11. **Architecture Review isolation PASS**；
12. version purity PASS；
13. manifest/snapshot PASS；
14. documentation currentity PASS；
15. product router cost PASS；
16. governance overhead budget PASS；
17. user product smoke PASS。

Release Gate 输出必须明确区分：

```text
old role references allowed in migration/history
old role references forbidden in active runtime
```

不得通过扩大 allowlist 把 active reference 隐藏掉。

---

# 58. 评审员验收清单

## 必须 PASS

- [ ] 能解释为什么从 Action-first 切到 Role-first；
- [ ] 旧 7 步的能力全部有新归属；
- [ ] 新 9 Role 是正式责任角色，不是流程步骤改名；
- [ ] `tp-spec-coding` 是唯一默认用户入口；
- [ ] `tp-software-lifecycle` 是唯一 software domain agent；
- [ ] `tp-workflow-orchestrator` 不再作为 active 用户 Agent；
- [ ] Runtime 仍只有五态；
- [ ] phase 仍然只是事实；
- [ ] L0～L3 仍能让普通任务轻量；
- [ ] pre-task Requirement Ready 逻辑保留并增强；
- [ ] Task 没有被错误提前创建；
- [ ] CLI-first/Record-first 保留；
- [ ] pure governance overhead 不因角色化显著上升；
- [ ] old Role 只存在 migration/history，不参与 active routing；
- [ ] project upgrade-contract + task migrate 被完整使用；
- [ ] 用户 Wiki / Knowledge / Memory / Config / Task 数据不丢。

---

## 必须 FAIL

出现以下任一项：

- [ ] 为兼容代码而继续把旧 7 Action Role 作为未来 canonical Role；
- [ ] 新 Role 只是旧 Role 下的装饰子层；
- [ ] 新旧软件 workflow 长期双轨；
- [ ] 新增 Lifecycle/Gate/Role public state machine；
- [ ] 每个 Task 强制走完 9 Role；
- [ ] 每个 Role 强制执行全部 Sub-Skill；
- [ ] 为每个 Sub-Skill 记账；
- [ ] 因可推导 metadata 缺失回退上一步；
- [ ] 新架构削弱 UltraPlan / UltraReview / Autonomy / Knowledge / Wiki；
- [ ] active Task migration 依赖人工重新整理；
- [ ] 升级要求用户重新配置 Base/Wiki/Knowledge；
- [ ] 删除历史事件中的旧 actor_role 以追求“看起来统一”。

---

# 59. 最终目标架构

```text
                              USER
                               │
                               ▼
                       tp-spec-coding
                    唯一默认产品入口
                               │
         ┌─────────────────────┼─────────────────────────┐
         │                     │                         │
         ▼                     ▼                         ▼
tp-software-lifecycle       tp-wiki                tp-knowledge
         │
         ├──────────────── tp-base-maintenance
         └──────────────── tp-project-autonomy
         │
         ▼
─────────────────────────────────────────────────────────────
                SOFTWARE ENGINEERING LIFECYCLE
─────────────────────────────────────────────────────────────

Pre-Task
Raw Request
   ↓
Product Manager
   ├─ product planning
   ├─ requirement analysis
   ├─ clarification
   ├─ decomposition
   ├─ scope
   └─ acceptance
   ↓
Requirement Ready
   ↓
Task

Task Delivery
   ↓
Software Architect
   ├─ system design
   ├─ technology selection
   ├─ interface design
   └─ architecture review
   ↓
Tech Lead
   ├─ technical planning
   ├─ coding standard
   └─ task decomposition
   ↓
Development Engineer ───── Database Engineer
   │                              │
   └───────────────┬──────────────┘
                   ▼
              Test Engineer
                   │
          Security Engineer
              （按风险）
                   │
                   ▼
              Code Reviewer
                   │
                   ▼
           Integration Engineer
                   │
                   ├── task-scoped handoff ──→ tp-knowledge
                   │                           └─ knowledge convergence
                   ▼
                Complete

─────────────────────────────────────────────────────────────
       L0～L3 / Role Resolver / Skill Resolver 动态裁剪
─────────────────────────────────────────────────────────────
                   │
                   ▼
        Shared TP-Spec Runtime / CLI
  Five States / phase fact / SQLite / Event / Evidence
  Record-first / Recovery / Contract / Workspace Fencing
```

---

# 60. 一句话版本定义

> **TP-Spec-Coding v5.2.4 不再以“下一步要做什么”作为软件工程能力的顶层组织方式，而是以“正式软件工程角色负责什么”重新组织整个软件开发能力体系。**

> **旧 7 步不是被删除，而是被还原为这些正式角色所承担的能力与经过实践验证的轻量生命周期经验。**

> **v5.2.4 的目标是让 TP-Spec-Coding 从一个优秀的 AI 开发流程，升级成一个能够支撑“一人项目组 / 一人软件公司的个人 AI 软件工程团队”。**

---

# 61. 实施团队最终约束

实现过程中遇到“当前源码与本计划冲突”时，按以下优先级裁决：

```text
1. 本计划 0 节的架构裁决
2. 用户四条产品底线
3. 用户资产不丢失
4. v5.2.3 已有能力 parity
5. 现有 contract / migration 安全纪律
6. 当前代码结构
```

**当前代码结构排在最后。**

原因：

> 当前代码是本次迁移的起点，不是未来架构的裁判。

但以下现有 Runtime 不变量仍属于上面的第 3～5 项，不得借“架构重构”随意破坏：

```text
5-state
Record-first
SQLite truth
trusted verification
migration chain
workspace/recovery
high-risk authorization
```

这就是 v5.2.4 的最终升级边界。
