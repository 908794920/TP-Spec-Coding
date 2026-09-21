# Wiki Daily Maintenance — Canonical AI Protocol

> 这是 Wiki 维护的标准执行协议。确定性预检应在模型派发前执行；模型只负责必要代码理解与语义审计，CLI 负责来源、快照、计划、质量门与 baseline。若宿主先唤醒模型才运行预检，必须披露仍有唤醒成本，不能声称整次调度零 LLM。

## 不变量

1. 只修改 resolved Wiki physical root 内的 Wiki/metadata；绝不修改 source repo。
2. 不手填 hash、snapshot、citation manifest 字段；机器字段由 `wiki manifest-refresh` 生成。
3. `COSMETIC` 不改正文。
4. `MASS_CHANGE_REVIEW_REQUIRED` 不得直接全量重写。
5. `UNCERTAIN` 不得推进 baseline。
6. 只有当前 change-set 的 L1-L3 `verify=PASS`，且需要 L4 时 `audit=PASS`，才执行 `snapshot-commit`。
7. baseline 替换前失败/中断：停止当前 repo 并保留旧 baseline；提交成功后的 cleanup_pending 单独报告，不谎称未推进。其他 repo 独立处理。
8. Git 所有 source/cite/coverage/audit 均使用同一 staged SHA；未知 ref、不可用对象和非祖先历史不能退回工作区。具体规则见 `wiki/rules/stable-source.md`。

## 标准步骤

若 Scheduler 的工作目录是中央 Wiki System Root，先通过当前 Base 的 Workspace Inventory + Wiki Repo Registry 解析 enabled Source Workspace，然后**逐 workspace 独立执行下面协议**。中央 Wiki Root 只是执行锚点，绝不能作为 `--workspace-root`，也不能把多个项目合并成一次无边界源码扫描。某个 workspace BLOCKED 时保留其旧 baseline，并继续其他可安全维护的 workspace。

对当前 workspace：

### 0. Base resolution

Resolve physical Base Root from user Installation (`~/.tp-spec/installation.yaml`) or `TP_SPEC_BASE_ROOT`. Project-side Base Junctions are compatibility-only and must not be required. Wiki System Root may be central, but repository scope always comes from the Wiki Registry.

## 1. Doctor

```text
<BaseRoot>/scripts/tp-spec.ps1 wiki doctor --workspace-root <workspace>
```

若某个 repo 的 config/root/source 有 ERROR，该 repo 停止并报告；不以总 FAIL 掩盖其他可处理 repo 的结果。

### 2. Deterministic preflight

```text
<BaseRoot>/scripts/tp-spec.ps1 wiki maintain --workspace-root <workspace>
```

逐 repo 读取结构化结果：

- `NO_CHANGE`：该 repo 立即结束；不执行下方 Manifest/Verify/Audit，不派发模型，不重建收据。Git 的 `fast_path=true` 还保证未进入源码扫描；非 Git 必须先完成 raw hash。
- `DETERMINISTIC_FINALIZE`：cosmetic/touch、源范围外的新 commit 或残留收据恢复等；不派发作者模型，执行步骤 4–8 的适用确定性处理。必要 L4 仍以 verify 结果为准，不因状态名代签审计。
- `WAITING_FOR_AI`：仅为该 repo 派发必要模型工作，进入步骤 3。
- `BLOCKED`：保留错误、来源与旧 baseline，不派发全库扫描来掩盖问题；其他 repo 继续。
- `MASS_CHANGE_REVIEW_REQUIRED`：先检查是否为重新下载、编码/换行、formatter、include/exclude 漂移或真正大迁移。没有充分证据前禁止 `--allow-mass-change`。若确认是真实大规模语义/结构迁移，执行 `wiki plan --allow-mass-change --mass-change-reason "<实际核验理由>"` 后再进入 AI UPDATE。

### 3. AI UPDATE

读取该 repo：

```text
meta/wiki-rebuild-plan.json
```

只处理：

- `affected_documents`；
- `topology_review` 中真实需要补充/调整的模块；
- `uncertain_files` 必须先查清，不能猜。

更新时用 `wiki source-read --workspace-root <workspace> --repo <repo-id> --path <source> [--start-line N --end-line N]` 按需回读固定来源，并遵循 `wiki/rules/content-standard.md`。Wiki 是源码地图，不是源码替代品；关键结论必须可回到真实 `<cite>`。

结构变化可新增/合并/调整 Wiki，但不要为了模板完整度制造无价值文档。

### 4. Manifest / Citation Anchor refresh

只对需要处理的 repo 执行本步；NO_CHANGE 已结束，不再进入。命令会先对 `COSMETIC` source 的精确 `<cite line>` 做 committed-anchor 确定性重定位，再刷新 manifest/hash/citations；因此注释/空行位移不需要模型，也不能留下旧行号。

AI 正文修改后或 deterministic finalize 时执行：

