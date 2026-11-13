# Third-Party Notices

TP-Spec-Coding itself is distributed under the repository's MIT License. The v5.3.4 implementation also studies or adapts small ideas from third-party open-source projects. No third-party repository is vendored into this source tree.

## Alibaba OpenCodeReview

- Project: `alibaba/open-code-review`
- Source commit reviewed: `794a971a9a4816e9adb77a4151708ccf54b03e74`
- Upstream file studied: `internal/diff/resolver.go`
- License: Apache License 2.0
- TP-Spec-Coding file: `cli/review_locator.py`
- Adaptation: deterministic review finding location strategy — normalized diff-hunk matching, full-file fallback, and cross-file relocation only when the match is unique.

The TP-Spec-Coding implementation is a Python adaptation integrated with TP-Spec-Coding's own Review/Evidence contracts; the upstream repository is not bundled as a runtime dependency.

## Microsoft MarkItDown

- Project: `microsoft/markitdown`
- Runtime package: `markitdown[pdf,docx,xlsx,xls,pptx]==0.1.7`
- License: MIT
- TP-Spec-Coding integration: local document normalization through MarkItDown's `convert_local` Python API.
- Source handling: upstream source code is not copied or vendored into this repository; MarkItDown is installed as a runtime dependency.

The TP-Spec-Coding boundary intentionally exposes only explicit local-file conversion. Remote retrieval remains a separate responsibility.

## Design References Not Vendored

### Graphify

- Project: `Graphify-Labs/graphify`
- Evaluated package: `graphifyy==0.9.53`
- Evaluated commit: `33362d969292b57eda82f3fbd9eb5f3f5bc9bbc2`
- License: Apache License 2.0
- Decision: the v5.3.1 Provider Spike is No-Go because the evaluated Java output failed the upstream endpoint validator.
- Distribution boundary: Graphify is not vendored and is not a runtime dependency of TP-Spec-Coding.

No Graphify source, Java extractor, cache implementation, or Provider Adapter is included in this source tree. A future upstream version requires a new independent Spike before adoption.

The following projects were used as architecture/design references only; their source code is not copied into TP-Spec-Coding:

- `sickn33/agentic-awesome-skills` — semantic Skill selection with deterministic catalog validation.
- `mattpocock/skills` — explicit/model-invoked Skill boundaries, spec synthesis, vertical-slice task decomposition; the scoped clarification and domain terminology adaptation is recorded below.
- `flankerhqd/cyvisguard` — capability-based safety policy and monotonic suspicion/finding combination.
- `openai/openai-agents-python` — filtered agent handoff context design.
- `BloopAI/vibe-kanban` — deterministic repository before/after Git identity facts.

These references do not create runtime dependencies or change TP-Spec-Coding's license.

### 调试、测试与迁移方法参考

2026-11-13 核对以下原始资料，在既有 `systematic-debugging`、`testing-strategy` / `references/test-value.md` 和 `database-engineering` 中独立撰写条件方法与项目示例。仅参考公开工具语义和研究方法，未复制手册段落、源代码或上游测试，未引入运行依赖、固定新流程或模型调用。

