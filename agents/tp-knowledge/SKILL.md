---
id: tp-knowledge
name: tp-knowledge
version: 5.3.0
status: active
type: human-owner-skill
tool_agnostic: 本技能包不要求特定 IDE、账号、插件或用户目录绝对路径；从 TP-Spec-Coding/agents/tp-knowledge/SKILL.md 加载即可。
description: >
  知识系统维护工程师（tp-knowledge）：human_owner 专项 Knowledge Content System Skill。专门维护长期可复用知识：外部文档、
  Task evidence、代码证据到 source/canonical 的沉淀、检索、验证、索引与定时增量维护。
  不负责 TP-Spec-Coding 版本/Junction/受管块健康；该职责属于 tp-base-maintenance。
---

# tp-knowledge

## 0. 定位与边界

Knowledge 是 TP-Spec-Coding 的**长期可复用知识层**：业务规则、稳定架构/接口/数据事实、历史决策、外部文档沉淀、已验证操作经验。

- Source Code：当前技术事实。
- Wiki：当前代码理解/导航缓存。
- Task Runtime：一次研发发生了什么。
- Knowledge：跨 Task 长期复用的事实、规则、经验与证据索引。

本 Skill 不维护 Base VERSION、公共 Junction、`.tp-spec` 受管块或基座同步；需要时调用 `tp-base-maintenance`。不拥有 workflow state，也不是固定生命周期 phase。只有 Runtime 已产生可信 `KNOWLEDGE_CONVERGENCE_REQUEST` 时，当前 Task 的 Completion 才等待本 Skill 写出绑定同一 Request/Change Set 的 Result。

**与软件生命周期解耦但可接收 typed effect：** `tp-integration-engineer` 只根据已验证交付事实发起 `KNOWLEDGE_CONVERGENCE_REQUEST`；`tp-software-lifecycle` 以 `dispatch_effect` 按需调度本 Agent。没有 Request 的 Task 显示 `NOT_REQUIRED`，不增加 Knowledge 步骤。存在 Request 但尚未执行时显示 `NOT_RUN`，不得伪装成“无变化”。

**Task-scoped convergence 边界：** 只消费可信 Request 和其中绑定的 Task 来源，执行 current project + registered shared scopes 的最小 targeted search，最终只写 `CREATED / UPDATED / DUPLICATE / NO_DURABLE_INSIGHT`。不重新裁决软件 Verification/Review/Delivery，不启动全库 scan、`90-sources` ingest、Golden Set、audit 或 migration/normalization。`CREATED/UPDATED` 必须绑定 exact canonical；`DUPLICATE` 必须命中已有 canonical；`NO_DURABLE_INSIGHT` 也必须有实际 query、来源和原因码。

## 1. 权威关系

```text
External docs / Task evidence / code evidence
                  ↓
              evidence/source
                  ↓
           Canonical Knowledge
                  ↓
        FTS/link/graph projection
                  ↓
               Retrieval
```

Canonical Markdown + 注册 evidence 是 Knowledge truth。Knowledge projection DB 是可删除重建的检索投影，不是事实源。

默认检索必须是：

```text
canonical-first FTS5 → source fallback
```

Embedding/vector 已做历史评测并因收益不足退役；数据库里存在相关兼容表不代表当前启用。Graph 是 optional projection。

## 2. 开始任何 Knowledge 工作前

1. 用共享 Content Systems Resolver 解析 `knowledge_physical_root`、registry、projection DB、meta root；不硬编码 Vault 绝对路径。
2. 读取 `knowledge/README.md` 与 `knowledge/rules/*` 当前 Base 规范。
3. 运行 `tp-spec knowledge doctor --workspace-root <workspace>`；需要内容变更时再运行 `knowledge maintain`。
4. 检索优先：先 `tp-spec knowledge search -q ...` 找已有 canonical，再按需读 source/evidence；禁止先全库扫 Markdown 再猜重复项。

默认检索 Scope 必须是当前项目 + registered shared scopes；只有显式跨项目任务才使用 `--scope global`。全局 SQLite 投影不等于全局默认检索。

Junction 仅是兼容/浏览入口。Knowledge System Root 与 Project Root 都是 Resolver 的结果；不得依赖 `.tp-spec/knowledge` 链接。

## 3. 日常内容维护

对已有 source/canonical 的变化：

```text
maintain
→ deterministic diff/classify
→ 必要时 AI targeted read/update
→ final truth scan（AI 写入后重新绑定）
→ projection update
→ verify (L1-L3)
→ L4 when required
→ audit-record
→ snapshot-commit
```

原则：

- 更新已有 canonical 优先于新增；
- 只处理真实变化，不每天全文重写；
- source/evidence 发生语义变化时，AI 判断是否影响长期知识；
- cosmetic/index-only 变化不要调用模型改正文；
- 删除、冲突、归属不明、merge/split 不确定时 fail-closed；
- baseline 只在当前 truth、verify、必要 L4 与 projection 都绑定同一状态后推进。
- AI/canonical/evidence/disposition 最终写入后必须重新 `knowledge scan`；不得拿 AI UPDATE 前的 change set 做 L4 或推进 baseline。

## 3A. Task-scoped convergence

软件 Delivery READY 后，只有出现已验证长期知识信号或 human_owner 明确要求时才产生 Request：

