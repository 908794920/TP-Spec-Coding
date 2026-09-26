# TP-Spec-Coding Agent / Role / Skill 模型

[`governance/role-catalog.yaml`](../governance/role-catalog.yaml) 是当前内置 Agent / Formal Role / Skill 路径与生成型 topology 的权威。面向用户的 Domain 导航位于 [`docs/agents/`](agents/)，不在本文复制第二套完整能力清单。

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

- `entry/`：唯一默认产品入口，负责低上下文意图路由、必要能力发现、Status / Continue / Explain。
- `agents/`：Domain Agent，负责在一个领域内选择能力。
- `skills/roles/`：软件工程 Formal Role。Role 是能力集合，不是固定阶段包。
- `skills/capabilities/`：可复用能力，按需 lazy-load。
- `skills/autonomy/`：项目自治领域的专项能力。
- CLI / Runtime：执行真实动作并自动维护 Task、Event、Evidence、Workflow 等事实。

产品入口的稳定路径是 [`entry/tp-spec-coding/SKILL.md`](../entry/tp-spec-coding/SKILL.md)。

## 2. 生命周期与 Role

`tp-software-lifecycle` 表示软件工程的**完整能力上限**。L0～L3、风险信号和工作流配置决定当前任务实际需要哪些阶段和 Role；不会因为 Role 存在就强制每个任务执行它。

软件生命周期的当前 Formal Role、内置 Capability Skill 和执行路径统一从 [`agents/tp-software-lifecycle.md`](agents/tp-software-lifecycle.md) 的生成区块查看。

安全、数据库等能力可以跨阶段按条件参与；这类 Role 与 phase 正交，不能重新建模成固定流水线。

## 3. Domain Agent 导航

当前公开 Domain Agent 从 [`文档地图`](README.md) 的生成列表选择，对应导航文件位于 `docs/agents/`。`tp-spec-coding` 是独立的产品入口，不计入 Domain Agent；不在此重复维护数量。导航中的 ID、路径、Role/Skill 关系由 Role Catalog 校验或生成；“适用场景”和“边界”才由人维护。

## 4. 生成型 topology

Role Catalog 的 `topology` 是内置 catalog + Skill metadata 的生成投影，不是第二事实源。用户级外部方法独立存放，CLI 与工作台后端通过共享加载器把内置投影和外部描述合成只读能力目录；不回写内置 Catalog。外部 ID 带来源前缀，未关联方法不虚构角色关系。存放、选择、正文定位与来源异常见 [外部 SKILL](EXTERNAL_SKILLS.md)。

节点同时保留稳定 `id` 和用户可读 `name`。内置关系读取生成投影，外部方法只读取用户级限定目录；不为了查询关系扫描整个 Skills 目录，也不增加新的数据库或后台服务。图中的“使用”及节点的 ×N 表示目录声明的引用关系，不是实际调用次数；实际执行仍以相应任务记录为准。

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

Role 只留职责、边界和准确触发指针，方法由 Capability/其按需 reference 维护。Catalog 的 `default` 是角色默认适用能力，不表示启动时预读全文；`conditional` 的实际触发条件以对应 Role 为准。同一稳定 ID 只计一个节点；显示名相同但来源／ID 不同是不同能力，多个使用关系不是多份能力。

角色默认/条件能力由 Catalog 及对应 Role 的触发指针维护；共享方法不在导航中复制正文。历史方法抽取、原使用者与引用处置见 [CHANGELOG](../CHANGELOG.md#history-capability-extraction)，该记录不作为当前安装或宿主缓存已同步的证明。

内置 Capability 方法路径以 `skills/capabilities/` 为根，具体可点击路径从生命周期导航或对应 Role 进入。Runtime 的[执行事实](EXECUTION_FACTS.md)、[Work/Fix 与集成候选](WORK_UNITS.md)、[来源审批](security-change-authority.md)和[结单/提炼](agents/tp-software-lifecycle.md)分别承载实际行为；本章与拓扑只负责导航，不能代替运行验证或真实验收。新旧事实按各自标记解释，不由角色关系推断过去已执行。
