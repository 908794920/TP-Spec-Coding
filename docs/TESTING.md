# TP-Spec-Coding 本仓开发与验证

## 1. 适用范围与优先级

**本仓移除历史测试套件；只对当前开发功能编写必要的临时单元测试，执行后清理。日常开发、提交、推送、PR、批次结束和最终交付均不默认全量测试。**

这是 v5.3.3 的项目执行策略，依据用户在本地工作台专项中的明确决定，适用于修改 TP-Spec-Coding 自身源码的主 Agent、子 Agent、本地执行者和云端开发。通用 TDD / 测试 / Review / 交付 Skill 的默认全量回归或永久测试要求，不能覆盖该策略。完整功能范围对账不等于必须重跑全仓测试。

本规则不自动扩展到被管理的 Java 等业务仓库。业务项目已有测试、夹具、基线仍按该项目规则与用户授权处理；不得借基座清理去删除它们。

## 2. 按本次改动选择检查

| 当前工作 | 允许的验证范围 |
|---|---|
| 阅读、需求讨论、普通说明修改 | 不运行产品测试 |
| 删除文件、调整调用或配置 | 核对实际引用、必要入口及直接受影响的配置 |
| 修改函数、接口、状态或取值 | 当前功能的临时单测和直接受影响的正反例 |
| 修改页面或交互 | 当前页面、映射与交互；静态结构检查不冒充浏览器通过 |
| 修改启动、构建、依赖 | 对应启动/退出、构建或类型检查；命令彼此分开，不串全量测试 |
| 提交、推送、制作增量或累计 Patch | 核对 A/M/D、补丁适用性与源码身份，不因此新增一轮产品验证 |

这不是每次必跑清单。不先运行 collect-only 或全量测试来证明测试可以删除；已验证且未受本次改动影响的内容不重复执行。发现具体问题时，补相应场景，不自动扩展成全仓 lint、构建或“质量自检”。

## 3. 临时验证生命周期

先明确输入、预期、错误分支和目标源码，在本次拥有的系统临时目录或隔离验证目录编写用例；不要放入产品源码、用户现场 Runtime 或业务数据目录。普通配置/说明修改没有相应代码行为时，不为凑数量编写测试。

只执行明确的文件/用例或当前功能命令，记录实际命令、关键环境、退出码、结果和未执行原因。需要 pytest 等可选工具时使用适合当前用例的环境，由执行者准备；不恢复基座统一测试依赖，不自动安装/升级生产依赖。标准库能完成的局部验证无需引入新框架。

验证结束后删除本次临时用例、夹具和临时环境；不进入 Git、Patch、归档目录或隐藏的长期套件，不靠 `.gitignore` 假装已删除。清理仅限本次拥有且获准的路径；真实结果在简短交付说明中保留，失败或未运行不得改为 PASS。已有报告、Evidence、用户原件及历史验收事实不随测试代码删除。

没有长期回归用例就没有对应的持续覆盖保证。交付说明只能声明本次实际验证的范围，不能写“全系统测试通过”。

## 4. 自动执行边界

原基座测试 CI、pytest 发现配置和 PowerShell Full 调度已退出；没有默认测试工作流。不把它们改名为自检、诊断、发布检查或质量闸门后恢复，也不在 Git Hook、npm 安装/启动/构建生命周期中隐藏调用。

**确需全量测试时，先说明具体影响和原因，由用户明确决定；Reviewer 建议、风险等级、提交、推送或“为了保险”都不产生全量执行授权。** 当前功能的必要局部检查不需逐条再次确认，但不得借此扩大到全仓。

仓库外的 GitHub 分支保护、组织工作流或机器 Git Hook 不由此源码修改自动改变。如果它们仍要求已退役 CI 状态，说明外部设置冲突，由有权限者处理；不能伪造状态通过或重建旧套件。未核验的外部配置不声称已清理。

## 5. 保留的产品能力与维护工具

Runtime 的 `verify`、证据真实性、新鲜度、验收、Review、Delivery 和正式结单继续按原契约工作；`full` 验收范围不等于执行全量测试。不得通过放宽业务规则解决基座测试清理。

`task run-pytest` 仍用于已获准的业务项目指定文件/用例，不接收外部 Temp 测试路径；使用前需在所选解释器准备 pytest。临时目录或非 pytest 检查按本次获准命令执行，已有输出需要入账时使用原报告接收能力，不为记账重新运行。`scripts/Test-TpSpecTask.ps1` 的 Task 检查能力保留。

已有 Base JSON、JUnit 等结果仍可接收；历史 Base 测试脚本退出不代表历史报告失效，也不把历史通过变成本轮通过。具体用法见 [生命周期操作参考](agents/tp-software-lifecycle.md)。

Role Catalog、Manifest、版本和文档导航工具保留其原有职责。仅在相应内容变化或发现具体缺口时使用，不打包成日常必跑合集，不关闭真实性检查掩盖删除遗漏。

## 6. 交付与真实体验

按已确认批次交付实际增量 Patch，最后交付固定原始基线到最终代码的累计 Patch；补丁应包含正确删除项。局部验证完成、Patch 已交付、用户本地合并、真实任务体验和正式上线分别记录。

真实使用需要用户本地执行时准确列为待验；没有无关全量测试结果不阻止提供试用代码。发现本次功能已确认错误仍应修复，不以“之后用户会使用”替代已知问题处理。