```text
Delivery READY
→ KNOWLEDGE_CONVERGENCE_REQUEST
→ tp-spec knowledge task-converge --request-event-id <ID> ...
→ targeted current-project + shared search
→ KNOWLEDGE_CONVERGENCE_RESULT
→ CREATED / UPDATED / DUPLICATE / NO_DURABLE_INSIGHT
```

执行要求：

- Request 必须绑定当前 Delivery、Verification、Review 和 `change_set_id`；绑定过期时拒绝执行；
- `--query` 必须是真实执行的 targeted query，Result 保存 search receipt；
- `--source` 必须是当前 Task 中可读取、可 hash 的来源工件；
- `DUPLICATE` 的 `--knowledge-ref` 必须出现在本次 targeted search 命中中；
- `CREATED / UPDATED` 的 `--knowledge-ref` 必须精确解析为 canonical，绑定当前 Task evidence，并通过局部 lint 与单条增量索引；
- `NO_DURABLE_INSIGHT` 表示“已检索和评估后没有长期价值”，不是“没执行”；
- `NOT_RUN` 只作为 Runtime 投影状态，不写成功 Result；
- Integration 不写 Result，普通 `FACT` 也不能替代 Result；
- 不为了 Knowledge 回退软件生命周期；若代码本身变化，由 Change Set 机制正常返回 Development。

## 4. 外部文档接入

按 `automation/knowledge/ingest-batch.md` 与 `knowledge/rules/ingestion-standard.md` 执行：

```text
REGISTER → MANIFEST/HASH → DEDUP → CONVERT/QUARANTINE
→ GROUP/TRIAGE → SEARCH EXISTING CANONICAL
→ AI READ/UPDATE/CREATE/MERGE → FINAL TRUTH SCAN → INDEX → VERIFY → AUDIT → FINALIZE
```

默认本地文档转换直接使用 Base 固定的 Microsoft MarkItDown 运行时，不重复实现 PDF/Office 解析器：

```text
tp-spec knowledge ingest register --workspace-root <workspace> --project <id> --batch <name> --source-root <path>
tp-spec knowledge ingest convert  --workspace-root <workspace> --batch <name>
```

`convert` 只对已登记、hash 未漂移的本地 `convert_candidate` 生成 machine-owned Markdown intake；成功后来源仍保持 `pending`，不会自动升级成 canonical truth。转换失败只隔离对应 source 为 `quarantined`，后续 disposition / canonicalization 仍由本 Domain 按证据处理。

目标不是“每份 Source 都生成一篇 Knowledge”，而是 **Registered Source Accountability = 100%**。允许 disposition：

`pending / canonicalized / merged / source_only / duplicate / superseded / quarantined / excluded`。

项目归属、原始文档删除、冲突 merge/split、破坏性转换必须由 human_owner 明确授权；无人值守定时会话不得擅自决定。

## 5. Evidence

兼容已有 `source_refs`；新或实质更新内容优先使用结构化 `evidence_refs` 表达 `source/task/code/external`。

强断言（当前入口、必须、唯一、数值、配置项、责任层）必须回真实 evidence。没有本地 Task evidence root 时，`TASK-*` 只能称为“已登记/可外部解析”，不得声称已本地复验。


## 5A. Legacy Knowledge 标准化

已有 Vault 迁移先执行 deterministic normalization，再让模型处理语义歧义：

```text
knowledge migrate-plan
→ knowledge migrate-normalize           # dry-run
→ knowledge migrate-normalize --apply  # 仅 safe changes
→ knowledge lint
→ targeted AI review
```

自动层只允许结构/别名/稳定 ID 可证明的兼容变换；`implemented_by/evolves_into`、缺失 evidence、缺失真实 verification date 等必须留给 targeted review。不得让模型为了 lint PASS 批量发明 evidence/date/关系。详见 `knowledge/rules/migration-standard.md`。

## 6. 对话模型定时维护

Knowledge 定时器的执行者是**对话模型**，不是单纯脚本。Scheduler 只保存短 bootstrap；每次唤起后：

1. 解析当前 Base/Knowledge；
2. 读取 `automation/knowledge/daily-maintenance.md` 当前 canonical protocol；
3. 通过 Knowledge CLI 获取 deterministic facts；
4. 只在有明确证据/范围时做 targeted AI UPDATE；
5. 不得使用 AskUserQuestion；需要人工决策则记录 `NEEDS_REVIEW`，保持旧 baseline；
6. 输出简洁日报：变化、自动动作、质量结果、未处理阻塞。

定时器本身不得复制整套维护提示词，否则 Base 升级后会产生双权威。

## 7. 检索与可观测性

优先通过 `tp-spec knowledge search` 使用标准投影。标准搜索只记录 query hash、模式、候选/结果数量、fallback、耗时等轻量 telemetry，不保存原始 query 正文。

关注：canonical hit、source fallback、no-result、latency。检索策略变化前运行 `tp-spec knowledge eval` 对当前 Golden Set 回归；不得仅因旧 DB 存在 vector 表而恢复 Embedding。它们用于判断 Knowledge 是否真正帮助 Agent，而不是把“文档数”当产品 KPI。

## 8. 禁止事项

- 不负责 Base 同步/修复；
- 不把检索 projection DB 当唯一备份；
- 不因存在 embedding 表重新启用 vector path；
- 不按目录名猜 project-id/source root；
- 不为了覆盖率制造低价值 canonical；
- 不把模型推断写成证据事实；
- 不扫描全部 Task 历史自动灌入 Knowledge；只有显式 candidate/evidence 或维护范围进入沉淀流程。
