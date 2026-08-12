# Wiki 内容标准

## 1. 定位

Wiki 是高信息密度的代码认知缓存，不是 Markdown 数量竞赛。优先回答：模块职责、关键实现、调用/数据流、接口、配置、依赖与风险定位；关键结论必须能回到真实源码。

Wiki 文档类型只有三类：

| type | 用途 |
|---|---|
| `content-doc` | 一个模块/包/服务/核心能力的七段式代码理解文档 |
| `concept-card` | 横切技术概念、算法、构建、约定、错误处理等代码相关解释；历史 `knowledge-card` 在 manifest refresh 时迁移为该类型，**不等于 canonical Knowledge** |
| `module-index` | 目录导航与子目录/文档聚合 |

## 2. content-doc 七段式

顺序固定：

1. 概述
2. 模块结构
3. 核心逻辑
4. 数据流
5. 接口
6. 配置
7. 依赖

确实无内容时可以写“无”，但必须说明为什么无；不得省略标题、只留标题、`TODO`/`待填` 或用空话填充。

每个关键 primary 实现应写出真实的：

- 职责；
- 关键类/方法/分支；
- 重要常量、参数、枚举或配置；
- 与其他类/模块的调用关系；
- 必要的数据流、异常/事务/权限边界。

## 3. 架构真实性规则

Wiki 的主要用途是让 Agent 更快、更准地定位代码，因此最危险的错误不是“少写一点”，而是把**存在的旧代码**写成**当前主路径**，或把系统最终性质归错责任层。

### 3.1 Current / Legacy 分层

涉及 workflow、API、command、template、schema、role、migration 或 runtime path 时，先判断其产品地位：

- `CURRENT`：当前日常主路径/活动契约；
- `COMPATIBILITY`：为旧调用或迁移继续保留；
- `RECOVERY`：仅恢复/修复场景使用；
- `DEPRECATED`：仍存在但不应新用；
- `HISTORICAL`：历史解释，不属于当前行为。

同一文档同时覆盖 current 与 legacy 时，必须在概述/核心逻辑/数据流中明确分开，不能画成一条连续主流程；流程图中的 legacy/compatibility/recovery 节点或边必须显式标注，不能与 CURRENT 无标签合流。判断 current 优先依据**实际入口、路由、活动配置、版本契约与运行调用链**，而不是文件仍存在。

### 3.2 Existence ≠ Authority

以下推理一律不成立：

```text
代码存在        → 当前入口
函数可调用      → 推荐 API
状态仍兼容      → 当前工作流状态
模板仍保留      → 当前标准模板
迁移函数存在    → 当前数据模型
```

如正文使用“唯一、必须、权威、当前、主路径”等词，应有比“存在该文件/函数”更强的 source evidence。

### 3.3 Responsibility Attribution

描述“谁保证什么”时，要把 enforcement layer 写对：

```text
DB constraint / trigger
Runtime transaction / state machine
Resolver / router
Validator / scanner / classifier
Quality Gate
Agent convention
Human policy
```

系统最终保持某个性质，不代表数据库、某个 helper 或某个入口单独保证它。没有直接强制证据时，写成“由……协同维持/检查”，不要过度归因。

### 3.4 Pipeline Stage Ownership

描述流水线时，每个阶段必须绑定真实 owner。尤其不要混淆：

```text
source discovery
source fingerprint
change classification
Wiki eligibility
source topology
rebuild planning
AI semantic update
manifest/provenance refresh
L1-L3 verify
coverage calculation
L4 semantic audit
snapshot baseline commit
```

如果两个模块处理相似数据，仍要根据实际调用边界说明谁**发现**、谁**分类**、谁**决策**、谁**持久化**。

### 3.5 Interface / Scope Exactness

命令名、CLI 参数、配置键、默认值、阈值、必选步骤、适用范围都属于**精确接口契约**。正文出现这类断言时，必须回到实际 parser/help、schema/config、canonical automation protocol 或 runtime entrypoint 核验。

特别禁止：

- 根据函数名、旧模板或相邻命令推断不存在的 CLI 参数；
- 把“建议/可选”写成“必须”；
- 把首次 clean build 的 readiness 阈值写成日常维护 Gate；
- 把 compatibility/recovery 命令写成 CURRENT 推荐入口；
- 只凭配置字段名字推断其作用域，而不检查实际读取位置。

无法证明精确语义时，应降级措辞或标记不确定，不得补全一个“看起来合理”的接口。

## 4. `<cite>` 溯源

```html
<cite path="relative/source/path" line="12-38"/>
```

规则：

- `path` 相对 **repo root**，使用正斜杠；禁止绝对路径与 `..`；
- 引用必须真实存在；
- 首建/更新时即定位到所述类、方法、常量或配置的真实行段；
- 除极少数单行文件外，line coverage 目标默认 ≥90%；
- 大文件不得用 `1-999`、`1-文件末尾` 等近似整文件假区间冒充精确引用；
- 不在 Wiki 粘贴大段源码，cite 是证据指针；
- cite 存在不等于正文结论正确，L4 仍须回源码审计语义；
- 关键 cite 放在实际支持该断言的正文 section 附近，使后续 manifest 能自动推导受影响章节；“溯源/参考/证据”可以保留汇总索引，但不得成为所有 cite 的唯一位置；
- 机器不会把纯“溯源/参考/证据”标题当作精确 section targeting evidence，避免把整篇文档误装成可细粒度增量定位。

## 5. Mermaid

调用链、状态机、数据流在能明显提升理解时优先使用 Mermaid。单图超过约 30 节点应拆分；代码块必须闭合。不要为了“看起来完整”强制每篇都画图。

## 6. 导航与命名

- 仓根必须有 `index.md`；
- 每个包含 Wiki 文档或子文档目录的层级必须有 `index.md`，形成从仓根到内容的导航链；
- 本地 Markdown 链接必须真实有效；
- 新文档文件名默认使用小写 kebab-case + `.md`；兼容迁移期间不要求为改名而无意义重写旧文档。

## 7. 反灌水

灌水的本质不是出现某个短语，而是**对不同代码对象复用相同空话或只有模板没有源码实质**。

强信号（命中即需要返工/复核）：

- `该文件是本仓的核心实现`
- `承载主要业务逻辑`
- `其类与方法实现细节`
- 对多个不同类逐字复用相同描述段落

弱信号如“核心逻辑围绕”“主要功能包括”本身可以合法；只有后面没有具体职责、方法、常量、关系等源码实质时才算灌水。

## 8. 结构变化

日常 semantic change 只更新真实受影响章节。新增/删除/移动核心源码或模块时，根据 Source Topology Diff 决定新增、合并、拆分或废弃 Wiki；不能为了保持旧骨架而写错，也不能因为新文件没有旧 dependency edge 就忽略。
