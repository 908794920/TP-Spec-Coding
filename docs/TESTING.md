# TP-Spec-Coding 测试体系与必要性审计

本文档是 v5.3.1 测试治理的事实清单。测试是否保留由其保护的契约决定，不由版本号、文件大小或测试数量决定。

## 1. 基线与口径

- **原始 v5.3.0 基线**：87 个测试文件 / 964 个 pytest 用例；正式全量基线为 964 passed，约 575 秒。
- **Task 1～3 后**：88 个测试文件 / 978 个 pytest 用例。Task 1 在既有文件增加 5 个回归，Task 3 新增 `test_card_workflow_semantics.py` 的 9 个回归。
- **Task 4～5 状态**：89 个有实际 collected item 的测试文件 / 985 个 pytest 用例。变化为 Task 5 新增 8 个治理测试，同时 Task 4 删除 1 个已证明 exact duplicate。
- **Task 6～7 当前状态**：仍为 89 个行为测试文件 / 991 个 pytest 用例。新增 6 个测试体系治理回归，用于保护 helper 收敛、function-scoped user root、并行候选审计和 evidence-based slow 分类；没有新增业务行为测试。
- **Task 8～9 后**：仍为 89 个行为测试文件 / 995 个 pytest 用例。新增 4 个测试治理回归，保护 xdist 决策、PR/Release CI 分层、Windows Full 去重和贡献者门禁文档；没有新增业务行为测试。
- `scripts/tests/test_catalog.py` 是测试治理数据文件，文件名匹配 pytest 发现规则但自身不定义测试 item，因此不计入上述 89 个行为测试文件。
- **Task 10 最终状态**：已执行一次完整 pytest 回归；当前 995 collected，994 passed、1 skipped、2 subtests passed，0 failed，耗时 140.56s。
- **历史回归契约收敛后**：86 个行为测试文件 / 971 个 pytest 用例。相对 Task 10 再删除 24 个已证明由 canonical replacement 严格覆盖或完整吸收的历史 case；连同 Task 4 的 1 个 exact duplicate，累计删除 25 个冗余 case。完整回归为 970 passed、1 skipped、2 subtests passed、0 failed，168.24s。没有删除独立业务/兼容/故障回归。
- **Top 慢测试调用链收敛后**：86 个行为测试文件 / 968 个 pytest 用例。新增 3 条严格 superseded coverage mapping，累计删除 28 个冗余 case；primary layer 为 unit 4、contract 485、integration 479。测试专用 CLI executor 复用 argparse parser，并让非 Card 契约默认不支付 presentation-only Card refresh；生产 CLI/Runtime 行为未修改。

### 成功标准

- **不以测试数量作为 KPI**；不设置 `964 -> 600` 一类目标。
- 删除/合并测试必须先证明 replacement 断言语义等价或更强，并记录旧 nodeid → replacement nodeid。
- 版本号只表示契约引入时间；旧版本回归只要保护的当前行为仍存在就继续保留。
- 日常反馈速度优先通过分层、定向选择和重复初始化收敛优化，而不是机械删测试。

## 2. 分类模型

Primary layer 恰好一个：`unit` / `contract` / `integration`。

Orthogonal marker 可以叠加：`smoke` / `slow` / `serial`。

Domain 至少一个：`base`、`runtime`、`workflow`、`cards`、`knowledge`、`wiki`、`autonomy`、`roles`、`migration`、`release`、`portability`。

资源扫描只作为审计证据，**不自动决定 layer**。例如出现 SQLite/Git 字样不会自动改 marker；最终分类以人工审计后的 `test_catalog.py` 为准。间接使用公共 fixture/testutil 的资源也按实际调用链计入。

### 当前文件级分布

| 维度 | 数量 |
|---|---:|
| layer `unit` | 1 文件 |
| layer `contract` | 42 文件 |
| layer `integration` | 43 文件 |
| domain `autonomy` | 10 文件 |
| domain `base` | 21 文件 |
| domain `cards` | 4 文件 |
| domain `knowledge` | 3 文件 |
| domain `migration` | 5 文件 |
| domain `portability` | 3 文件 |
| domain `release` | 11 文件 |
| domain `roles` | 8 文件 |
| domain `runtime` | 10 文件 |
| domain `wiki` | 2 文件 |
| domain `workflow` | 19 文件 |
| parallel candidate `YES` | 86 文件 |
| parallel candidate `REVIEW` | 0 文件 |
| parallel candidate `NO` | 0 文件 |

Task 6 已逐项审计原 19 个 `REVIEW` 文件：Git/SQLite 均位于 test-local workspace/临时目录；两个 shared-temp 文件都显式使用 test-local `TP_SPEC_TEMP_ROOT`；CWD 修改已有 try/finally 或 monkeypatch，并增加 function-scoped CWD teardown 保护；无真实网络或监听端口。因此全部提升为并行候选 `YES`。这只是并行**前置条件审计**，不是 xdist 已验证结论；Task 8 仍需固定 worker pilot。

## 3. 资源使用事实

| 资源 | 涉及文件数 | 说明 |
|---|---:|---|
| `subprocess` | 25 | 真实 Python/PowerShell 等子进程 |
| `sqlite` | 40 | SQLite/Runtime DB（含 testutil/VisualCase 等间接使用） |
| `git` | 23 | Git 仓库或 Git 命令 |
| `network` | 0 | 真实网络 API |
| `port` | 0 | 真实 bind/listen 端口 |
| `shared_temp` | 2 | 共享/全局 Temp 语义 |
| `env_mutation` | 21 | 进程环境变量修改 |
| `cwd_mutation` | 6 | 进程 CWD 修改 |

网络和端口按实际 API 调用判断；仅在测试文本中出现 `requests`、`socket`、URL 或“port”字样不计入。当前没有发现真正发起网络请求或监听端口的正式 pytest。

## 4. 86 个行为测试文件 Inventory

