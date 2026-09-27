---
name: tp-base-installation
display_name: 安装与健康检查
version: 5.3.5
description: 用于 TP-Spec 用户级安装配置、Base/Wiki/Knowledge 路径解析、Workspace Inventory 和安装健康诊断；项目接入与契约升级分别交对应能力。
---

# 安装与健康检查

## 对象与定位

维护用户 Installation、Workspace Inventory 和 Resolver。纯本机安装诊断先用 `base installation-doctor`；有项目上下文时，再从当前 CLI 的 `base resolve --workspace-root <workspace>` 取得实际 Base、安装声明、项目身份和内容系统 scope。不为安装诊断创建项目，也不沿用历史绝对路径或项目 Junction。

用户根由 `environment.user_tp_spec_root()` 解析（`TP_SPEC_USER_ROOT` 或默认 `~/.tp-spec`）；`installation.yaml` 保存 Base/Wiki/Knowledge 系统根，`workspaces.yaml` 保存获准维护对象。它们是本机配置，不复制到项目 README/AGENTS。Knowledge 默认仍为当前项目 + shared；用户明确要求才检索全局。

## 诊断与修复

1. 使用 `base installation-doctor` 检查 VERSION、关键文件、安装配置、启动器和 Registry 位置；`base resolve` 区分磁盘 Base、实际执行 Base、Binding 和 Runtime contract。
2. 需要工作区清单时运行只读 `base inventory`，优先复用已有 Registry；只有明确的发现范围才增加 `--search-root`，不扫全盘。
3. 核对 Knowledge 使用统计健康时，另查 `knowledge doctor` / `knowledge index status` 的 `usage_collection` 就绪状态和警告；VERSION、总体 doctor PASS 或索引可搜索都不能单独证明采集 schema 已就绪。健康检查不要求真实搜索或读取来凑计数。
4. 若采集状态为旧契约、缺少读取记录结构或带采集警告，报告未就绪范围，并按本次授权转入 [Knowledge 使用说明](../../../docs/KNOWLEDGE_USAGE.md) 所述显式升级路径。未获授权不得自动执行 `index update`、DDL 或迁移。
5. 用户要求创建、更新或修复安装配置时，先查看 `base configure --help`，只写已明确的系统根。合法旧配置中未提供的 root 保留；损坏配置需取得全量 root 后重建，不能猜新路径。
6. 旧用户级安装状态用 `base installation-migrate` 先出计划，确认对象和已有授权覆盖后才 `--apply`；清单写入使用 `base inventory --write`。内容正文交 Wiki/Knowledge 能力。
7. 修复后重跑受影响的安装诊断和 Resolver。项目 Binding、root rebind 或入口漂移转 [项目接入维护](../tp-base-project-integration/SKILL.md)；旧 Project/Task contract 转 [契约升级迁移](../tp-base-contract-migration/SKILL.md)。

## 结果

报告实际安装根、版本、范围、诊断和已变更配置；健康语义使用 `HEALTHY / SYNC_AVAILABLE / SYNC_REQUIRED / REPAIR_REQUIRED / UNSAFE`，同时保留 CLI 的实际状态和错误。缓存错误不能包装成 Runtime 已丢失，缺失可选 Junction 也不是故障。

发现“新 VERSION、旧校验规则”或正在运行的工作台时，交 [工作台维护](../tp-base-workbench/SKILL.md)核对运行实例，磁盘诊断不代替运行或页面验收。
