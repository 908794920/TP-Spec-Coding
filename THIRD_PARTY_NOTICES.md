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
- `mattpocock/skills` — explicit/model-invoked Skill boundaries, spec synthesis, vertical-slice task decomposition.
- `flankerhqd/cyvisguard` — capability-based safety policy and monotonic suspicion/finding combination.
- `openai/openai-agents-python` — filtered agent handoff context design.
- `BloopAI/vibe-kanban` — deterministic repository before/after Git identity facts.

These references do not create runtime dependencies or change TP-Spec-Coding's license.

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

**锁文件来源与限制：**W02 当期容器不能连接 npm Registry 下载包体。通过可用的 GitHub 只读工具读取公开生成的 `zenbu-labs/terminal-code/package-lock.json`，Git blob `4b867289582766b2fa081dee5980773300153f4c`，只复用其中 49 个 npm 包的解析版本、resolved、integrity、依赖及平台/许可证元数据；不引入该应用源码、bin 入口或产品逻辑。根包信息改为本项目，React 移入运行依赖后用 npm 10.9.2 执行离线 `--package-lock-only --ignore-scripts` 归一化，并通过 `npm ci --dry-run --offline --ignore-scripts --no-audit --no-fund` 检查依赖图。所有包体仍待首次实际联网安装与校验，不把 dry-run 当作安装/构建通过。

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

W03 已用 npm 10.9.2 对新增锁文件离线归一化并执行 `ci --dry-run --offline --ignore-scripts --no-audit --no-fund`。当期仍不能下载 npm 包体；**该结果只证明锁依赖图可解析，不证明包体 SRI 已实际校验、前端安装、构建、类型检查或浏览器通过**。首次联网 `npm ci` 由用户本地统一合并后执行。

来源：
- `https://app.unpkg.com/@xyflow/react@12.10.1/files/package.json`
- `https://github.com/xyflow/xyflow/blob/main/packages/react/package.json`
- `https://github.com/xyflow/xyflow/blob/main/pnpm-lock.yaml`
- `https://github.com/thesongzhu/Friday/blob/51684b987c041193f079563056cc43aa823aa559/pnpm-lock.yaml`
- `https://reactflow.dev/api-reference/react-flow`
- `https://reactflow.dev/learn/layouting/layouting`