| path | collected | layer | domains | necessity | proc | sqlite | git | net | port | shared tmp | env | cwd | parallel | main contracts |
|---|---:|---|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|---|
| `scripts/tests/migration/test_v523_to_v524_role_map.py` | 2 | `contract` | `migration`, `roles` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | v523 to v524 role map regression/compatibility contract |
| `scripts/tests/test_b12_structured_refs.py` | 70 | `contract` | `base` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | b12 structured refs regression/compatibility contract |
| `scripts/tests/test_b14_lossless_summary.py` | 43 | `contract` | `base` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | b14 lossless summary regression/compatibility contract |
| `scripts/tests/test_b17_regression.py` | 42 | `contract` | `base` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | b17 regression regression/compatibility contract |
| `scripts/tests/test_b18_cutover_rehearsal.py` | 3 | `contract` | `base` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | b18 cutover rehearsal regression/compatibility contract |
| `scripts/tests/test_c1_review_preflight.py` | 15 | `integration` | `base` | `KEEP_REGRESSION` | Y | - | Y | - | - | - | - | - | `YES` | c1 review preflight regression/compatibility contract |
| `scripts/tests/test_c5_s1_validator.py` | 15 | `integration` | `base` | `KEEP_REGRESSION` | Y | - | Y | - | - | - | - | - | `YES` | c5 s1 validator regression/compatibility contract |
| `scripts/tests/test_card_workflow_semantics.py` | 9 | `integration` | `cards`, `workflow` | `KEEP_INDEPENDENT_CONTRACT` | - | Y | - | - | - | - | Y | - | `YES` | workflow step, execution-role, conditional-role, terminal and rework presentation semantics |
| `scripts/tests/test_config_loader.py` | 16 | `contract` | `base` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | governance/config parser validation, error codes, and supported success paths |
| `scripts/tests/test_test_suite_governance.py` | 19 | `contract` | `release`, `base` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | pytest catalog completeness, marker taxonomy, fail-closed classification, and coverage mapping |
| `scripts/tests/test_v510_active_contract.py` | 10 | `integration` | `base` | `KEEP_REGRESSION` | - | Y | - | - | - | - | - | - | `YES` | v510 active contract regression/compatibility contract |
| `scripts/tests/test_v510_runtime_defaults.py` | 4 | `contract` | `runtime` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | v510 runtime defaults regression/compatibility contract |
| `scripts/tests/test_v510_version_purity.py` | 6 | `contract` | `release` | `KEEP_REGRESSION` | Y | - | - | - | - | - | - | - | `YES` | v510 version purity regression/compatibility contract |
| `scripts/tests/test_v511_encoding.py` | 19 | `contract` | `base` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | v511 encoding regression/compatibility contract |
| `scripts/tests/test_v511_external_repair.py` | 17 | `integration` | `base` | `KEEP_REGRESSION` | - | Y | - | - | - | - | - | - | `YES` | v511 external repair regression/compatibility contract |
| `scripts/tests/test_v511_frontmatter.py` | 21 | `contract` | `base` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | v511 frontmatter regression/compatibility contract |
| `scripts/tests/test_v511_template_completeness.py` | 7 | `contract` | `base` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | v511 template completeness regression/compatibility contract |
| `scripts/tests/test_v512_integrated_upgrade.py` | 14 | `integration` | `migration` | `KEEP_REGRESSION` | Y | Y | Y | - | - | - | - | - | `YES` | v512 integrated upgrade regression/compatibility contract |
| `scripts/tests/test_v512_maintenance.py` | 11 | `integration` | `base` | `KEEP_REGRESSION` | - | Y | - | - | - | - | - | - | `YES` | v512 maintenance regression/compatibility contract |
| `scripts/tests/test_v513_base_convergence.py` | 9 | `contract` | `base` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | v513 base convergence regression/compatibility contract |
| `scripts/tests/test_v513_knowledge_standardization.py` | 18 | `integration` | `knowledge` | `KEEP_REGRESSION` | - | Y | - | - | - | - | - | - | `YES` | v513 knowledge standardization regression/compatibility contract |
| `scripts/tests/test_v513_portability.py` | 9 | `integration` | `portability` | `KEEP_REGRESSION` | - | Y | - | - | - | - | - | - | `YES` | v513 portability regression/compatibility contract |
| `scripts/tests/test_v513_record_first.py` | 10 | `integration` | `runtime` | `KEEP_REGRESSION` | Y | Y | Y | - | - | - | - | - | `YES` | v513 record first regression/compatibility contract |
| `scripts/tests/test_v513_runtime_portability.py` | 13 | `integration` | `runtime`, `portability` | `KEEP_REGRESSION` | - | Y | - | - | - | - | Y | - | `YES` | v513 runtime portability regression/compatibility contract |
| `scripts/tests/test_v513_skill_semantics.py` | 13 | `contract` | `base` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | v513 skill semantics regression/compatibility contract |
| `scripts/tests/test_v513_wiki_standardization.py` | 72 | `contract` | `wiki` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | v513 wiki standardization regression/compatibility contract |
| `scripts/tests/test_v514_orchestration_adversarial.py` | 8 | `integration` | `workflow` | `KEEP_REGRESSION` | - | Y | - | - | - | - | - | - | `YES` | v514 orchestration adversarial regression/compatibility contract |
| `scripts/tests/test_v514_orchestration_contract.py` | 5 | `contract` | `workflow` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | v514 orchestration contract regression/compatibility contract |
| `scripts/tests/test_v514_orchestration_integration.py` | 3 | `integration` | `workflow` | `KEEP_REGRESSION` | - | Y | - | - | - | - | - | - | `YES` | v514 orchestration integration regression/compatibility contract |
| `scripts/tests/test_v514_orchestration_router.py` | 5 | `integration` | `workflow` | `KEEP_REGRESSION` | - | Y | - | - | - | - | - | - | `YES` | orchestration level routing, stage routing, and review/rework role decisions |
| `scripts/tests/test_v514_release_convergence.py` | 4 | `contract` | `release` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | v514 release convergence regression/compatibility contract |
| `scripts/tests/test_v514_risk_escalation.py` | 7 | `integration` | `workflow` | `KEEP_REGRESSION` | - | Y | - | - | - | - | - | - | `YES` | v514 risk escalation regression/compatibility contract |
| `scripts/tests/test_v514_upgrade.py` | 3 | `contract` | `migration` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | v514 upgrade regression/compatibility contract |
| `scripts/tests/test_v520_final_convergence.py` | 6 | `integration` | `release` | `KEEP_REGRESSION` | - | Y | - | - | - | - | - | - | `YES` | v520 final convergence regression/compatibility contract |
| `scripts/tests/test_v520_namespace_migration.py` | 4 | `contract` | `migration` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | v520 namespace migration regression/compatibility contract |
| `scripts/tests/test_v520_namespace_purity.py` | 3 | `contract` | `release` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | active namespace purity and release exclusion of process-history docs |
| `scripts/tests/test_v520_open_source_release.py` | 16 | `integration` | `release` | `KEEP_REGRESSION` | Y | Y | Y | - | - | - | Y | - | `YES` | v520 open source release regression/compatibility contract |
| `scripts/tests/test_v520_windows_portability.py` | 7 | `integration` | `portability` | `KEEP_REGRESSION` | Y | Y | - | - | - | - | Y | - | `YES` | v520 windows portability regression/compatibility contract |
| `scripts/tests/test_v521_project_memory.py` | 5 | `contract` | `runtime` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | v521 project memory regression/compatibility contract |
| `scripts/tests/test_v522_context_effectiveness.py` | 8 | `integration` | `base` | `KEEP_REGRESSION` | - | Y | - | - | - | - | - | - | `YES` | v522 context effectiveness regression/compatibility contract |
| `scripts/tests/test_v522_context_usage.py` | 19 | `integration` | `base` | `KEEP_REGRESSION` | Y | Y | Y | - | - | - | Y | - | `YES` | v522 context usage regression/compatibility contract |
| `scripts/tests/test_v522_contracts.py` | 29 | `contract` | `base` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | v522 contracts regression/compatibility contract |
| `scripts/tests/test_v522_wiki_namespace_anchor_recovery.py` | 5 | `contract` | `wiki` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | v522 wiki namespace anchor recovery regression/compatibility contract |
| `scripts/tests/test_v522_workflow_delivery_hardening.py` | 14 | `integration` | `workflow` | `KEEP_REGRESSION` | Y | Y | Y | - | - | - | Y | - | `YES` | v522 workflow delivery hardening regression/compatibility contract |
| `scripts/tests/test_v523_autonomy_batch.py` | 4 | `integration` | `autonomy` | `KEEP_REGRESSION` | Y | Y | Y | - | - | - | Y | Y | `YES` | v523 autonomy batch regression/compatibility contract |
| `scripts/tests/test_v523_autonomy_cycle_fencing.py` | 6 | `integration` | `autonomy` | `KEEP_REGRESSION` | Y | Y | Y | - | - | - | Y | - | `YES` | v523 autonomy cycle fencing regression/compatibility contract |
| `scripts/tests/test_v523_autonomy_discovery.py` | 5 | `integration` | `autonomy` | `KEEP_REGRESSION` | Y | Y | Y | - | - | - | Y | - | `YES` | v523 autonomy discovery regression/compatibility contract |
| `scripts/tests/test_v523_autonomy_envelope.py` | 6 | `integration` | `autonomy` | `KEEP_REGRESSION` | Y | Y | Y | - | - | - | Y | Y | `YES` | v523 autonomy envelope regression/compatibility contract |
| `scripts/tests/test_v523_autonomy_integration.py` | 6 | `integration` | `autonomy` | `KEEP_REGRESSION` | Y | Y | Y | - | - | - | Y | Y | `YES` | v523 autonomy integration regression/compatibility contract |
| `scripts/tests/test_v523_autonomy_phase0_contract.py` | 4 | `integration` | `autonomy` | `KEEP_REGRESSION` | - | Y | - | - | - | - | - | - | `YES` | v523 autonomy phase0 contract regression/compatibility contract |
| `scripts/tests/test_v523_autonomy_profile.py` | 4 | `integration` | `autonomy` | `KEEP_REGRESSION` | Y | Y | Y | - | - | - | Y | - | `YES` | v523 autonomy profile regression/compatibility contract |
| `scripts/tests/test_v523_autonomy_release.py` | 2 | `contract` | `autonomy` | `KEEP_REGRESSION` | - | - | - | - | - | - | - | - | `YES` | v523 autonomy release regression/compatibility contract |
| `scripts/tests/test_v523_autonomy_review.py` | 3 | `integration` | `autonomy` | `KEEP_REGRESSION` | Y | Y | Y | - | - | - | Y | Y | `YES` | v523 autonomy review regression/compatibility contract |
| `scripts/tests/test_v523_autonomy_workspace.py` | 6 | `integration` | `autonomy` | `KEEP_REGRESSION` | Y | Y | Y | - | - | - | Y | - | `YES` | v523 autonomy workspace regression/compatibility contract |
| `scripts/tests/test_v523_runtime_hardening.py` | 8 | `integration` | `runtime` | `KEEP_REGRESSION` | - | Y | - | - | - | - | Y | Y | `YES` | v523 runtime hardening regression/compatibility contract |
| `scripts/tests/test_v524_contract_cutover.py` | 4 | `contract` | `base` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | v524 contract cutover regression/compatibility contract |
| `scripts/tests/test_v524_delivery_knowledge_handoff.py` | 5 | `integration` | `knowledge`, `workflow` | `KEEP_INDEPENDENT_CONTRACT` | - | Y | - | - | - | - | - | - | `YES` | v524 delivery knowledge handoff regression/compatibility contract |
| `scripts/tests/test_v524_directory_convergence.py` | 6 | `contract` | `release` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | v524 directory convergence regression/compatibility contract |
| `scripts/tests/test_v524_legacy_runtime_retirement.py` | 7 | `contract` | `runtime` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | v524 legacy runtime retirement regression/compatibility contract |
| `scripts/tests/test_v524_no_tail.py` | 2 | `contract` | `release` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | v524 no tail regression/compatibility contract |
| `scripts/tests/test_v524_powershell_cli_first.py` | 3 | `contract` | `release` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | v524 powershell cli first regression/compatibility contract |
| `scripts/tests/test_v524_product_router.py` | 4 | `contract` | `workflow` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | v524 product router regression/compatibility contract |
| `scripts/tests/test_v524_requirement_ready.py` | 3 | `contract` | `workflow` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | v524 requirement ready regression/compatibility contract |
| `scripts/tests/test_v524_review_isolation.py` | 3 | `contract` | `workflow` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | v524 review isolation regression/compatibility contract |
| `scripts/tests/test_v524_review_locator.py` | 4 | `unit` | `workflow` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | v524 review locator regression/compatibility contract |
| `scripts/tests/test_v524_role_catalog.py` | 3 | `contract` | `roles` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | formal role catalog structure and skill-path validity |
| `scripts/tests/test_v524_role_first_contract.py` | 5 | `contract` | `roles` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | v524 role first contract regression/compatibility contract |
| `scripts/tests/test_v524_role_reference_inventory.py` | 2 | `contract` | `roles` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | role-reference inventory classification and deterministic report payload |
| `scripts/tests/test_v524_role_resolver.py` | 4 | `integration` | `roles` | `KEEP_INDEPENDENT_CONTRACT` | - | Y | - | - | - | - | - | - | `YES` | v524 role resolver regression/compatibility contract |
| `scripts/tests/test_v524_task_role_ownership.py` | 4 | `contract` | `roles` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | v524 task role ownership regression/compatibility contract |
| `scripts/tests/test_v524_trusted_role_results.py` | 4 | `contract` | `roles` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | v524 trusted role results regression/compatibility contract |
| `scripts/tests/test_v525_markitdown_integration.py` | 9 | `contract` | `base` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | v525 markitdown integration regression/compatibility contract |
| `scripts/tests/test_v526_event_presentation.py` | 6 | `contract` | `runtime`, `cards` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | v526 event presentation regression/compatibility contract |
| `scripts/tests/test_v526_html_cards.py` | 80 | `integration` | `cards`, `workflow` | `KEEP_INDEPENDENT_CONTRACT` | - | Y | - | - | - | - | Y | Y | `YES` | card snapshot/render/display artifact and refresh contracts |
| `scripts/tests/test_v526_temp_artifacts.py` | 33 | `integration` | `runtime` | `KEEP_INDEPENDENT_CONTRACT` | Y | Y | Y | - | - | Y | Y | - | `YES` | owned execution-temp lifecycle, cleanup evidence, and delivery blocking |
| `scripts/tests/test_v527_document_navigation.py` | 5 | `contract` | `release` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | v527 document navigation regression/compatibility contract |
| `scripts/tests/test_v527_skill_topology.py` | 5 | `contract` | `roles` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | v527 skill topology regression/compatibility contract |
| `scripts/tests/test_v529_acceptance_database.py` | 7 | `integration` | `workflow` | `KEEP_INDEPENDENT_CONTRACT` | Y | Y | Y | - | - | - | - | - | `YES` | v529 acceptance database regression/compatibility contract |
| `scripts/tests/test_v529_baseline_consistency.py` | 7 | `integration` | `workflow` | `KEEP_INDEPENDENT_CONTRACT` | - | Y | - | - | - | - | - | - | `YES` | v529 baseline consistency regression/compatibility contract |
| `scripts/tests/test_v529_change_set_binding.py` | 11 | `integration` | `runtime` | `KEEP_INDEPENDENT_CONTRACT` | Y | - | Y | - | - | - | - | - | `YES` | Change Set digest/binding and stale verification-review-delivery contracts |
| `scripts/tests/test_v529_delivery_rework.py` | 8 | `integration` | `workflow` | `KEEP_INDEPENDENT_CONTRACT` | Y | Y | Y | - | - | - | Y | - | `YES` | v529 delivery rework regression/compatibility contract |
| `scripts/tests/test_v529_development_habits.py` | 5 | `contract` | `workflow` | `KEEP_INDEPENDENT_CONTRACT` | - | - | - | - | - | - | - | - | `YES` | v529 development habits regression/compatibility contract |
| `scripts/tests/test_v529_knowledge_convergence.py` | 14 | `integration` | `knowledge`, `workflow` | `KEEP_INDEPENDENT_CONTRACT` | Y | Y | Y | - | - | - | Y | - | `YES` | typed Knowledge request/result provenance, source binding, and invalidation |
| `scripts/tests/test_v529_migration_release.py` | 5 | `integration` | `migration`, `release` | `KEEP_INDEPENDENT_CONTRACT` | Y | Y | Y | - | - | - | - | - | `YES` | v529 migration release regression/compatibility contract |
| `scripts/tests/test_v529_terminal_projection.py` | 9 | `integration` | `runtime` | `KEEP_INDEPENDENT_CONTRACT` | Y | Y | Y | - | - | - | Y | - | `YES` | v529 terminal projection regression/compatibility contract |
| `scripts/tests/test_v529_visual_verification.py` | 10 | `integration` | `workflow`, `cards` | `KEEP_INDEPENDENT_CONTRACT` | Y | Y | Y | - | - | Y | Y | - | `YES` | visual evidence manifest and temporary-auth cleanup delivery gates |

