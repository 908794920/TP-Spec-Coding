# Third-Party Notices

TP-Spec-Coding itself is distributed under the repository's MIT License. The v5.3.2 implementation also studies or adapts small ideas from third-party open-source projects. No third-party repository is vendored into this source tree.

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
