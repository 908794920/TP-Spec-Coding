# Wiki Quality Audit — Canonical AI Protocol

用于人工怀疑 Wiki 质量或大批更新后的独立审计。

1. 运行 `wiki manifest-refresh`（只刷新机器事实，不改变正文语义）。
2. 运行 `wiki verify`，记录全部 L1/L2/L3 真实结果。
3. 运行 `wiki coverage`，重点复核 Effective Wiki Coverage 的 eligible/covered/uncovered、direct citation/semantic-only covered 文件数与 exclusion reason；同时观察 dependency 注水、citation line coverage、scanner-wide source dependency coverage、stale topology。
4. 执行 `wiki audit --full --repo <id>` 获取确定性**全仓 mandatory scope**；逐篇深读计划内全部 durable 文档并回到 source 核验 cite 与正文结论。`--full` 不得用抽样替代。
5. 发现问题只修 Wiki，不放宽质量门。
6. 报告必须明确本次 `--full` 的实际逐篇审计范围以及未跑项；未逐篇完成计划范围不得写 PASS。
