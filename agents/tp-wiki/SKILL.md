---
id: tp-wiki
name: tp-wiki
version: 5.2.4
status: active
type: human-owner-skill
tool_agnostic: 本技能包不要求特定 IDE、账号、插件、模型或绝对路径；从 TP-Spec-Coding 相对路径加载即可。
description: >
  代码理解 Wiki 工程师（tp-wiki）：V5.2.4 代码理解 Wiki 专项 Skill：把当前源码事实维护为高信息密度、可溯源、可增量更新的代码认知地图。
  不拥有 workflow state；可由 human_owner 显式调用，或由 human_owner 已配置的 canonical Wiki automation 调用。
---

# tp-wiki — 代码理解层

## 0. 定位

Wiki 是**当前源码的结构化理解与导航层**，不是源码本身：

```text
Source Code = 当前技术事实
Wiki        = 当前技术事实的结构化理解/导航
Task        = 一次研发行为的历史记录
Knowledge   = 跨任务长期有效的业务/经验知识
```

必须先用 Wiki 缩小源码范围，再回到真实源码核验关键事实。Wiki 不得覆盖源码事实，不得替代 Task 历史，不得写入 canonical Knowledge。

## 1. 调用边界

- 不拥有 actor/workflow state，不触发任务状态、交接或结单。
- 可由 human_owner 按需调用；也可由 human_owner 配置的 `automation/wiki/*.md` 定时维护协议调用。
- 普通研发角色不得把“顺手维护 Wiki”变成 Task Gate；Wiki stale 应通过独立维护链修复。
- 一次首次构建/全量重建只处理一个 repo；日常 canonical automation 可按 registry 顺序处理多个 repo。

## 2. 路径与配置

唯一入口是 TP-Spec-Coding Content Systems Resolver：

- `wiki.root` 表示 Wiki **System Root**；可来自用户 Installation、项目 Content Systems override 或零配置本地默认；
- 配置外部中央 root 时直接使用 resolved physical root；
- 日常 Wiki 必须继续保持 workspace/repo scope；Resolver 从 System Root + Repo Registry 计算项目 Wiki root。`.tp-spec/wiki` Junction 仅为 legacy 兼容，不是 Runtime 必需条件；
- 不按目录名猜 workspace/repo/Junction target；不硬编码任何 machine-local Wiki Root；
- Wiki 数据目录不再携带 `tools/`。

先执行：

```text
<BaseRoot>/scripts/tp-spec.ps1 wiki doctor --workspace-root <workspace>
```

## 3. 标准事实链

确定性工具负责：路径、源码枚举、raw/normalized fingerprint、encoding、变更分类、Source Topology Diff、rebuild plan、manifest machine fields、L1-L3、snapshot baseline。

本 Skill 负责：

1. 根据 rebuild plan 回读真实源码；
2. 判断 semantic/structural 变化意味着什么；
3. 更新真正受影响的 Wiki；
4. 处理新增/删除/移动模块造成的 topology 变化；
5. 做 L4 semantic audit，核对正文结论是否真的被源码支持；
6. 如实报告不确定、失败与剩余风险。

禁止手工维护 hash/snapshot/机器 citations 清单来“过门”。

### 3.1 架构语义五条铁律

为降低低成本模型在“代码存在但产品地位不同”场景中的误判，写 Wiki 前先完成下面四个判断；只在相关时写入正文，不制造额外模板段落。

1. **Currentity 分类**：涉及 workflow、API、command、template、schema、role 或 runtime path 时，先区分 `CURRENT / COMPATIBILITY / RECOVERY / DEPRECATED / HISTORICAL`。同一能力存在新旧实现时，必须明确哪个是当前主路径，并用入口、路由、活动配置、版本契约或实际调用链解释为什么其他路径不是 CURRENT。
2. **Existence ≠ Authority**：代码存在、函数可调用、状态仍兼容、模板仍保留，都不等于它是当前推荐入口/权威契约/日常主路径。不得仅因“源码里还能找到”就把 compatibility/historical 写成 current。
3. **Responsibility Attribution**：写“负责 / 保证 / 决定 / 唯一入口 / 强制”这类强断言时，必须定位真实 enforcement layer，例如 DB constraint、Runtime transaction、Resolver、Validator、Quality Gate、Agent convention 或 Human policy；没有直接 enforcement evidence 就降级措辞。
4. **Pipeline Stage Ownership**：对流水线逐阶段绑定真正 owner，不把相邻阶段混写。至少区分 discovery、fingerprint、change classification、Wiki eligibility、topology、planning、AI semantic update、manifest/provenance、verify、coverage、semantic audit、baseline commit。
5. **Interface / Scope Exactness**：命令、参数、配置键、阈值、默认值、必选步骤等属于精确契约，必须回到 parser/schema/config/canonical protocol 或实际 entrypoint 核验；不得根据函数名、旧模板或相邻流程推断不存在的 CLI 参数，也不得把仅用于首次 clean build 的规则泛化为日常维护规则。

