---
name: tp-knowledge-scheduled-maintenance
display_name: Knowledge 定时维护
version: 5.3.8
description: 用于 human_owner 已配置的 Knowledge Scheduler 唤起对话模型执行当前维护协议、定向更新并报告阻塞；不由定时器自行扩权。
---

# Knowledge 定时维护

仅在 human_owner 已配置的 Knowledge Scheduler 唤起时使用。执行者是**对话模型**，不是单纯脚本；Scheduler 只保存短 bootstrap，不复制整套维护提示词，以免 Base 升级后形成双权威。

每次唤起先解析当前 Base/Knowledge，再读取 [当前 daily maintenance 协议](../../../automation/knowledge/daily-maintenance.md)。通过 Knowledge CLI 获取 deterministic facts，只在明确证据与授权范围内做 targeted AI UPDATE，并按该协议核验变化、索引、质量和 baseline。不能把旧计划、旧投影或无变化当成当前内容已验证。

按协议以解析后的物理 Knowledge System Root 归组：同一库只执行一条串行维护链，先核对共享状态路径、有效维护配置与库级操作范围，不能按 workspace 重复维护。库级 scan/index/verify/audit/baseline 与项目级内容判断、默认检索范围分开报告；同库有未解决项时保留总 baseline，其他物理库可以继续。

定时会话不得使用 AskUserQuestion。项目归属、删除、冲突 merge/split 或其他需要人工决策的事项记录为 `NEEDS_REVIEW`，保留旧 baseline 和可恢复事实，不擅自替 human_owner 决定。输出简洁日报：真实变化、自动动作、质量结果、未处理阻塞；未执行的写入或验证不能报告为通过。