## 5. 必要性审计与覆盖映射

必要性类别：

- `KEEP_INDEPENDENT_CONTRACT`：当前独立契约，不能由其他测试替代。
- `KEEP_REGRESSION`：历史缺陷/迁移/兼容契约仍作用于当前版本。
- `MERGE_CANDIDATE`：存在结构或断言重叠，但尚未证明可删。
- `SUPERSEDED_CANDIDATE`：存在更强 replacement 候选；只有 node-level 覆盖映射成立后才能删除。

当前文件级必要性分布：

- `KEEP_INDEPENDENT_CONTRACT`：33 文件。
- `KEEP_REGRESSION`：53 文件。

### 已删除的覆盖冗余

删除规则：replacement 必须真实存在；原 test 的每一条断言语义必须由 replacement 直接包含、由同一 canonical validator 更严格覆盖，或被完整搬入 replacement。只存在“相似”或“部分重叠”的测试不删除。

| old nodeid | replacement nodeid | protected contract | evidence | decision |
|---|---|---|---|---|
| `scripts/tests/test_v524_role_reference_inventory.py::test_removed_role_inventory_is_not_shipped` | `scripts/tests/test_v520_namespace_purity.py::test_process_history_docs_are_not_shipped` | docs/history process-history artifacts are not shipped | AST-normalized bodies are identical | `DELETE_EXACT_DUPLICATE` |
| `scripts/tests/test_v510_agent_contracts.py::TestAgentContracts::test_all_skills_version_511` | `scripts/tests/test_v524_role_catalog.py::test_catalog_has_only_new_active_role_model` | all catalog-declared role skills use the active version | canonical role-catalog validator checks every role Skill frontmatter version | `DELETE_CONSOLIDATED_CONTRACT` |
| `scripts/tests/test_v510_agent_contracts.py::TestAgentContracts::test_no_legacy_template_path_in_skills` | `scripts/tests/test_v524_role_catalog.py::test_catalog_has_only_new_active_role_model` | catalog-declared role skills do not contain the retired template/version token | canonical role-catalog test now scans every declared role Skill for the retired token | `DELETE_CONSOLIDATED_CONTRACT` |
| `scripts/tests/test_v510_agent_contracts.py::TestAgentContracts::test_role_catalog_hashes_match` | `scripts/tests/test_v524_role_catalog.py::test_catalog_has_only_new_active_role_model` | role-catalog content_sha256 matches normalized Skill content | canonical role-catalog test invokes update_role_catalog.validate, which checks every content_sha256 | `DELETE_STRICT_SUPERSET` |
| `scripts/tests/test_v510_agent_contracts.py::TestAgentContracts::test_role_catalog_version_511` | `scripts/tests/test_v524_role_catalog.py::test_catalog_has_only_new_active_role_model` | role-catalog catalog_version/base_version match VERSION | canonical role-catalog validator checks both version fields | `DELETE_STRICT_SUPERSET` |
| `scripts/tests/test_v510_version_purity.py::TestVersionPurity::test_no_legacy_dirs` | `scripts/tests/test_v520_open_source_release.py::test_only_active_task_template_contract_is_shipped` | only the active template directory is shipped and cutover-snapshots is absent | release-surface test retains the exact directory assertion and now also checks cutover-snapshots absence | `DELETE_CONSOLIDATED_CONTRACT` |
| `scripts/tests/test_v511_agent_contracts.py::TestRoleCatalog::test_catalog_has_expected_roles_and_hashes` | `scripts/tests/test_v524_role_catalog.py::test_catalog_has_only_new_active_role_model` | active role set, catalog version, skill existence and hashes are valid | canonical role-catalog test asserts the exact role set and invokes the stronger validator | `DELETE_STRICT_SUPERSET` |
| `scripts/tests/test_v511_agent_contracts.py::TestAgentSkills::test_agent_versions` | `scripts/tests/test_v524_role_catalog.py::test_catalog_has_only_new_active_role_model` | every catalog-declared role Skill uses active VERSION | canonical role-catalog validator checks every declared role Skill version | `DELETE_STRICT_SUPERSET` |
| `scripts/tests/test_v511_agent_contracts.py::TestAgentSkills::test_requirement_analysis_is_pretask_and_low_bookkeeping` | `scripts/tests/test_v513_skill_semantics.py::TestWorkflowRoleSemantics::test_requirement_keeps_fact_assumption_decision_boundary` | requirement role keeps pre-task and low-bookkeeping boundaries | all original semantic anchors and the max_search_rounds rejection were folded into the canonical requirement-role test | `DELETE_CONSOLIDATED_CONTRACT` |
| `scripts/tests/test_v511_agent_contracts.py::TestAgentSkills::test_architecture_review_is_risk_triggered_not_default_gate` | `scripts/tests/test_v513_skill_semantics.py::TestWorkflowRoleSemantics::test_architecture_review_is_compact_but_professional` | architecture review is risk-triggered and not a mandatory L2/L3 gate | all original positive/negative anchors were folded into the canonical architecture-review semantic test | `DELETE_CONSOLIDATED_CONTRACT` |
| `scripts/tests/test_v511_agent_contracts.py::TestAgentSkills::test_roles_do_business_not_projection_bookkeeping` | `scripts/tests/test_v513_skill_semantics.py::TestWorkflowRoleSemantics::test_compact_roles_still_reject_old_daily_bookkeeping` | roles avoid stage-handoff bookkeeping while preserving test/delivery ownership boundaries | stage-handoff checks plus test-complete and Delivery Result anchors are retained in canonical skill-semantic tests | `DELETE_CONSOLIDATED_CONTRACT` |
| `scripts/tests/test_v511_agent_contracts.py::TestCostTiering::test_l0_l3_are_risk_labels_not_fixed_expensive_flows` | `scripts/tests/test_v513_record_first.py::RecordFirstCase::test_public_workflow_is_small_and_phases_are_facts` | L0-L3 use NEW-ACTIVE-COMPLETED and architecture review is optional by default | replacement contains the same assertions on all four levels and architecture_review.default | `DELETE_STRICT_SUPERSET` |
| `scripts/tests/test_v513_record_first.py::TestRecordFirstStaticContracts::test_optional_templates_have_no_stage_handoff` | `scripts/tests/test_v511_template_completeness.py::TestTemplateCompleteness::test_upgraded_templates_reference_v511_artifacts` | optional business templates do not contain stage_handoff | replacement iterates the same template set and adds task/readme contract assertions | `DELETE_STRICT_SUPERSET` |
| `scripts/tests/test_v513_skill_semantics.py::TestRoleCatalogMetadata::test_catalog_metadata_matches_skill_frontmatter` | `scripts/tests/test_v524_role_catalog.py::test_catalog_has_only_new_active_role_model` | role-catalog id/type/version metadata matches Skill frontmatter | canonical role-catalog validator checks id, type and version for every declared Skill | `DELETE_STRICT_SUPERSET` |
| `scripts/tests/test_v520_open_source_release.py::test_version_purity_scanner_rejects_previous_minor_after_v520_cutover` | `scripts/tests/test_v510_version_purity.py::TestVersionPurity::test_scanner_rejects_previous_patch` | version-purity scanner rejects older same-major dotted versions | canonical scanner regression now covers old patch, old minor and immediate prior-minor samples | `DELETE_CONSOLIDATED_CONTRACT` |
| `scripts/tests/test_v524_delivery_knowledge_handoff.py::test_legacy_task_scoped_knowledge_handoff_is_rejected` | `scripts/tests/test_v522_contracts.py::test_legacy_task_scoped_knowledge_fast_paths_are_retired` | legacy task-scoped Knowledge handoff is rejected | replacement exercises the same empty payload plus an additional reusable-finding legacy payload | `DELETE_STRICT_SUPERSET` |
| `scripts/tests/test_v524_release_docs.py::test_readme_exposes_current_entry_and_document_map` | `scripts/tests/test_v520_open_source_release.py::test_readme_explains_value_quickstart_agents_and_portability` | README exposes current entry/model and hides retired workflow-orchestrator | all original README assertions were folded into the broader canonical README release-surface test | `DELETE_CONSOLIDATED_CONTRACT` |
| `scripts/tests/test_v524_release_docs.py::test_getting_started_links_back_to_ai_install_entry_and_current_model` | `scripts/tests/test_v520_open_source_release.py::test_getting_started_supports_ai_assisted_clean_machine_setup` | GETTING_STARTED links to install entry/current model and avoids retired workflow/re-init guidance | all original GETTING_STARTED anchors were folded into the canonical onboarding test | `DELETE_CONSOLIDATED_CONTRACT` |
| `scripts/tests/test_v524_release_docs.py::test_agents_and_skills_is_current_model_not_migration_history` | `scripts/tests/test_v520_open_source_release.py::test_development_flow_has_one_external_lead_and_three_independent_agents` | AGENTS_AND_SKILLS documents the current role model and no retired Action Role history | original documentation assertions were folded into the canonical public role-surface test | `DELETE_CONSOLIDATED_CONTRACT` |
| `scripts/tests/test_v524_release_docs.py::test_changelog_keeps_release_history_not_process_plan` | `scripts/tests/test_v520_open_source_release.py::test_public_brand_and_release_version` | CHANGELOG retains current release/navigation history | original CHANGELOG anchors were folded into the canonical public release identity test | `DELETE_CONSOLIDATED_CONTRACT` |
| `scripts/tests/test_v524_role_catalog.py::test_subskill_paths_are_real` | `scripts/tests/test_v524_role_catalog.py::test_catalog_has_only_new_active_role_model` | declared subskill ids/paths resolve to valid capability Skills | update_role_catalog.validate checks subskill metadata, path prefix, existence, frontmatter identity/version and mode | `DELETE_STRICT_SUPERSET` |
| `scripts/tests/test_v527_document_navigation.py::test_document_navigation_checker_exists` | `scripts/tests/test_v527_document_navigation.py::test_public_document_navigation_has_no_broken_links_or_process_paths` | document-navigation checker exists and is loadable | replacement loads the checker module before validating the live documentation surface | `DELETE_STRICT_SUPERSET` |
| `scripts/tests/test_v527_document_navigation.py::test_current_document_entrypoints_exist` | `scripts/tests/test_v527_document_navigation.py::test_public_document_navigation_has_no_broken_links_or_process_paths` | core public document entrypoints exist | validate_document_navigation checks every CORE_DOCUMENTS entrypoint before link validation | `DELETE_STRICT_SUPERSET` |
| `scripts/tests/test_v527_document_navigation.py::test_generated_agent_topology_blocks_match_catalog` | `scripts/tests/test_v527_document_navigation.py::test_public_document_navigation_has_no_broken_links_or_process_paths` | generated Agent topology blocks match role catalog | validate_document_navigation includes validate_agent_guides and generated docs Agent-map verification | `DELETE_STRICT_SUPERSET` |
| `scripts/tests/test_v527_document_navigation.py::test_process_document_release_surface_is_removed` | `scripts/tests/test_v527_document_navigation.py::test_public_document_navigation_has_no_broken_links_or_process_paths` | retired process-document files are absent | validate_document_navigation calls retired_process_files and reports every retired process file | `DELETE_STRICT_SUPERSET` |

