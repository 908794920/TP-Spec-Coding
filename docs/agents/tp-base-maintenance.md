# tp-base-maintenance

## 适用场景

用于 Base 安装配置、路径解析、项目同步、迁移、doctor、版本和发布维护。已有安装优先检查现状并做最小修复，不重复初始化。

## 执行入口

机器契约与能力 ID 由 Role Catalog 和 Agent `SKILL.md` 定义；配置命令应先检查当前 installation/project binding，再决定是否写入。

## 能力导航

<!-- TP-SPEC:AGENT-TOPOLOGY-BEGIN -->
<!-- 由 scripts/check_document_navigation.py --write 根据 governance/role-catalog.yaml 生成。不要手工编辑本区块。 -->

- **Agent**：tp-基座维护 · `tp-base-maintenance`
- **执行契约**：[`agents/tp-base-maintenance/SKILL.md`](../../agents/tp-base-maintenance/SKILL.md)
- **能力 ID**：`base.configure`、`base.migrate`、`base.doctor`、`base.repair`

<!-- TP-SPEC:AGENT-TOPOLOGY-END -->

## 相关文档

- [Getting Started](../GETTING_STARTED.md)
- [文档地图](../README.md)
- [自动化总入口](../../automation/README.md)

## 边界

不得猜测机器路径，不得未经确认覆盖已有绑定。Base 升级不应要求用户重新装修业务项目；新增默认能力应尽量由 Base 自身解析和配置兼容处理。