- [Git bisect 2.56.0 官方手册](https://git-scm.com/docs/git-bisect/2.56.0)：可比的好坏提交、稳定症状探针、无法测试版本的跳过与候选边界；不将过渡提交直接当作已证实根因。
- [Hypothesis 官方教程](https://hypothesis.readthedocs.io/en/latest/tutorial/introduction.html)及[失败重放](https://hypothesis.readthedocs.io/en/latest/tutorial/replaying-failures.html)，查阅时文档版本 6.170.15；Chen、Cheung、Yiu 的 [Metamorphic Testing 原始报告 HKUST-CS98-01](https://www.cse.ust.hk/faculty/scc/publ/CS98-01-metamorphictesting.pdf)：从已有契约选择属性或输入变换关系，保留可重放反例和关键具体期望。未安装 Hypothesis 或要求目标项目新增测试框架。
- [MySQL 8.4 原子 DDL 官方说明](https://dev.mysql.com/doc/refman/8.4/en/atomic-ddl.html)：单条原子性不代表多语句整体回滚；部分失败后的处理依据目标版本、引擎、工具语义与实际回读，不把 MySQL 规则泛化到所有数据库。

### 需求澄清与数据语义方法适配

- **Matt Pocock Skills**，Copyright (c) 2026 Matt Pocock，MIT。固定提交 `5863806dd4e15c63174bee4e7515a4256792ecfa` 的 [grilling](https://github.com/mattpocock/skills/blob/5863806dd4e15c63174bee4e7515a4256792ecfa/skills/productivity/grilling/SKILL.md) 与 [domain-modeling](https://github.com/mattpocock/skills/blob/5863806dd4e15c63174bee4e7515a4256792ecfa/skills/engineering/domain-modeling/SKILL.md) 用于核对现有按依赖澄清方法，并补充业务术语消歧、具体场景检验及真实取舍理由。改写位置为 `skills/capabilities/requirement-clarification/` 及需求经理入口；不采用无条件遍历所有分支、固定委派、再次确认或额外创建术语/决策台账。
- **NVIDIA Auto Ontology**，Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES，Apache-2.0。固定提交 `fc43a82600e18b19d159c52023f54f5572f537ac` 的 [modeling](https://github.com/NVIDIA/auto-ontology/blob/fc43a82600e18b19d159c52023f54f5572f537ac/skills/nvidia-ontology-management/references/modeling.md) 与 [query-validation](https://github.com/NVIDIA/auto-ontology/blob/fc43a82600e18b19d159c52023f54f5572f537ac/skills/nvidia-ontology-query/references/query-validation.md) 用于中文改写 `database-engineering` 的业务语义与查询核对方法及相关引用。仅吸收问题口径、物理映射、关联与粒度、SQL/结果/回答分开核验；不引入上游平台、模型调用、认证或发布流程。[上游许可](https://github.com/NVIDIA/auto-ontology/blob/fc43a82600e18b19d159c52023f54f5572f537ac/LICENSE)，Apache-2.0 全文复用仓库已保留的 [标准许可副本](licenses/impeccable-APACHE-2.0.txt)。

Matt Pocock Skills 的许可声明随上述改写保留：

```text
MIT License

Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Browser Report Interface References (Not Vendored)

- Microsoft Playwright, Apache License 2.0: public JSON reporter and result types inspected at tag `v1.63.0`. The native report's per-test outcomes and attachment references inform `cli/browser_reports.py`; no upstream engine/reporter source is copied into the runtime. Source: https://github.com/microsoft/playwright/tree/v1.63.0 .
- Midscene (`web-infra-dev/midscene`), MIT: package exports and license inspected at tag `v1.12.3`; official Playwright fixture/reporter and caching documentation inform the optional integration guidance. Original HTML is retained as opaque evidence, not parsed into a signed AI judgment. Source: https://github.com/web-infra-dev/midscene/tree/v1.12.3 .

These references are not Python/Base runtime dependencies and do not imply an installed or runtime-validated Playwright/Midscene/browser/model combination. Authorized business projects own their native dependencies, lockfiles, test assets and upgrade verification. No browser binaries, model credentials or upstream source packages are distributed in this repository.


## v5.3.3 本地工作台前端依赖（W02）

本批新前端独立实现，不复制 EvoFlow 或其他应用的业务代码、界面素材和字体。

| 直接依赖 | 锁定版本 | 包元数据中的许可证 |
|---|---|---|
| react / react-dom | 19.2.8 | MIT |
| vite | 8.2.1 | MIT |
| @vitejs/plugin-react | 6.0.5 | MIT |
| typescript | 5.9.3 | Apache-2.0 |
| @types/react / @types/react-dom | 19.2.18 / 19.2.4 | MIT |
| @types/node | 22.20.1 | MIT |

间接构建依赖包括 Rolldown（MIT）、Lightning CSS（MPL-2.0）、detect-libc（Apache-2.0）、picocolors（ISC）、source-map-js（BSD-3-Clause）等，逐项版本/许可证声明见 `package-lock.json`，实际使用应保留安装包附带的许可证。本声明不是对包体内容已完整审核或下载的结论。

**锁文件来源与限制：**W02 当期容器不能连接 npm Registry 下载包体。通过可用的 GitHub 只读工具读取公开生成的 `zenbu-labs/terminal-code/package-lock.json`，Git blob `4b867289582766b2fa081dee5980773300153f4c`，只复用其中 49 个 npm 包的解析版本、resolved、integrity、依赖及平台/许可证元数据；不引入该应用源码、bin 入口或产品逻辑。根包信息改为本项目，React 移入运行依赖后用 npm 10.9.2 执行离线 `--package-lock-only --ignore-scripts` 归一化，并通过 `npm ci --dry-run --offline --ignore-scripts --no-audit --no-fund` 检查依赖图。W02 交付时尚未下载包体或完成首次联网校验，不把当期 dry-run 当作安装/构建通过；后续批次的实际验证范围见 [CHANGELOG](CHANGELOG.md)，不由这段来源说明判断当前安装状态。

元数据来源（读取日期 2026-09-14）：
`https://github.com/zenbu-labs/terminal-code/blob/main/package-lock.json`

官方技术依据：
- `https://vite.dev/guide/`
- `https://vite.dev/guide/api-javascript.html`
- `https://react.dev/learn/build-a-react-app-from-scratch`

W02 未预装图形库；W03 的实际新增依赖见下一节。


## v5.3.3 任务关系图依赖（W03）

- `@xyflow/react`：锁定 `12.10.1`；React Flow 基础库，MIT。使用公开节点/连线和浏览交互 API，自行实现 TP-Spec 节点/映射/样式，不采用 Pro 模板，不复制 EvoFlow 或其他应用代码。
- `@xyflow/system`：间接锁定 `0.0.75`，MIT；其 D3 交互依赖由库内部使用。Zustand `4.5.7` 为图组件的间接依赖，不另建本应用全局状态框架。
- 本批使用一个本地分层布局实现，未新增 Dagre、ELK 或 D3 Force 布局依赖；不是自研图形交互库。
- 保留 W02 全部既有包版本，新增 20 个锁定包节点（总计 69 个）；包含 XYFlow、classcat、zustand、use-sync-external-store 及所需 D3/类型包。实际安装包的许可证仍需随依赖保留，不能由本说明代替。

**元数据来源与限制：**官方已发布包 `@xyflow/react@12.10.1` 的 package.json 与官方仓库用于核对入口/API、依赖和 MIT 声明；新增锁定版本/SRI/依赖解析从公开生成的 `thesongzhu/Friday/pnpm-lock.yaml` 的固定提交 `51684b987c041193f079563056cc43aa823aa559` 读取，并结合上游锁文件核对。只复用 npm 解析元数据，不引入该应用的代码、字体、测试、运行依赖集合或产品逻辑。没有把官网仓库当前显示的版本当作本项目安装版本。

W03 已用 npm 10.9.2 对新增锁文件离线归一化并执行 `ci --dry-run --offline --ignore-scripts --no-audit --no-fund`。当期仍不能下载 npm 包体；**该结果只证明锁依赖图可解析，不证明包体 SRI 已实际校验、前端安装、构建、类型检查或浏览器通过**。这记录 W03 当期的环境限制，不表示后续批次从未联网安装；本机依赖是否就绪仍须按当前环境确认。

来源：
- `https://app.unpkg.com/@xyflow/react@12.10.1/files/package.json`
- `https://github.com/xyflow/xyflow/blob/main/packages/react/package.json`
- `https://github.com/xyflow/xyflow/blob/main/pnpm-lock.yaml`
- `https://github.com/thesongzhu/Friday/blob/51684b987c041193f079563056cc43aa823aa559/pnpm-lock.yaml`
- `https://reactflow.dev/api-reference/react-flow`
- `https://reactflow.dev/learn/layouting/layouting`


## P1 视觉方法适配

以下固定版本用于 `skills/capabilities/ui-prototype-design/SKILL.md` 及其 `references/interaction-and-motion.md` 的方法适配。未打包完整第三方仓库、上游引擎、安装器、Hook、字体或素材；两份许可证作为离线分发声明保留。适配文件的来源条款仍须保留，不能用仓库 MIT 声明替代第三方许可。

| 来源与固定版本 | 实际阅读文件与采用部分 | 本项目取舍 |
|---|---|---|
| [Impeccable](https://github.com/pbakaus/impeccable/tree/f2c7051853848826aac2f4646581d62a732155ad)，Skill 4.3.1 | `.pi/skills/impeccable/SKILL.md`、`reference/operate.md`、`reference/animate.md`、`reference/adapt.md`、`scripts/impeccable`、根 `LICENSE` | 操作型产品的熟悉控件/状态、目的性动效、中断/清理、结构性响应式与真实浏览器证据；改写为中文 Task/角色/授权方法，补业务三类清单、组件实际调用、Mock 与产品边界 |
| [Taste](https://github.com/Leonxlnx/taste-skill/tree/e79ca9ec7e071eb3a3b623c4fb752e853fc3ed58) | `skills/taste-skill/SKILL.md`、`skill.sh`、根 `LICENSE` | 仅互补采用先理解 brief、保留现有品牌和用户约束的方法；该版本声明不面向 dashboards/data tables/multi-step product UI，不能作为业务工作台的完整方法 |

**许可与归属：** Impeccable，Copyright 2025 Paul Bakaus，Apache License 2.0，见 [原许可副本](licenses/impeccable-APACHE-2.0.txt)；Taste，Copyright (c) 2026 Leonxlnx，MIT，见 [原许可副本](licenses/taste-skill-MIT.txt)。副本分别与固定版本的 Git blob `bb3f6d23b1f8025514a62a12b51b47d73e3c9aa9`、`48a2f6640b81ff8eca9ce7f6a96337692713ef5b` 一致。固定 Impeccable 根 `NOTICE` 路径返回 404；未据此声称已扫描整仓的其他声明。

**适配边界：** 两个固定来源在 2026-09-16 有已读取的提交记录，不能据此保证后续维护质量或称为最新版本。不采用营销页默认字体/配色/动效强度、固定断点/设备矩阵、强制新建 PRODUCT.md/DESIGN.md，亦不引入上游自动下载/安装链。现有栈足以实现时不增加包依赖或付费工具；普通适配成本是本地方法和导航维护，上游升级需要重新核对适用部分，不自动跟随。

这是方法适配，不是上游引擎、全部命令或其检测器已安装/实测的声明。本地代表原型的实际浏览器范围及限制随 P1 Patch 交付记录，不能推为原业务、真实权限、Windows 安装或全版验收通过。

## Unslop 与 Huashu Design 视觉方法适配

- **Unslop** 由 Damir Sokolovsky（@heydamir）创作，采用 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。以固定提交 `97daa3eb365670ea3f87ed85356cbfcee18105a5` 的 Skill 为来源，改写按画面定位问题、从产品内容确定视觉重点、按影响范围修改并复看的方法。[上游仓库](https://github.com/heydamir/unslop) · [固定版本 Skill](https://github.com/heydamir/unslop/blob/97daa3eb365670ea3f87ed85356cbfcee18105a5/skills/unslop/SKILL.md)
- **Huashu Design**，Copyright (c) 2026 alchaincyf (花叔 · 花生)，采用 MIT 许可。以固定提交 `e8d1148a80d5a281d4247cffe320add3df017928` 的设计风格、方向、网页与打磨参考为来源，改写同类参考选用、将视觉关系落到实现及原尺寸截图复看的方法。[设计风格](https://github.com/alchaincyf/huashu-design/blob/e8d1148a80d5a281d4247cffe320add3df017928/references/design-styles.md) · [设计方向](https://github.com/alchaincyf/huashu-design/blob/e8d1148a80d5a281d4247cffe320add3df017928/references/directions.md) · [网页参考](https://github.com/alchaincyf/huashu-design/blob/e8d1148a80d5a281d4247cffe320add3df017928/references/modules/web.md) · [打磨参考](https://github.com/alchaincyf/huashu-design/blob/e8d1148a80d5a281d4247cffe320add3df017928/references/polish-loop.md) · [原许可](https://github.com/alchaincyf/huashu-design/blob/e8d1148a80d5a281d4247cffe320add3df017928/LICENSE)

本项目将这些方法按现有 UX、产品、实现与视觉验证职责用中文改写，保留当前授权和证据边界。未复制上游脚本、素材和模板，未引入固定评审轮次、方案数、随机选风格或新运行依赖。

Huashu Design 的许可声明随上述方法改编保留。

```text
MIT License

Copyright (c) 2026 alchaincyf (花叔 · 花生)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