本轮新增删除 24 个 case，加上 Task 4 已删除的 1 个 exact duplicate，累计 25 个。删除后 AST-normalized exact duplicate group 为 0；高阈值跨文件静态字符串重叠复扫也未再发现可直接判定为严格超集的候选。

### 审计后继续保留的重叠组

以下测试仍可能读取相邻文件或共享部分字符串，但 node-level 审计没有证明严格替代关系，因此继续保留：

- **agent/skill contracts**：`scripts/tests/test_v513_skill_semantics.py`、`scripts/tests/test_v522_contracts.py`、`scripts/tests/test_v527_skill_topology.py`；decision=`KEEP_DISTINCT_AFTER_NODE_LEVEL_AUDIT`。
- **release/purity/navigation**：`scripts/tests/test_v510_version_purity.py`、`scripts/tests/test_v520_namespace_purity.py`、`scripts/tests/test_v520_open_source_release.py`、`scripts/tests/test_v527_document_navigation.py`；decision=`KEEP_DISTINCT_AFTER_NODE_LEVEL_AUDIT`。
- **role static contracts**：`scripts/tests/test_v524_role_catalog.py`、`scripts/tests/test_v524_role_first_contract.py`、`scripts/tests/test_v524_role_reference_inventory.py`、`scripts/tests/test_v527_skill_topology.py`、`scripts/tests/test_v529_baseline_consistency.py`；decision=`KEEP_PENDING_NODE_LEVEL_MAPPING`。

