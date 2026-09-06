# TP-Spec-Coding Agent / Role / Skill 模型（v5.3.2）

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

Role Catalog 的 `topology` 是对同一份 catalog + Skill metadata 的生成投影，用于快速检索和卡片展示，不是第二事实源。

节点同时保留稳定 `id` 和用户可读 `name`。运行时消费者读取生成投影，不为了查询关系扫描整个 Skills 目录，也不增加新的数据库或后台服务。

## 5. Runtime 与 Governance

Runtime 的核心职责是自动记录真实执行事实。原则：

- AI 调用业务 CLI，CLI/Runtime 自动产生结构化 Event/Evidence；
- `summary` 只用于人类阅读，不参与状态、颜色、质量判断或工作流路由；
- 普通 Capability Skill 调用不默认成为 Runtime owner；
- 非关键 Governance enrichment 缺失不应轻易回滚真实工作；
- 卡片、HTML、status/events 文件属于只读投影或展示，不反向成为事实源。

正式事件的结果语义由 Base 的 event semantics 契约控制；旧事件只允许按确定性的 legacy machine contract 兼容，禁止从自由文本补 PASS/FAIL。

## 6. 配置与扩展

路由、阶段、Role/Skill 条件、确认策略和阈值尽量由 `governance/` 配置表达；Python 代码负责加载、校验和执行算法。策略配置化不意味着把事务、路径规范化或 SQLite 实现细节写进 YAML。

新增 Domain Agent 时先更新真实 Agent/Skill 和 Role Catalog，再运行生成/校验工具更新 topology 与用户导航。Base 升级应优先保持已有项目 binding/Runtime 兼容，不能要求用户重新配置整个项目。
