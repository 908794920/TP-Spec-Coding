---
name: tp-base-workbench
display_name: 工作台维护
version: 5.3.6
description: 用于本地工作台启动、停止、重启、实际源码与运行版本核对，以及升级后旧进程、接口或页面异常；不承担工作台功能开发。
---

# 工作台维护

## 定位与诊断

按 [本地工作台](../../../docs/WORKBENCH.md#windows-轻量管理入口)识别实际启动目录与管理方式。项目 Resolver 的安装声明、`/api/health` 的 `source_root/instance_id/python_executable/user_root`、正在监听的进程及启动时间分别核验，不按端口或旧目录猜服务归属。

`health.version` 和页面顶部可能实时读取磁盘 VERSION；Python 模块在旧进程中仍可保留升级前规则。出现新 `catalog_version` 被旧 `supported_versions` 拒绝时，比较同一源码的新 CLI 读取结果与现有 `/api/global`、进程启动时间和源码变化，再判断旧实例还是代码缺陷。重启恢复不能推广为所有报错都靠重启解决。

## 运行管理

- Windows 受管实例：使用确认源码根中的 `node ui/workbench-manager.mjs start|stop|restart` 或 `ui` 下相应 `.cmd`。复用其私有实例身份校验，不按进程名或端口批量杀服务。
- 前台 `npm run dev` 实例：在拥有它的终端停止或使用宿主的原会话控制；不能证明归属时交用户处理，不让受管入口抢占端口。
- 仅准备实际需要的依赖；日常启动和重启不自动安装、升级或全量测试。更改用户根环境变量需用同一环境重新启动相应进程。
- 修改 Base 代码属于软件工程领域。本能力只处理已授权的运行维护，不同步开发源码到安装目录，不把打开页面当成部署授权。

## 完成判定

1. 管理命令确实成功，所选实例身份与源码根符合本次目标；重启时旧实例已结束、新实例可读。
2. 读取 `/api/health` 和受影响 API。处理拓扑问题时检查 `/api/global` 的 `read.completeness`、`problems`、`skill_topology`；不得仅以 HTTP 200 或 VERSION 为成功。
3. 在真实浏览器重读受影响页面，确认原错误消失、目录/正文和相关交互正常；若页面仅显示缓存旧结果，不能报告恢复。保留实际截图或明确页面未验。

普通维护命令不自动打开工作台；仅当用户要求页面或当前问题依赖该实例时执行。报告源码、实例、接口、页面四个层面的实际结果，缺一项就说明对应限制。
