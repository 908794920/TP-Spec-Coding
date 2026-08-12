# Wiki Full Build / Rebuild — Canonical AI Protocol

一次只处理一个 repo。

1. `wiki doctor`
2. `wiki init --repo <id>`
3. `wiki build --repo <id>`（内部执行 initial scan + topology-aware plan；无 baseline 时所有 scanner-visible source 先记为 STRUCTURAL/added，plan 再标注 `wiki_eligibility`；initial 不触发 mass-change guard）
4. AI 先按 topology 中的 Wiki eligibility 与真实源码做**能力/子系统聚类**，再设计高信息密度 Wiki 结构；一个源码文件不等于一篇 Markdown。遵循 `wiki/rules/content-standard.md` 的 Currentity、Existence≠Authority、Responsibility Attribution、Pipeline Stage Ownership 与 Interface/Scope Exactness；关键 cite 首建即带行号。任何 command/CLI option/config key/threshold/default/mandatory step 必须回真实 parser/schema/config/canonical protocol 核验，禁止根据旧模板或相邻流程补全。
5. 分批填充正文；不修改 source repo。对同一能力同时存在新旧实现的场景，必须明确 CURRENT 与 COMPATIBILITY/RECOVERY/HISTORICAL，不能混成一条主流程。
6. `wiki manifest-refresh --repo <id>`
7. `wiki verify --repo <id>`，FAIL 必须返工。
8. 执行 `wiki coverage --repo <id> --details`，记录 effective covered/eligible/uncovered、证据强度与 `first_build_readiness`。默认 `quality.initial_build_effective_coverage_min=0.95`：低于阈值时状态必须视为 `BUILD_INCOMPLETE`，继续处理 uncovered；不能因为 `effective_wiki_coverage_warn=0.0` 或 `verify PASS` 就宣布首次构建完成。应有长期代码理解价值的文件映射到现有/聚合 Wiki；确无独立价值的才调整 eligibility 并保留真实 reason。然后重新 `manifest-refresh → verify → coverage`。不得为了 100% 调分母或制造一文件一文档。
9. 关键 cite 优先放在实际断言所在正文 section；“溯源/参考/证据”仅可汇总，不得成为唯一 cite 位置。然后执行 `wiki audit --repo <id> --full`；首次构建必须逐篇完成对抗式 L4，重点挑战 current/legacy、责任归因、pipeline owner 与 cite 是否真的支持强断言，再 `audit-record PASS`。低于 first-build readiness 阈值时 CLI 应拒绝进入 full L4。
10. `wiki snapshot-commit --repo <id>`。

禁止先提交 baseline 再补正文；禁止为了覆盖率灌水；禁止仅因源码中还存在旧实现就把它写成当前主路径。