## 7. 历史验证记录（非当前执行规则）

以下保留旧版文档已经记录的测量、结果与限制，不是本轮重跑，也不背书当前源码。旧套件的分类、留存、Smoke/CI/Full 执行矩阵已退出；历史路径和依赖版本只用于追溯，不是现有文件或安装要求。原完整审计可从本次清理前的 Git 历史读取，不在源码中保留测试副本。

> 以下“当前”“本轮”均指各历史阶段，不是 v5.3.3 W01。

### 历史基线与口径

- **原始 v5.3.0 基线**：87 个测试文件 / 964 个 pytest 用例；正式全量基线为 964 passed，约 575 秒。
- **Task 1～3 后**：88 个测试文件 / 978 个 pytest 用例。Task 1 在既有文件增加 5 个回归，Task 3 新增 `test_card_workflow_semantics.py` 的 9 个回归。
- **Task 4～5 状态**：89 个有实际 collected item 的测试文件 / 985 个 pytest 用例。变化为 Task 5 新增 8 个治理测试，同时 Task 4 删除 1 个已证明 exact duplicate。
- **Task 6～7 当前状态**：仍为 89 个行为测试文件 / 991 个 pytest 用例。新增 6 个测试体系治理回归，用于保护 helper 收敛、function-scoped user root、并行候选审计和 evidence-based slow 分类；没有新增业务行为测试。
- **Task 8～9 后**：仍为 89 个行为测试文件 / 995 个 pytest 用例。新增 4 个测试治理回归，保护 xdist 决策、PR/Release CI 分层、Windows Full 去重和贡献者门禁文档；没有新增业务行为测试。
- `scripts/tests/test_catalog.py` 是测试治理数据文件，文件名匹配 pytest 发现规则但自身不定义测试 item，因此不计入上述 89 个行为测试文件。
- **Task 10 最终状态**：已执行一次完整 pytest 回归；当前 995 collected，994 passed、1 skipped、2 subtests passed，0 failed，耗时 140.56s。
- **历史回归契约收敛后**：86 个行为测试文件 / 971 个 pytest 用例。相对 Task 10 再删除 24 个已证明由 canonical replacement 严格覆盖或完整吸收的历史 case；连同 Task 4 的 1 个 exact duplicate，累计删除 25 个冗余 case。完整回归为 970 passed、1 skipped、2 subtests passed、0 failed，168.24s。没有删除独立业务/兼容/故障回归。
- **Top 慢测试调用链收敛后**：86 个行为测试文件 / 968 个 pytest 用例。新增 3 条严格 superseded coverage mapping，累计删除 28 个冗余 case；primary layer 为 unit 4、contract 485、integration 479。测试专用 CLI executor 复用 argparse parser，并让非 Card 契约默认不支付 presentation-only Card refresh；生产 CLI/Runtime 行为未修改。

### 历史资源使用

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

### 历史 Task 5 局部结果

| 命令 | selected | 结果 |
|---|---:|---|
| `-m "smoke or ((unit or contract) and not slow)"` | 504 / 985 | 504 passed，481 deselected，12.89s |
| `-m "cards and not slow"` | 105 / 985 | 105 passed，880 deselected，27.17s |
| `-m "workflow and not slow"` | 191 / 985 | collection 正确；pytest 9.0.2 在既有 `test_v522_workflow_delivery_hardening.py` 组合执行上挂起，未得到正式 PASS/FAIL 总结 |

`workflow` 的挂起不通过把该文件误标为 `slow` 或 `serial` 来规避。使用 Task 3 commit `bb62f31` 的未修改代码在同一 pytest 9.0.2 环境运行该问题文件也会组合挂起，因此该现象不是 Task 4/5 marker 改造引入。当时仓库正式开发依赖为 `pytest>=8,<9`；这是历史环境记录，当前候选口径见第 14.12 节。

### 历史 Task 7 测量

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

### 历史 Task 9 结果

Task 9 当时记录：995 tests；快速 Gate 514 passed / 481 deselected，13.28s；非 slow、非 serial integration collection 为 447 / 995；serial 为 0。对应自动执行链现已删除。

### 历史 Task 10 环境与执行边界


- 当前代码版本保持 `v5.3.0`；本次治理没有发布所有者授权，不额外提升版本号。
- 历史环境记录：当时容器为 Python 3.13.5 / pytest 9.0.2，而仓库正式约束为 `pytest>=8,<9`；容器离线，无法安装受支持的 pytest 8.x。当前候选口径见第 14.12 节。
- 历史环境记录：容器全局存在仓库未声明的 pytest 插件（如 ddtrace/asyncio/cov/jsonreport）。这些插件会导致部分 subprocess-heavy 测试在 pytest 已输出 PASS 后进程不退出，因此当时测试统一使用 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，以接近 CI 仅安装 `requirements-dev.txt` 的受控插件面。
- 历史环境记录：当时没有 `pwsh`/Windows runner，因此 Windows Full Gate 记录为 **NOT RUN**；不能用该历史记录宣称跨平台 Release Gate 完整通过。

### 14.2 最终完整 pytest

历史 Task 10 记录了一次不按 marker 排除测试、关闭额外 plugin autoload 的完整回归；该命令现已退役。

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
4. xdist 未采用；旧版的后续 pilot 建议已随测试策略退出，不是当前待执行项。

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