```text
<BaseRoot>/scripts/tp-spec.ps1 wiki manifest-refresh --workspace-root <workspace> --repo <repo-id>
```

不得手工修 hash 来过门。

若 `manifest-refresh` / `verify` 报 `MANIFEST_SCHEMA_INVALID` 且 metadata 仍是旧 namespace schema，先由基座维护执行一次受控 namespace migration；不得逐文件手改 schema：

```text
<BaseRoot>/scripts/tp-spec.ps1 base namespace-migrate --workspace-root <workspace> --apply
```

若报 `CITE_ANCHOR_RELOCATION_UNAVAILABLE` / `citation anchor ... missing`，先诊断 committed anchor 覆盖：

```text
<BaseRoot>/scripts/tp-spec.ps1 wiki anchors-doctor --workspace-root <workspace> --repo <repo-id>
<BaseRoot>/scripts/tp-spec.ps1 wiki anchors-repair --workspace-root <workspace> --repo <repo-id>
```

只有 dry-run 返回 `repairable=true`（当前 source snapshot 与 committed baseline 完全一致，Wiki/manifest 也仍绑定原 anchor subject）时才允许：

```text
<BaseRoot>/scripts/tp-spec.ps1 wiki anchors-repair --workspace-root <workspace> --repo <repo-id> --apply
```

Git anchor doctor/repair 从成功 baseline 的 commit 读取；对象存在且 subject 一致时可恢复旧签名。FILESYSTEM 若 `source_baseline_current=false`，hash 无法反推旧签名，需 targeted re-verification/full-rebuild，不得拿新字节伪装旧 anchor。

### 5. L1-L3 Verify

```text
<BaseRoot>/scripts/tp-spec.ps1 wiki verify --workspace-root <workspace> --repo <repo-id>
```

若 FAIL：根据 issues 修 Wiki/引用/结构后，重新 `manifest-refresh → verify`；不推进 baseline。

WARN 必须阅读。明显灌水、topology 漏项、引用覆盖不足不能以“脚本 PASS”冒充语义质量完成。

### 6. Coverage

在确定性 verify 后记录真实覆盖率：

```text
<BaseRoot>/scripts/tp-spec.ps1 wiki coverage --workspace-root <workspace> --repo <repo-id>
```

对外主指标使用 `effective_wiki_coverage`，同时报告 covered / eligible / uncovered、`citation_evidence_files`、`semantic_only_covered_files` 与 exclusion reasons，让百分比能解释成真实文件数量。不得把 `source_dependency_coverage` 冒充真实 Wiki 覆盖率；不得为了提高数字给无正文证据的文件批量添加 `reference` dependency。

### 7. L4 Semantic Audit

若 verify 输出 `semantic_audit_required=true`，先执行：

```text
<BaseRoot>/scripts/tp-spec.ps1 wiki audit --workspace-root <workspace> --repo <repo-id>
```

严格按 `meta/wiki-semantic-audit-plan.json` 的文档范围做 L4；不要每次自行发明抽样方法。然后：

- 对计划中的文档按风险通过 `wiki source-read` 核对同一固定 source；
- 覆盖 audit plan 中全部 mandatory 文档与 topology 新增；首次 `initial-full-repo` 必须逐篇核验，不得抽样替代；
- 检查正文结论是否被 cite 真实支持，而不仅是 cite 路径存在；
- 对涉及 workflow/API/command/schema/template/role 的文档执行 audit plan 中的对抗式 challenge：CURRENT 与竞争旧路径、Existence≠Authority、真实 enforcement layer、pipeline stage owner、CLI/config/threshold 的 Interface/Scope Exactness；current 与 legacy 若同图出现必须显式分叉/标注。

真实通过后记录：

```text
<BaseRoot>/scripts/tp-spec.ps1 wiki audit-record --workspace-root <workspace> --repo <repo-id> --result PASS --summary "<本次实际核验内容>" --document <doc> [...] [--topology-reviewed]
```

若 audit plan 的 `topology_review_required=true`，只有逐项检查 `topology_review` 后才能加 `--topology-reviewed`；未实际审计不得写 PASS。

### 8. Snapshot commit

```text
<BaseRoot>/scripts/tp-spec.ps1 wiki snapshot-commit --workspace-root <workspace> --repo <repo-id>
```

FILESYSTEM 字节在 scan 后变化，必须阻止提交并重新 maintain。Git ref 向前移动不会替换 staged SHA；本次提交其已核验来源，下次处理新 SHA。若配置/规则、Wiki subject 或证据已变则重建适用结果。`COMMITTED` 伴随 cleanup_pending 表示提交已成功但清理待重试，不得当作基线未变。

## 汇报

最后按 repo 输出真实数字：change counts、guard、AI 更新文档、L1-L3 ERROR/WARN、L4 覆盖、baseline 是否提交。未跑的检查明确写“未跑”。
