# -*- coding: utf-8 -*-
"""Best-effort post-success refresh hook for formal Runtime facts."""
from __future__ import annotations

import os
import sys
from typing import Any, Optional

from .render import artifact_output_path, default_output_path, render_card, render_inline_card
from .snapshot import build_task_snapshot

_TASK_STEPS = {"create", "checkpoint", "block", "resume", "verify", "delivery-converge", "complete"}
_WORK_STEPS = {"start", "end"}
_WORKFLOW_STEPS = {"confirm"}


def should_refresh_task_card(args: Any) -> bool:
    group = str(getattr(args, "group", "") or "")
    subcommand = str(getattr(args, "subcommand", "") or "")
    if group == "task":
        return subcommand in _TASK_STEPS
    if group == "work":
        return subcommand in _WORK_STEPS
    if group == "workflow":
        return subcommand in _WORKFLOW_STEPS
    return False


def _task_id(args: Any) -> str:
    if str(getattr(args, "group", "") or "") == "task" and str(getattr(args, "subcommand", "") or "") == "create":
        return str(getattr(args, "id", "") or "").strip()
    return str(getattr(args, "task", "") or "").strip()


def refresh_after_success(args: Any) -> Optional[str]:
    if not should_refresh_task_card(args):
        return None
    task_id = _task_id(args)
    if not task_id:
        return None
    snapshot = build_task_snapshot(
        task_id,
        db_path=getattr(args, "db", None),
        base_root=getattr(args, "base_root", None),
    )
    output = default_output_path("active_task", task_id)
    rendered = render_card(snapshot, output)
    artifact = artifact_output_path()
    try:
        if artifact != rendered:
            render_card(snapshot, artifact)
    except Exception as exc:
        print(f"CARD_ARTIFACT_WARNING: {type(exc).__name__}: {exc}", file=sys.stderr)

    inline_output = str(os.environ.get("TP_SPEC_CARD_INLINE_OUTPUT") or "").strip()
    if inline_output:
        try:
            inline = render_inline_card(snapshot, inline_output)
            print(f"INLINE_VISUALIZATION: {inline}")
        except Exception as exc:
            print(f"CARD_INLINE_WARNING: {type(exc).__name__}: {exc}", file=sys.stderr)
    return str(rendered)
