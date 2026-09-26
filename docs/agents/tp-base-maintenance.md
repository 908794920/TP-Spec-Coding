# tp-base-maintenance

## 适用场景

用于 Base 安装配置、路径解析、项目同步、迁移、doctor、版本和发布维护。已有安装优先检查现状并做最小修复，不重复初始化。

## 执行入口

机器契约与能力 ID 由 Role Catalog 和 Agent `SKILL.md` 定义；配置命令应先检查当前 installation/project binding，再决定是否写入。

## 能力导航

<!-- TP-SPEC:AGENT-TOPOLOGY-BEGIN -->
<!-- 由 scripts/check_document_navigation.py --write 根据 governance/role-catalog.yaml 生成。不要手工编辑本区块。 -->

- **Agent**：tp-基座维护 · `tp-base-maintenance`
- **执行契约**：[`agents/tp-base-maintenance/SKILL.md`](../../agents/tp-base-maintenance/SKILL.md)
- **能力 ID**：`base.configure`、`base.migrate`、`base.doctor`、`base.repair`

<!-- TP-SPEC:AGENT-TOPOLOGY-END -->

## 相关文档

- [Getting Started](../GETTING_STARTED.md)
- [文档地图](../README.md)
- [自动化总入口](../../automation/README.md)

## 边界

不得猜测机器路径，不得未经确认覆盖已有绑定。Base 升级不应要求用户重新装修业务项目；新增默认能力应尽量由 Base 自身解析和配置兼容处理。

## 兼容更新与显式契约迁移

软件 `VERSION`、当前解析到的 Base 路径、项目绑定、Runtime Project/Task contract 是不同事实。`base resolve` 返回 `base.source`、`executing_base` 与 **Project 级** `runtime_contract`；后者不扫描并认证全部 Task。路径优先级仍是 `TP_SPEC_BASE_ROOT` → project binding → Installation → 当前执行 Base，非法来源不静默换成宽松默认。用 `task migration-plan` 核对具体 Task，而不是凭同步成功推断旧任务已适配。

**无需契约变化的更新**只替换 Base 程序/模板，再按既有授权对选定项目执行 `base sync-project --apply`。根 AGENTS/README 托管区之外的内容保留原字节，Memory/项目 Skill/测试及基线不重建，已登记 Task 和 Evidence 不因同步改变。绑定中的现有合法覆盖、显式空列表/false 和等于默认值的语义选项保持；只有已识别的空路径/重复机器根可以清理。无变化不写文件；确需修改 YAML 时可能规范化该文件的排版/注释，不能宣称任意 YAML 都逐字节保留。

### 项目规则与 Memory 的同步边界

项目稳定 Rule/高价值经验的归位、AGENTS 薄入口与可发现性核对、去重及失败处理统一见 [`tp-memory-capture`](../../skills/capabilities/tp-memory-capture/SKILL.md)。这里只同步通用入口；不读取可选 Memory 正文来裁决规则、不迁移项目实例内容、不自动删除 PROJECT 或改候选 Skill 状态。既有 Memory 为 create-once，自有正文不会因模板更新被覆盖；新模板不等于既有项目经验已迁移。已知 Skill/片段直达，INDEX 仅在目标未知且需要经验时导航；PROJECT 可保存详细稳定规则与事实线索，方法正文归项目 Skill。

项目根文件必须为精确的 `AGENTS.md`。检测到 `Agents.md`/其他大小写变体、损坏标记或无法读取的根正文时，计划返回对应文件的 `BLOCKED`，不自动选择、改名、转码或合并；核对实际规则及所有权并获准解决冲突后再重试。只检查根目录同名变体，不扫描模块或 Memory。已有模块级 AGENTS 不批量改动。保留原件与必要来源，根规则未写成功不能声称已持久化，也不能先删除其 Memory 唯一副本。

### 只读核对

以下使用已安装且已确认路径的 `tp-spec` 启动器；尖括号需替换成实际对象，不从目录名猜 Task 身份：

```text
tp-spec base installation-doctor
tp-spec base resolve --workspace-root <workspace>
tp-spec base sync-project --workspace-root <workspace>
tp-spec task migration-plan --project <PROJECT> --db <DB> --tasks-root <tasks-root> --gate
tp-spec project upgrade-contract --id <PROJECT> --db <DB> --dry-run
```