结论：本轮停止继续删除。没有证据证明为严格超集的历史 regression 保持原样。

## 6. Smoke 集合

Smoke 保持极小，只证明关键入口仍能工作，不替代 domain regression：

- `scripts/tests/test_config_loader.py::TestSuccessPaths::test_all_governance_validate`
- `scripts/tests/test_v510_active_contract.py::TestActiveContract::test_gate_accepts_active_version`
- `scripts/tests/test_v513_record_first.py::RecordFirstCase::test_simple_verified_flow_has_small_event_budget`
- `scripts/tests/test_v514_orchestration_router.py::test_l1_standard_route`
- `scripts/tests/test_v524_role_catalog.py::test_catalog_has_only_new_active_role_model`
- `scripts/tests/test_v526_html_cards.py::test_renderer_contains_core_fields_interactions_and_snapshot_notice`

## 7. 门禁命令矩阵（Task 5）

```bash
# 日常快速门禁
python -m pytest -q -m "smoke or ((unit or contract) and not slow)"

# 领域定向
python -m pytest -q -m "cards and not slow"
python -m pytest -q -m "workflow and not slow"
python -m pytest -q -m "knowledge"

# integration 并行边界；Task 8 前不自动启用 xdist
python -m pytest -q -m "integration and not slow and not serial"
python -m pytest -q -m "integration and not slow and serial"

# Release：不通过 marker 排除正式测试
python -m pytest -q --durations=50
```

当前 `slow` 由 Task 7 的真实 wall-time 证据决定，共 4 个 integration 文件：`test_v523_autonomy_integration.py`、`test_v529_delivery_rework.py`、`test_v529_knowledge_convergence.py`、`test_v529_visual_verification.py`。文件大、使用 subprocess/Git/SQLite 本身都不是 slow 证据。

当前仍不设置 `serial` 文件：Task 6 没有发现真实端口、全局 writable workspace 或跨 worker 必须共享的 SQLite/Git 路径。是否真的启用并行仍由 Task 8 的固定 worker pilot 决定。

### Task 5 当前环境验证数据

| 命令 | selected | 结果 |
|---|---:|---|
| `-m "smoke or ((unit or contract) and not slow)"` | 504 / 985 | 504 passed，481 deselected，12.89s |
| `-m "cards and not slow"` | 105 / 985 | 105 passed，880 deselected，27.17s |
| `-m "workflow and not slow"` | 191 / 985 | collection 正确；pytest 9.0.2 在既有 `test_v522_workflow_delivery_hardening.py` 组合执行上挂起，未得到正式 PASS/FAIL 总结 |

`workflow` 的挂起不通过把该文件误标为 `slow` 或 `serial` 来规避。使用 Task 3 commit `bb62f31` 的未修改代码在同一 pytest 9.0.2 环境运行该问题文件也会组合挂起，因此该现象不是 Task 4/5 marker 改造引入。当时仓库正式开发依赖为 `pytest>=8,<9`；这是历史环境记录，当前候选口径见第 14.12 节。

## 8. Fail-closed 规则

- `pytest.ini` 通过 `addopts = --strict-markers` 启用严格 marker；测试源码使用未注册 marker 时 collection 失败。
- `scripts/tests/conftest.py` 对每个 collected item 应用 catalog 默认分类。
- 每个 collected item 必须恰好一个 primary layer，且至少一个 domain。
- 新增 `test_*.py` 但未登记 catalog 时立即 `UsageError`，不能静默落入默认 bucket。
- test/class 显式 layer/domain marker 优先于 file default；catalog 不根据资源字符串动态改变 layer。

## 9. 已知限制与后续 Task

- 历史环境记录：当时容器安装 pytest 9.0.2，而仓库 `requirements-dev.txt` 约束 `pytest>=8,<9`；该阶段 collection/定向 marker 验证可执行，但正式全量性能结论不得以 pytest 9 代替当时项目支持环境。当前候选口径见第 14.12 节。
- Task 6：已完成 helper 收敛、function-scoped env/CWD 边界与并行候选审计。
- Task 7：已完成真实 duration profiling；Knowledge immutable-template 因收益不足不实施，并补齐 evidence-based `slow`。
- Task 8：只有固定 worker pilot 证明收益才考虑 xdist；不默认引入依赖。
- Task 9：PR/Windows Full Gate 分层已完成。
- Task 10：最终全量回归、manifest 收敛和测试报告已完成；Windows Full Gate 因当前环境无 `pwsh` 仍未执行。


## 10. Task 6：helper 收敛与隔离审计

### 10.1 重复 helper 收敛

