# Wiki 首次构建

适用条件：首次构建或全量重建一个 repo 的可信 Wiki baseline 时读取。

首次构建时，先把 Wiki-eligible source 按能力/子系统做**语义聚类**再设计文档拓扑；一个源码文件不等于一篇 Wiki。`quality.initial_build_effective_coverage_min` 是首次可信 baseline 的**就绪阈值**（默认 0.95），与日常 `effective_wiki_coverage_warn` 分离：低于阈值必须继续处理 uncovered，不能把“verify 没有 coverage ERROR”解释成“半成品可以结单”。对剩余 uncovered 逐项判断“补进现有/聚合 Wiki”还是“确实应排除并给出真实 reason”，不得为了 100% 调分母。