`migration-plan` 与 `upgrade-contract --dry-run` 使用只读数据库连接，不为计划切换 journal mode、补 schema 或写迁移事实。正常 CLI 的可选机器本地分段诊断仍可写出，与项目 DB/工件分开。`--gate` 返回非零表示所列当前契约/投影未收敛，不代表业务代码失败；报告的 `release_gate` 也不是产品完整 Release Gate。

计划给出活动/源 contract、对象、可用动作、原始工件版本、可机械转换的文件和前后内容哈希，以及保留项与恢复风险。`planned_artifact_changes` 是转换器的工件差异，不是未来事件 ID/时间和派生文件的完整 Patch；执行时必须复核实际输入。

### 获准后仅迁移明确对象

迁移规则集中在 `cli/migrations/__init__.py`；运行时仍严格要求活动 contract。有限支持的源版本以该表为准，只有 schema、身份、角色/工件形态及事务验证全部成立才能执行，**不是所有同主版本或历史部署都已兼容**。未列明版本及未知 DB schema 拒绝，不靠改版本字符串放行。已是当前且一致时不制造空迁移。

先暂停相关写入，在获准维护窗口对**所选数据库及 Task 目录**建立一致备份；存在 WAL 时不能只复制主 `.db` 后就宣称备份完整。可使用现场已有 SQLite 一致备份方式，或确认所有相关连接停止后备份完整状态；备份、安装和执行授权不是 `--actor human_owner` 参数能证明的。备份依据参见 [SQLite Backup API](https://www.sqlite.org/backup.html) 与 [WAL 文件边界](https://www.sqlite.org/wal.html#the_wal_file)；本工具不新增备份平台。

```text
tp-spec project upgrade-contract --id <PROJECT> --db <DB>
tp-spec task migrate --task <TASK> --task-dir <task-dir> --db <DB>
tp-spec task migration-plan --project <PROJECT> --db <DB> --tasks-root <tasks-root> --gate
```

Project 命令只切 Project contract；每个获准在途 Task 通过正式 `task migrate` 单独选择。不自动全库迁移，不迁移终态/退休档案，不将旧 PASS 重绑为新主体。Project 切换后未迁移 Task 仍受契约门禁约束；不要因部分 Task 尚旧就重新切 Project 或反复同步。

Task 迁移复用既有 journal、必要投影提交、自检和恢复入口。锁内复核 Task/Project、事件 revision、退休状态及根工件内容；预检后编辑、结单或新事件导致拒绝，保留并发改动并重新计划。故障后通过正式 `reconcile` 诊断/恢复，不手改 SQLite/events/generated。该保障不扩展成任意断电的跨文件分布式事务；成功后若已产生新事实，不可直接覆盖旧备份回退。

### 失败与恢复结果

| 结果 | 实际含义与后续动作 |
|---|---|
| `UNSUPPORTED_MIGRATION_SOURCE` / `SCHEMA_MISMATCH` | 未转换相关契约；核对源结构和支持范围，不伪造版本、自动补表或全库迁移。 |
| `MIGRATION_INPUT_CHANGED` / `PROJECT_CONTRACT_CHANGED` | 计划后输入发生变化；重新读取当前事实和授权，不重复覆盖原计划。 |
| `registry=PENDING` / `SYNC_REQUIRED` | 必要 Project/root 事实已存在或已提交，但机器缓存未收敛，或旧 contract 仍不兼容；检查具体字段，重复**相同维护命令**收敛缓存，不重跑业务/测试。 |
| 托管文件 `BLOCKED` / `BLOCKED_AFTER_BINDING` | 检查 `changes` 和子结果；同步是逐文件原子替换，不是全项目总事务，先前安全写入可能已完成。链接/损坏标记/输入变化拒绝，保留用户文件，修复明确原因后幂等重试。 |

Runtime Registry 损坏、同身份有另一现存 workspace/DB 时保留原件并阻止自动接管；更新采用同目录临时文件替换，写失败不截断其他项目记录。缓存与 SQLite 不是一个原子事务，恢复必须重查双方。内容指纹和临写检查不等于能锁住任意外部编辑器/并发安装器，迁移期间仍须使用获准的独占维护窗口。

现场安装、既有 WorkItem 的兼容处置及 Windows 路径行为须取得对应现场证据；隔离夹具的通过不证明这些现场操作已经执行。