同一文档若同时描述 CURRENT 与 COMPATIBILITY/RECOVERY，流程图和数据流必须显式分叉/标注，不得把两条路径无标签合并成一条“当前主链”。

质量取舍优先级：**误导当前主路径 / 责任归因错误 / 核心模块漏图 > 引用与覆盖完整度 > 边角实现细节**。Wiki 服务检索与研发质量，不为形式评分扩写低价值内容。

首次构建时，先把 Wiki-eligible source 按能力/子系统做**语义聚类**再设计文档拓扑；一个源码文件不等于一篇 Wiki。`quality.initial_build_effective_coverage_min` 是首次可信 baseline 的**就绪阈值**（默认 0.95），与日常 `effective_wiki_coverage_warn` 分离：低于阈值必须继续处理 uncovered，不能把“verify 没有 coverage ERROR”解释成“半成品可以结单”。对剩余 uncovered 逐项判断“补进现有/聚合 Wiki”还是“确实应排除并给出真实 reason”，不得为了 100% 调分母。

## 4. 变更处理

- `TOUCHED_ONLY`：不改正文。
- `COSMETIC`：provenance-only，不调用模型重写正文。
- `SEMANTIC`：只更新真实受影响文档/章节；必要时扩大范围，但必须有源码事实理由。
- `STRUCTURAL`：检查 Source Topology，必要时新增/合并/调整 Wiki 与 index；不能因为旧 dependency graph 没有 edge 就忽略新核心文件。
- `DELETED`：移除或重写已经失效的代码解释/引用。
- `UNCERTAIN`：先查清编码/文件事实；不得猜测，不得推进 baseline。
- `MASS_CHANGE_REVIEW_REQUIRED`：先判断重新下载、CRLF/LF、编码、formatter、include/exclude 漂移或真实大迁移；没有证据前禁止全量重写。

## 5. 内容标准

遵循 `wiki/rules/content-standard.md`：

- content-doc 保持高信息密度七段式；
- 关键结论必须用真实 `<cite path="..." line="a-b"/>` 溯源；
- 关键 cite 应放在实际承载断言的正文 section 附近；“溯源/参考/证据”可以汇总，但不得成为唯一 cite 位置，否则后续只能命中整篇文档，无法低成本定位受影响章节；
- cite 首建/更新即应有精确行号，除极少数单行文件；
- 每个关键实现写真实职责、关键方法/分支/常量/参数/调用关系；
- 禁止不同类复用逐字相同套话凑覆盖率；
- 不粘贴大段源码；不为了目录完整生成无价值 Markdown。

## 6. 质量门

遵循 `wiki/rules/quality-gates.md`：

- L1 Integrity：事实/结构硬门；
- L2 Traceability：dependency/cite/source/topology 可追溯；`wiki coverage` 的 `effective_wiki_coverage = trusted covered / wiki-eligible` 是真实文件覆盖率主指标；
- L3 Content Quality：灌水、重复、依赖注水、低信息密度；
- L4 Semantic Audit：模型回源码核验语义正确性。

`verify PASS` 只证明确定性门通过，不能替代 L4。首次建立可信 baseline 时 L4 为 `initial-full-repo`；日常增量必须覆盖全部 affected documents，风险抽样不能替代 mandatory scope。未实际执行的检查不得写成 PASS。

## 7. Baseline 铁律

唯一合法顺序：

```text
SCAN → CLASSIFY → TOPOLOGY → PLAN → AI UPDATE
→ manifest-refresh → VERIFY → L4 AUDIT(if required)
→ snapshot-commit
```

以下任一发生都禁止推进 baseline：AI 未更新、质量 FAIL、UNCERTAIN 未解决、L4 未做/失败、运行中断、scan 后源码再次变化。

Anchor baseline 异常时先 `wiki anchors-doctor`。只有 `repairable=true` 才允许 `wiki anchors-repair --apply`；若 current source 已偏离 committed snapshot，则旧行签名不可恢复，必须 fail-closed 转重新验证/full-rebuild。不得手改 `wiki-cite-anchors.json`、hash、snapshot_id 或 cite line。

## 8. Automation

外部 AI Scheduler 只保存 `automation/wiki/SCHEDULER_BOOTSTRAP.md` 中的短 bootstrap；每次运行读取当前 `automation/wiki/daily-maintenance.md`。canonical protocol 无法读取时停止，禁止凭记忆继续。

## 9. 禁止事项

- 不修改 source repo；只写 resolved Wiki physical root 内的 Wiki/metadata。
- 不混写 `.tp-spec/knowledge`；不把 Wiki 内 concept/card 当成 canonical Knowledge。
- 不硬编码模型名、绝对路径、旧 PowerShell 脚本或 Junction 目标。
- 不放宽质量门迁就产物；不虚报全仓 PASS；不把抽样写成全量实测；不靠 metadata-only `reference` dependency 刷高覆盖率。
- 不因一次重新下载/格式漂移触发无证据的全量重写。
