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
