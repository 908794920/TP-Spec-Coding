# TP-Spec-Coding Agent / Role / Skill 模型

[`governance/role-catalog.yaml`](../governance/role-catalog.yaml) 是当前 Agent / Formal Role / Skill 路径与生成型 topology 的权威。面向用户的 Domain 导航位于 [`docs/agents/`](agents/)，不在本文复制第二套完整能力清单。

## 1. 层级

```text
entry/tp-spec-coding/SKILL.md
        ↓
agents/<domain>/SKILL.md
        ↓
skills/roles/ + skills/capabilities/ + skills/autonomy/
        ↓
CLI / Runtime
```

- `entry/`：唯一默认产品入口，只做低上下文意图路由、Status / Continue / Explain。
- `agents/`：Domain Agent，负责在一个领域内选择能力。
- `skills/roles/`：软件工程 Formal Role。Role 是能力集合，不是固定阶段包。
- `skills/capabilities/`：可复用能力，按需 lazy-load。
- `skills/autonomy/`：项目自治领域的专项能力。
- CLI / Runtime：执行真实动作并自动维护 Task、Event、Evidence、Workflow 等事实。

产品入口的稳定路径是 [`entry/tp-spec-coding/SKILL.md`](../entry/tp-spec-coding/SKILL.md)。

## 2. 生命周期与 Role

`tp-software-lifecycle` 表示软件工程的**完整能力上限**。L0～L3、风险信号和工作流配置决定当前任务实际需要哪些阶段和 Role；不会因为 Role 存在就强制每个任务执行它。

软件生命周期的当前 Formal Role、Capability Skill 和执行路径统一从 [`agents/tp-software-lifecycle.md`](agents/tp-software-lifecycle.md) 的生成区块查看。

安全、数据库等能力可以跨阶段按条件参与；这类 Role 与 phase 正交，不能重新建模成固定流水线。

## 3. Domain Agent 导航

六个当前公开 Domain Agent 的用户入口统一从 [`docs/README.md`](README.md) 选择，对应导航文件都位于 `docs/agents/`。导航中的 ID、路径、Role/Skill 关系由 Role Catalog 校验或生成；“适用场景”和“边界”才由人维护。

## 4. 生成型 topology

Role Catalog 的 `topology` 是对同一份 catalog + Skill metadata 的生成投影，用于快速检索和工作台展示，不是第二事实源。

节点同时保留稳定 `id` 和用户可读 `name`。运行时消费者读取生成投影，不为了查询关系扫描整个 Skills 目录，也不增加新的数据库或后台服务。

## 5. Runtime 与 Governance

Runtime 的核心职责是自动记录真实执行事实。原则：

- AI 调用业务 CLI，CLI/Runtime 自动产生结构化 Event/Evidence；
- `summary` 只用于人类阅读，不参与状态、颜色、质量判断或工作流路由；
- 普通 Capability Skill 调用不默认成为 Runtime owner；
- 非关键 Governance enrichment 缺失不应轻易回滚真实工作；
- 本地工作台及 status/events 文件属于只读投影或展示，不反向成为事实源；历史 HTML 也不是当前事实。

正式事件的结果语义由 Base 的 event semantics 契约控制；旧事件只允许按确定性的 legacy machine contract 兼容，禁止从自由文本补 PASS/FAIL。

## 6. 配置与扩展

路由、阶段、Role/Skill 条件、确认策略和阈值尽量由 `governance/` 配置表达；Python 代码负责加载、校验和执行算法。策略配置化不意味着把事务、路径规范化或 SQLite 实现细节写进 YAML。

新增 Domain Agent 时先更新真实 Agent/Skill 和 Role Catalog，再运行生成/校验工具更新 topology 与用户导航。Base 升级应优先保持已有项目 binding/Runtime 兼容，不能要求用户重新配置整个项目。


## 7. 能力入口与引用处置

Role 只留职责、边界和准确触发指针，方法由 Capability/其按需 reference 维护。Catalog 的 `default` 是角色默认适用能力，不表示启动时预读全文；`conditional` 的实际触发条件以对应 Role 为准。同名 Skill 只计一次，多个使用关系不是多份能力。

本次引用核对范围是收到的源码快照内 `entry/`、`agents/`、`skills/`、`governance/`、`project-entry/`、`scripts/`、`cli/`、`docs/` 及生成 topology；不包含用户已安装 Base、外部项目或宿主缓存。没有以“未注册”判定无使用者，也没有删除历史案例或退役 Skill。

| 处置 | 原使用者/证据入口 | 单一方法维护位置及现在的关系 |
|---|---|---|
| 保留并补产品方法导航 | 产品经理原正文；已有 requirement-clarification / assumption-management | `requirement-clarification/references/product-definition.md` 保留输入成熟度/产品定义；原澄清与假设能力仍用，产品经理按需加载 |
| 抽取架构设计/独立复审 | 软件架构师原正文含两种方法；已有 delivery-planning 共用 | 新 `architecture-design` 与其 `references/architecture-review.md`；不为复审另造固定角色 |
| 保留共享计划/拆分 | 架构师和技术主管的 delivery-planning；技术主管 task-decomposition | 原文件补 Task/Work、实际依赖与授权集成；不从子工作名字推关系 |
| 抽取专项方法 | 安全工程师、数据库工程师原 SKILL 已有有效规则，不是“完全无能力” | 新 `security-analysis`、`database-engineering`；保留扫描合并/授权、SQL 归属/迁移/一致性细则 |
| 合并实现、测试与完整审查细则 | 开发、测试、代码审查员原正文及各自已挂能力 | `implementation-control`、`testing-strategy`、`technical-review` 单处维护；debugging、test-value、visual-qa 继续按需引用，不另造同义 Skill |
| 补关系，不退役 | `knowledge-capture` 原文件及其 agents metadata 存在，原 catalog 无该关系；`tp-knowledge` 是实际长期知识维护入口 | 集成交付工程师挂载 `knowledge-capture` 和新 `delivery-convergence`；候选经可信 Request 交 `tp-knowledge`，不复制 canonical 写入职责 |
| 适配并挂载视觉方法 | 产品经理原产品方法和开发/测试已有 UI 边界；来源/取舍见第三方声明 | 新 `ui-prototype-design` 挂产品经理与开发；测试复用 `testing-strategy/references/visual-qa.md`，不增加 UI 角色或上游引擎 |
| 单一共享 Memory | 九角色原重复段落、已有 tp-memory-capture、project-entry 模板 | 角色仅短触发指针；`tp-memory-capture` 统一规则/事实/方法归位，交付每 Task 必评估；模板不改项目自有区 |
| 原样保留领域专项 | tp-project-autonomy 的 domain_skills 及 scripts/update_role_catalog.py 生成路径 | 四个 `skills/autonomy/` 能力保留，无使用关系被批量删掉；topology/文档仍由既有工具生成 |

上述 Capability 路径以 `skills/capabilities/` 为根，具体可点击路径从生命周期导航或对应 Role 进入。Runtime 的[执行事实](EXECUTION_FACTS.md)、[Work/Fix 与集成候选](WORK_UNITS.md)、[来源审批](security-change-authority.md)和[结单/提炼](agents/tp-software-lifecycle.md)分别承载实际行为；本章与拓扑只负责导航，不能代替运行验证或真实验收。新旧事实按各自标记解释，不由角色关系推断过去已执行。
