#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TP-Spec-Coding V5.2.0 CLI 统一入口。

注册当前活动命令与显式兼容/恢复工具；普通研发角色以 Record-first task API 为日常写入口，
Wiki 子系统通过独立 ``wiki`` 命令组提供代码理解维护能力。

调用方式：
- 脚本式：python cli/main.py project init --id demo ...
- 包式：  python -m cli.main project init --id demo ...
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

# 支持脚本式调用：python cli/main.py ...
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import project_cmd
from cli import base_maintenance
from cli import task_cmd
from cli import work_session_cmd
from cli import rework_cmd
from cli import workitem_cmd
from cli import event_cmd
from cli import projection_cmd
from cli import report_cmd
from cli import config_cmd
from cli import commit_cmd
from cli import receipt_cmd
from cli import review_preflight
from cli import lossless_summary
from cli import snapshot_cmd
from cli import rollback_cmd
from cli import structured_refs
from cli import reconcile_cmd
from cli import review_cmd
from cli import orchestration_cmd
from cli.wiki import commands as wiki_commands
from cli.knowledge import commands as knowledge_commands
from cli.version import active_version
from cli.commit_errors import BaselineBlockedError
from cli.encoding_guard import EncodingValidationError


def _cmd_not_implemented_m0(args) -> int:
    group = getattr(args, "group", None) or "unknown"
    print(f"not implemented in M0: {group}", file=sys.stderr)
    return 255


def _add_stub_group(subparsers, name: str) -> None:
    """为 M0 未实现的命令组注册一个占位 subparser，M1-M4 替换。

    用 argparse.REMAINDER 捕获任意剩余参数（含 --option），避免 stub 报错。
    """
    p = subparsers.add_parser(name)
    p.add_argument("rest", nargs=argparse.REMAINDER, help="subcommand args (not implemented in M0)")
    p.set_defaults(func=_cmd_not_implemented_m0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-work",
        description=f"TP-Spec-Coding V{active_version()} CLI",
    )
    subparsers = parser.add_subparsers(dest="group", required=True)

    # V5.2.0 Base convergence：安装根、Workspace Inventory、项目绑定与 Junction 收敛。
    base_maintenance.add_base_subparsers(subparsers)

    # project 组（M0 实现）
    project_parser = subparsers.add_parser("project", help="Project management")
    project_cmd.add_project_subparsers(project_parser)

    # db 组（M0 实现）
    db_parser = subparsers.add_parser("db", help="Database operations")
    project_cmd.add_db_subparsers(db_parser)

    # task 组（M1 实现）
    task_parser = subparsers.add_parser("task", help="Task management")
    task_cmd.add_task_subparsers(task_parser)

    # work 组（M2 实现）
    work_parser = subparsers.add_parser("work", help="Work session management")
    work_session_cmd.add_work_subparsers(work_parser)

    # rework 组（M2 实现）
    rework_parser = subparsers.add_parser("rework", help="Rework management")
    rework_cmd.add_rework_subparsers(rework_parser)

    # workitem 组（M2 实现）
    workitem_parser = subparsers.add_parser("workitem", help="Work item management")
    workitem_cmd.add_workitem_subparsers(workitem_parser)

    # event 组（M3 实现）
    event_parser = subparsers.add_parser("event", help="Event management")
    event_cmd.add_event_subparsers(event_parser)

    # projection 组（M3 实现）
    projection_parser = subparsers.add_parser("projection", help="Projection management")
    projection_cmd.add_projection_subparsers(projection_parser)

    # report 组（M4 实现）
    report_parser = subparsers.add_parser("report", help="Report management")
    report_cmd.add_report_subparsers(report_parser)

    # config 组（M5-B 实现）
    config_parser = subparsers.add_parser("config", help="Config management")
    config_cmd.add_config_subparsers(config_parser)

    # V5.2.0 legacy commit compatibility/recovery surface; daily roles use task record-first APIs.
    commit_cmd.add_commit_subparsers(subparsers)

    # 高风险动作收据（不改变状态）
    receipt_cmd.add_receipt_subparsers(subparsers)

    # V5.2.0 C1 审查预检（不改变状态；anchor_check 确定性校验 + 封存安全）
    review_preflight.add_review_preflight_subparsers(subparsers)

    # V5.2.0 B-14 仅无损的可回溯摘要（不改变状态；分类 + sentinel 保护 + 可逆折叠）
    lossless_summary.add_lossless_summary_subparsers(subparsers)

    # V5.2.0 B-18 cutover 快照/回滚（非破坏性工具；回滚默认 dry-run 零写入）
    snapshot_cmd.add_cutover_snapshot_subparsers(subparsers)
    rollback_cmd.add_cutover_rollback_subparsers(subparsers)

    # V5.2.0 B-12 结构化引用校验（纯确定性，不依赖其他模块）
    structured_refs.add_refs_validate_subparsers(subparsers)

    # V5.2.0 A-04 正式 reconciliation（以 DB 为权威重建投影，追加 RECONCILIATION 事件）
    reconcile_cmd.add_reconcile_subparsers(subparsers)

    # V5.2.0 Hardening：正式架构评审命令（tp-architecture-review 写入 REVIEW_COMPLETED/ARCHITECTURE）
    review_cmd.add_review_subparsers(subparsers)

    # V5.2.0 Workflow Orchestrator：只读 L0-L3 路由与契约诊断。
    orchestration_cmd.add_workflow_subparsers(subparsers)

    # V5.2.0 Wiki 标准化：代码理解层的确定性扫描/规划/质量门/基线提交。
    wiki_commands.add_wiki_subparsers(subparsers)

    # V5.2.0 Knowledge 标准化：长期知识、证据、FTS 投影、外部接入与定时维护。
    knowledge_commands.add_knowledge_subparsers(subparsers)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    try:
        return int(func(args) or 0)
    except SystemExit:
        raise
    except BaselineBlockedError as e:
        # V5.2.0 A-06：基座阻塞标准语义；业务角色必须停止任务，不得自行修复基座。
        print(f"BASELINE_BLOCKED: {e}", file=sys.stderr)
        return 1
    except EncodingValidationError as e:
        # V5.2.0 A-05：UTF-8 输入拒绝；数据库与投影必须零变化。
        print(f"ENCODING_VALIDATION_FAILED: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