- 7 份语义完全相同的 Runtime `run()` 已统一复用 `scripts/tests/runtime_testutil.py::run`。
- 8 份 Autonomy CLI `run()` 使用另一套 SystemExit 语义，不能错误并入 Runtime helper，因此新增 `scripts/tests/autonomy_testutil.py::run` 统一承载。
- 4 份完全相同的 Autonomy `git_repo()` 同步收敛到 `autonomy_testutil.py`；README 内容、Git identity 或分支语义不同的其他 Git fixture 保持本地，不做“大一统”。

### 10.2 环境与 CWD 隔离

`scripts/tests/conftest.py` 增加 function-scoped process-state boundary：

- 每个 test 默认获得 `<tmp_path>/tp-spec-user-root` 作为 `TP_SPEC_USER_ROOT`，不读取开发机真实 `~/.tp-spec`；
- pytest `monkeypatch` 在 teardown 自动恢复原环境；
- fixture 最终强制恢复 test 开始时的 CWD，作为已有 try/finally/`monkeypatch.chdir` 之外的兜底；
- `v514_orchestration_testutil.make_db()` 不再裸写 `os.environ`，调用方控制的 test-scoped user root 不会被覆盖。

原 21 个 env-mutation 文件中，除上述 `make_db()` 裸写外，其余均使用 `patch.dict`/`monkeypatch` 或显式 subprocess env；原 6 个 CWD 文件的修改点均已有 try/finally 或 monkeypatch。Task 6 没有发现需要新增 `serial` 的真实共享资源。

所有修改 helper 的主要调用方采用文件独立进程复验；Autonomy 8 个调用文件连续两轮通过。当前 pytest 9.0.2 下 `test_v522_workflow_delivery_hardening.py` 仍存在基线已知的组合挂起，未通过 skip/xfail/slow/serial 隐藏。

## 11. Task 7：duration profiling 与性能决策

Task 7 的历史测量使用 pytest 9.0.2，正式依赖当时要求 `pytest>=8,<9`，因此这些数据用于**相对热点和是否值得优化**，不替代当时正式 Release timing；当前候选口径见第 14.12 节。

### 11.1 Knowledge fixture 结论

对 `test_v529_knowledge_convergence.py` 单独测量：

- 完整 test environment bootstrap：约 `0.237～0.249s/test`；
- 代表性业务 call：约 `3.6～7.6s/test`；
- 14 个 node 独立执行累计约 `49.6s`；
- 最慢 node 为 knowledge projection 场景，约 `7.6s`。

因此昂贵部分不是 Git/SQLite/bootstrap 模板，而是完整 Task lifecycle / delivery / knowledge-convergence 业务路径。即使把 bootstrap 降到零，理论收益也不足整体约 10%，不值得引入 session/module immutable template、Git/SQLite 复制和 Windows 额外复杂度。**Task 7 明确选择不实施该优化。**

### 11.2 evidence-based slow

本阶段补充 `slow`：

| 文件 | 实测 wall time | 处理 |
|---|---:|---|
| `test_v529_knowledge_convergence.py` | node 独立累计约 49.6s | 保持 `slow` |
| `test_v529_delivery_rework.py` | 约 20.0s / 8 tests | 标记 `slow` |
| `test_v529_visual_verification.py` | 16.71s / 10 tests | 标记 `slow` |
| `test_v523_autonomy_integration.py` | 约 14.0～14.7s / 6 tests | 标记 `slow` |

`test_v526_temp_artifacts.py`（约 10.6s / 33 tests）和 `test_v513_record_first.py`（约 11.0s / 11 tests）暂不标 `slow`：成本尚不足以证明需要从普通领域回归中移出。

### 11.3 门禁前后

- Task 7 前 `cards and not slow`：105 passed，26.66s。
- 将真实高成本视觉验收文件归入 `slow` 后：95 passed，10.79s。
- wall time 下降约 59.5%；被移出的 10 个测试没有删除，仍由显式 slow / Release 全量门禁执行。
- 当前完整 collection：991 tests；primary layer 为 `unit=4`、`contract=502`、`integration=485`；`slow=38`、`serial=0`；日常快速门禁 510 passed / 481 deselected，12.93s。

Task 7 没有为了跑得快修改生产行为、降低断言、增加 skip/xfail，也没有拆大文件冒充性能优化。

## 12. Task 8：并行插件决策

### Task 8 决策：不引入 pytest-xdist

Task 6 已完成 writable root、SQLite/Git、环境变量、CWD、Temp、网络和端口隔离审计，89 个行为测试文件目前都是并行候选；但这只满足“可以进入 pilot”的前置条件，不等于已经证明并行执行稳定。

本次执行环境没有预装 `pytest-xdist`，且运行环境离线，无法临时安装插件；同时没有可执行 Windows pilot 的 PowerShell/Windows runner。计划的采用条件要求 representative suite 至少改善约 20%，连续 3 次无新增 flaky，并且 **Linux 与 Windows pilot** 都通过。当前无法完成这两个关键验证，因此 fail-closed 结论是：

- `requirements-dev.txt 保持不变`，不新增 `pytest-xdist`；
- 不写入 `-n auto`、`-n 2` 或 `--dist` 到正式 Gate；
- 不把“并行候选审计通过”误报为“xdist 已验证”；
- 本版本也不同时增加自定义 deterministic sharding，避免在没有必要收益证据时叠加第二套并行复杂度。

后续若有同时可运行 Linux/Windows 的支持环境，可重新执行固定 `-n 2 --dist loadfile` 三轮 pilot；只有达到原计划阈值才重新评估依赖。

## 13. Task 9：CI / Windows Full Gate 分层

### 13.1 PR Gate

GitHub Actions 将 PR 反馈拆成独立 job：

```bash
python -m pytest -q -m "smoke or ((unit or contract) and not slow)"
python -m pytest -q -m "integration and not slow and not serial"
```

`serial` 是正交执行约束；当前 catalog 中为 0。CI 保留“若未来出现 serial 则执行”的分支，并把 pytest `NO_TESTS_COLLECTED(5)` 仅在该空集合场景解释为成功，不影响真实测试失败码。Windows PR 运行同一快速 pytest 集合以及 `Test-TpSpecBase.ps1 -Mode Static`。

### 13.2 Push / Release Gate

Push 在 fast/integration 通过后仍执行完整回归：

```bash
python -m pytest -q --durations=50
```

完整回归不通过 marker 排除 `slow`、`serial` 或历史 regression。Windows push 继续执行：

```powershell
pwsh -File scripts/ci/Test-TpSpecBase.ps1 -Mode Full
```

因此 **fast != release**，领域定向通过也不等于 Release ready。

Task 9 当前 collection 为 995 tests；快速 Gate 实测 514 passed / 481 deselected，13.28s；非 slow、非 serial integration collection 为 447 / 995；serial 当前为 0。完整 995 用例仍留到 Task 10 正式 Release Convergence。

### 13.3 Windows Full 去重边界

`test_config_loader.py` 已被完整 pytest 收集，因此 `Mode Full` 不再先直接执行一次同一 Python 测试文件；`Mode Static` 仍保留直接 config-loader 单元入口，用于静态/离线基础检查。

`Test-RoleCatalog.ps1` 暂不删除。虽然它委托 `update_role_catalog.py --verify` 做结构验证，但它仍是 Windows/PowerShell shell、路径拼接和 Python 解释器调用入口的独立门禁；Python Role Catalog tests 与 Python verifier 不能证明该 PowerShell 入口可运行。

## 14. Task 10：最终 Release Convergence

### 14.1 最终环境与执行边界

- 当前代码版本保持 `v5.3.0`；本次治理没有发布所有者授权，不额外提升版本号。
- 历史环境记录：当时容器为 Python 3.13.5 / pytest 9.0.2，而仓库正式约束为 `pytest>=8,<9`；容器离线，无法安装受支持的 pytest 8.x。当前候选口径见第 14.12 节。
- 历史环境记录：容器全局存在仓库未声明的 pytest 插件（如 ddtrace/asyncio/cov/jsonreport）。这些插件会导致部分 subprocess-heavy 测试在 pytest 已输出 PASS 后进程不退出，因此当时测试统一使用 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，以接近 CI 仅安装 `requirements-dev.txt` 的受控插件面。
- 历史环境记录：当时没有 `pwsh`/Windows runner，因此 Windows Full Gate 记录为 **NOT RUN**；不能用该历史记录宣称跨平台 Release Gate 完整通过。

