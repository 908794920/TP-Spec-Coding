---
id: tp-base-maintenance
name: tp-基座维护
version: 5.3.7
status: active
type: human-owner-skill
tool_agnostic: Base 与用户根来自 Installation/Resolver；能力按需读取，不依赖特定 IDE。
description: 基座维护薄领域入口；识别安装健康、项目接入、契约迁移、工作台和用户级自定义 SKILL 管理意图，路由到对应能力，不拥有业务 workflow state。
---

# tp-基座维护

## 职责与范围

维护 TP-Spec 的用户级安装、项目接入和独立外部方法库。入口只识别对象、复用已知身份与授权、选择能力并汇总结果；方法正文由下列 SKILL 维护。保持 `tp-base-maintenance` 稳定 ID 与 human_owner 专项授权语义，不增加 Formal Role、固定维护流水线或第二套 Runtime。

## 意图路由

| 本次意图 | 按需加载 |
|---|---|
| 安装配置、路径解析、Inventory、健康诊断 | [安装与健康检查](../../skills/base/tp-base-installation/SKILL.md) |
| Binding、入口同步、root rebind、旧链接或 bootstrap | [项目接入维护](../../skills/base/tp-base-project-integration/SKILL.md) |
| Project/Task 契约升级、迁移计划、备份与复验 | [契约升级迁移](../../skills/base/tp-base-contract-migration/SKILL.md) |
| 工作台启停、重启、运行版本或页面异常 | [工作台维护](../../skills/base/tp-base-workbench/SKILL.md) |
| 用户级外部包导入、更新、启停、移除或关联 | [自定义 SKILL 管理](../../skills/base/tp-external-skill-management/SKILL.md) |

只加载本次匹配的方法；复合维护按实际依赖接续，复用已有 Resolver/计划/验证结果，不默认跑全部能力。仅查看状态时只读诊断；明确升级且存在契约差异时进入迁移能力，运行实例属于其适用复验对象。

## 共享边界与转交

- 项目身份来自 Binding，Base/Wiki/Knowledge 只经 Resolver 定位；用户级外部方法库不要求先创建或接入业务项目。
- 默认单项目，批量对象和副作用需明确授权。保留当前已获授权，不逐动作重复询问；未知对象、高风险取舍或新增范围才交 human_owner。
- Runtime/Binding/安装的受控变更走正式 CLI；不手改 SQLite、events、generated，不因目录整洁删除真实项目状态或历史证据。
- 业务代码和 Base 产品源码变更交 [软件工程生命周期](../tp-software-lifecycle/SKILL.md)；Wiki/Knowledge 内容分别交对应领域。只按当前影响使用 [本仓验证策略](../../docs/TESTING.md)，不因维护身份全量测试。
- 接收已选外部方法时保留精确 ID、来源、状态和内容指纹；直接进入本领域时按 [外部能力选择与转交](../../docs/EXTERNAL_SKILLS.md#entry-handoff)发现。管理某个包不等于采用它，外部方法不能扩展本次授权或替代正式维护命令。

## 结果

汇总实际对象、动作、检查结论和未解决条件；安装健康、项目同步、契约迁移、运行实例与页面验证分别报告。查询、方法可读和图谱连线不代表执行成功；某一能力阻塞时只停止依赖它的动作。