### 14.2 最终完整 pytest

最终只执行一次不按 marker 排除任何正式测试的完整回归：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q --durations=50
```

结果：

```text
995 collected
994 passed
1 skipped
2 subtests passed
0 failed
0 xfailed / 0 xpassed
140.56s
parallel workers: 1
```

唯一 skip 是既有 Windows-only portability 场景。

当前 slowest 10（call duration）：

| duration | nodeid |
|---:|---|
| 4.52s | `test_v522_workflow_delivery_hardening.py::...::test_each_stage_applies_to_verification_rework_review_and_delivery` |
| 3.63s | `test_v529_knowledge_convergence.py::test_knowledge_projection_distinguishes_not_required_not_run_and_result` |
| 3.33s | `test_v520_open_source_release.py::test_release_manifest_gate_distinguishes_working_tree_from_git_release` |
| 3.05s | `test_v529_visual_verification.py::test_delivery_rejects_active_or_cleanup_pending_temp_artifacts` |
| 2.51s | `test_v522_workflow_delivery_hardening.py::...::test_plain_delivery_checkpoint_cannot_complete_but_valid_ready_delivery_can` |
| 2.33s | `test_v522_workflow_delivery_hardening.py::...::test_new_verification_invalidates_old_delivery_result` |
| 2.10s | `test_v529_knowledge_convergence.py::test_no_knowledge_signal_is_not_required` |
| 2.08s | `test_v529_delivery_rework.py::...::test_reverification_requires_fresh_code_review_before_delivery` |
| 2.08s | `test_v529_knowledge_convergence.py::test_duplicate_requires_targeted_search_hit` |
| 2.06s | `test_v529_knowledge_convergence.py::test_created_validates_exact_canonical_and_indexes_only_that_ref` |

### 14.3 Task 10 分层数量与耗时

Task 10 的 995 个 collected item primary layer 严格互斥：

| 分层 | 数量 | 当前实测 | 口径 |
|---|---:|---:|---|
| smoke | 6 | 1.45s | 单进程 marker run |
| unit | 4 | 0.35s | 单进程 marker run |
| contract | 506 | 6.14s | 单进程 marker run |
| integration | 485 | 168.75s | 43 个 integration 文件独立进程 aggregate wall；单进程 marker 子集在当前容器存在顺序/遗留进程挂起，不作为正式耗时 |
| slow | 38 | 约 45.55s | 4 个 slow 文件独立进程 wall 合计（来自 integration 文件隔离实测） |
| serial | 0 | 0s | 当前无 serial item |

完整单进程 995 tests 为 140.56s。分层耗时不能相加得到 full time，因为 smoke 是其他层的正交子集，slow 也是 integration 的正交子集；integration 的 168.75s 还是文件隔离执行口径。

### 14.4 原始基线 / Task 10 Before / After

| 指标 | Before | After |
|---|---:|---:|
| pytest collected | 964 | 995 |
| smoke count/time | 无 | 6 / 1.45s |
| unit count/time | 无 | 4 / 0.35s |
| contract count/time | 无 | 506 / 6.14s |
| integration count/time | 无 | 485 / 168.75s（文件隔离 aggregate） |
| slow count/time | 无 | 38 / 约 45.55s（4 文件隔离 wall） |
| serial count/time | 无 | 0 / 0s |
| full time | ~575s | 140.56s |
| parallel workers | 1 | 1 |
| failures | 0 | 0 |
| skips | 1 个既有 Windows-only | 1 个 Windows-only |
| xfail/xpass | 交接未报告 | 0 / 0 |
| subtests | 2 | 2 |

观察到的 full wall time 比历史约 575s 低约 75.6%，但两者**不是严格同环境对照**：历史基线包含不同 pytest/进程执行策略，当前最终运行禁用了容器额外 plugin autoload。因此该差值只能作为当前反馈改善事实，不能全部归因于测试代码改造。

### 14.5 测试资产变化与覆盖守恒

从原始 964 到最终 995 的净增加为 31 个 collected item：

- Task 1：既有文件新增 5 个 Card/Change Set 回归；
- Task 3：新增 9 个卡片 workflow semantics 回归；
- Task 4：删除 1 个已证明 AST 完全相同的 exact duplicate；
- Task 5：新增 8 个测试治理回归；
- Task 6～7：新增 6 个 helper/isolation/slow 治理回归；
- Task 8～9：新增 4 个 CI/xdist 决策治理回归。

Task 10 当时计算：`964 + 5 + 9 - 1 + 8 + 6 + 4 = 995`。其后历史回归契约收敛又删除 24 个有明确 replacement 的冗余 case，当前为 971。

### 14.6 helper / fixture 收敛

- 7 份 Runtime `run()` 统一复用 `runtime_testutil.py::run`；
- 8 份 Autonomy `run()` 和 4 份同体 `git_repo()` 统一到 `autonomy_testutil.py`；
- `TP_SPEC_USER_ROOT` 改为 function-scoped test root，并由 pytest teardown 自动恢复；
- CWD 增加 function-scoped 恢复兜底；
- Knowledge immutable-template 因 bootstrap 只占整体不足约 10% 而明确不实施。

### 14.7 xdist 最终决策

**未采用 pytest-xdist。** 当前 89 个行为测试文件的资源隔离审计允许进入 pilot，但本次环境不能完成 Linux + Windows 固定 `-n 2` 三轮验证，也无法证明跨平台收益达到约 20% 阈值。因此不新增依赖、不写 `-n auto`，Release 仍使用单 worker。

### 14.8 Card visual evidence

Task 3 已使用真实 Chromium 对任务卡进行桌面 1440px 与移动 390px 渲染验证：无 document 横向溢出，console/page error 为 0；实际确认“工作步骤 / 执行角色 / 必需与条件步骤 / 条件参与角色 / Database / Security”均可辨识。该视觉事实没有用静态 DOM/CSS 契约替代。

### 14.9 未解决限制

1. Windows Full Gate：历史记录中当时无 `pwsh`，未执行；当前候选的 Windows Full Gate 结果见 B17b 接续记录。
2. pytest 版本：历史容器为 9.0.2，不是当时仓库声明的 `<9` 支持面；通过关闭非项目 plugin autoload 获得可重复完整回归。当前候选已固定 `pytest==9.1.1`，其本机证据见第 14.12 节。
3. `test_v522_workflow_delivery_hardening.py` 等 subprocess-heavy 测试在容器全局 plugin autoload 打开时存在进程退出异常；仓库不为此引入 skip/xfail 或生产代码变更。
4. xdist 未采用；若后续具备 Linux/Windows runner，可重新执行固定 `-n 2 --dist loadfile` pilot。

### 14.10 Task 10 后历史回归契约收敛

- Task 10 release candidate：995 collected。
- 本轮删除：24 个有明确 replacement 的历史冗余 case。
- 当前：971 collected；86 个行为测试文件。
- 当前 primary layer：unit 4、contract 485、integration 482；正交 marker：smoke 6、slow 38、serial 0。
- 累计相对原始 v5.3.0：`964 + 32 新增 - 25 删除 = 971`，净 `+7`。
- 删除的 25 个 case 中：1 个 exact duplicate；其余 24 个均有 `COVERAGE_MAPPINGS` 的 old nodeid → live replacement nodeid 证据。
- 收敛后完整回归：971 collected，970 passed、1 skipped、2 subtests passed、0 failed，168.24s；执行口径仍为单 worker 且 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`。
- 与 Task 10 的 140.56s 相比，本轮完整 wall time **没有下降**，反而增加 27.68s（约 19.7%）。这说明本轮收益是减少历史冗余、版本堆积与维护成本，而不是运行提速；两次运行存在环境抖动，不应把 wall time 差异归因于删除 24 个快速静态 case。
- 未通过大参数化、skip/xfail、弱化断言或合并独立业务场景来降低数字。
- 本轮结束条件不是达到某个目标数量，而是 exact duplicate=0 且没有新的可证明严格超集候选。

### 14.11 Top 慢测试调用链与初始化成本收敛

本轮从 971 collected 出发，不以删除数量作为目标，先对慢路径做调用链 profiling，再决定测试删除与 test-only 执行优化。

**测试资产变化：**

- 当前：86 个行为测试文件 / 968 个 pytest 用例。
- 新删除 3 个早期 workflow-delivery 历史场景，均由后续 canonical contract 严格覆盖并写入 `COVERAGE_MAPPINGS`。
- 累计删除 28 个冗余 case；相对原始 v5.3.0 为 `964 + 32 新增 - 28 删除 = 968`，净 `+4`。
- 当前 primary layer：unit 4、contract 485、integration 479；smoke 6、slow 38、serial 0。
- 没有通过 skip/xfail、弱化断言或大参数化来降低 collected 数量。

**调用链 profiling 结论：**

- `cli.main.build_parser()` 单次构建约 27.5ms；复用 parser 后 `parse_args()` 约 0.04ms。大量 in-process CLI 测试此前每条命令都重复构建完整 argparse 树。
- Knowledge 代表慢场景会调用 test CLI executor 21 次，其中成功命令会触发约 16 次 Card snapshot refresh。该测试不验证 Card，presentation-only refresh 成为主要额外成本。
- 同一 Knowledge 场景 A/B：正常约 6.78s；仅关闭无关 Card refresh 约 1.94s；再复用 parser 约 1.25s。
- Git fixture 不是主要瓶颈：`autonomy_testutil.git_repo` 单次初始化约 21ms，因此不引入 immutable Git template/cache。
- `config_loader` / `workflow_loader` cache teardown A/B 未改善长进程退化，因此没有加入“每 test 清缓存”的无效复杂度。

**历史 test-only 执行优化（v5.3.2 实施前，不是当前生产契约）：**

- 当时 `scripts/tests/cli_testutil.py` 复用静态 argparse parser，并在测试中抑制 Card 自动刷新。当前已删除抑制逻辑，生产入口自身就是显式卡片策略。
- 当前 executor 仅保留 parser 复用；不存在 `refresh_card` 测试开关。`test_v532_cli_contract.py` 直接调用生产入口，观察真实卡片调用与旧 HTML 的内容、修改时间；显式卡片测试单独验证渲染。
- 多个遗留 direct `climain.main()` 调用迁移到统一 executor，避免同一套测试框架出现两种成本模型。
- 生产 `cli.main`、Runtime、Task 状态、Card 生成逻辑均未为测试提速而修改。

**代表文件 wall-time 前后：**

| 文件 | 优化前 | 优化后 | 主要原因 |
|---|---:|---:|---|
| Knowledge  convergence | 30.44s | 9.05s | 去除无关 Card refresh + parser 复用 |
| Delivery rework | 14.82s | 3.62s | 同上 |
| Visual verification | 11.29s | 2.43s | 同上 |
| Record-first | 8.17s | 1.58s | direct-main 收敛 + parser 复用 |
| Integrated upgrade | 12.67s | 2.06s | direct-main 收敛 + parser 复用 |
| Autonomy integration | 8.14s | 5.88s | CLI 成本降低后剩余主要是真实 Git/integration 操作 |
| Release manifest 单一状态机 | 约 4.69s | 约 0.19s | 保留真实 Git repo/命令，但不再为同一状态机启动 5 次 Python 解释器 |
| HTML Cards | 6.05s | 5.45s | 保留真实 Card refresh，仅复用静态 argparse parser |

其中 **Knowledge 30.44s → 9.05s** 是文件级独立进程实测；不同运行轮次存在环境抖动，表格用于识别数量级收益，不把所有差值归因于单一函数。

**当前稳定快速门禁：**

- `smoke or ((unit or contract) and not slow)`：493 passed / 475 deselected；最终复测 pytest 12.49s、外层 wall 14.29s（前一轮曾测得 9.19s / 10.53s，存在环境波动）。
- 本轮没有引入 xdist，也没有修改正式 Release 全量门禁语义。
- 历史回归说明：当时容器为 pytest 9.x，而项目声明 `<9`；长单进程全集在该环境存在顺序/进程退出抖动。当前候选的依赖口径与本机证据见第 14.12 节。

**最终稳定回归（文件隔离口径）：**

- 历史稳定回归：86/86 个行为测试文件通过；968 collected 对应 967 passed、1 个既有 Windows-only skipped、2 subtests passed、0 failed。
- 每个文件使用独立 pytest 进程；pytest 主进程退出后清理同一进程组残留子进程，避免 subprocess-heavy 历史测试污染下一文件。该清理只存在于验证驱动，不进入产品或正式测试代码。
- 86 个文件的 pytest 报告时间合计 95.53s。该数值是逐文件 pytest 内部时间之和，不等于单一进程 full wall，也不包含外层调度工具开销，因此只作为稳定文件隔离口径。
- 当前 Top 文件：workflow-delivery 10.40s、Knowledge convergence 7.93s、Autonomy integration 7.58s、HTML Cards 5.45s、Integrated upgrade 3.64s、Delivery rework 3.58s。
- 与历史 168.24s 单进程结果执行模式不同，不能把 95.53s 直接解释成 43.2% 的严格 full-wall 提升；可直接比较的代表文件 A/B 和 fast gate 才是本轮性能收益证据。

### 14.12 B17b 当前候选：Windows 产物采集与 pytest 9.1.1 口径

本节是 B17b 当前候选的增量记录；前文的历史环境记录不改写为本机当前结果。

- `requirements-dev.txt` 当前固定为 `pytest==9.1.1`。本机实际核验环境为 Python 3.13.5 / pytest 9.1.1；这只证明该锁定组合，不把未运行的 pytest 8.x 或其他 9.x 版本写成已支持。
- 基座没有声明必须加载的第三方 pytest 插件。CI 和 `Test-TpSpecBase.ps1 -Mode Full` 对 pytest 调用统一设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，仅使用 pytest 内建插件；调用结束后 PowerShell 恢复原环境变量。`PYTEST_PLUGINS`、`PYTEST_ADDOPTS` 和 `-p` 未被用于注入额外插件。
- pytest 9.1.1 的真实 JUnit 接收回归覆盖全成功 subTest、全失败 subTest、混合 subTest 和 teardown error；报告接收只验证 producer 声明统计与实际 failure/error/skipped 节点的一致性，不把声明统计扩展为虚构 testcase，也不将报告来源认证为真实执行。
- 当前候选 `collect-only` 实测为 **1451 tests collected**；本轮新增的 4 个回归均在 47 项浏览器报告集合中。
- B17b 受影响集合采用外部父进程记录命令、Python/pytest 版本、stdout、stderr、退出码和终态。本轮最新候选实测：`test_v532_browser_reports.py` **47 passed / exit 0**；`test_v532_recording.py` **87 passed / exit 0 / 132.17s**。证据位于外部 `.tp-spec/docs/B17b/test-runs/20260909-b17b-browser-05/` 与 `20260909-b17b-recording-03/`，不进入发布包。
- Windows 采集在任务目录句柄上逐层相对创建 `evidence/collected/<request>/<attempt>`，拒绝 reparse point；attempt 和文件均独占创建。写入、`fsync`、大小及 SHA 校验针对同一打开对象；目录替换反例不会在外部目录生成文件。已知未提交采集失败只通过同一文件句柄标记删除；提交状态未知的 attempt 不做无条件清理。
- WIP-4 之前的 Windows Full Gate 记录为 `1445 passed / 2 skipped / 2 subtests passed`；本轮四项修复后只重跑了 Static 和受影响集合，没有把该历史结果写成当前候选 Full Gate。真实 MarkItDown `0.1.7` 的既有本地转换证据仍可复用，但不代表所有格式和业务流程均已验收。
- 本轮独立审查已实际执行：四个代码 Finding 均已复核关闭；当前仅保留“多文件采集失败资产清理”和“PowerShell 极端位置异常后的环境恢复”两个建议项。原始 35 个失败没有伪造逐项销账，B11/B12/B13/B15 仍未完成，因此当前候选仍不是完整 B17b 通过。
