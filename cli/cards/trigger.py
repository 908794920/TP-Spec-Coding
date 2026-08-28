# -*- coding: utf-8 -*-
"""Best-effort post-success refresh hook for formal Runtime facts."""
from __future__ import annotations

from typing import Any, Optional
import sys

from .commands import render_display_outputs
from .render import default_output_path
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


def _legacy_inline_stream(args: Any):
    """Preserve the old stdout marker only where stdout is human text.

    Record-first task mutations emit JSON by default and workflow confirmation
    can emit JSON/YAML, so appending an inline marker there would corrupt the
    command's primary machine-readable payload.  Task creation and work-session
    commands historically emit plain status text and keep the legacy stdout
    marker for host compatibility.
    """
    group = str(getattr(args, "group", "") or "")
    subcommand = str(getattr(args, "subcommand", "") or "")
    if group == "task" and subcommand == "create":
        return sys.stdout
    if group == "work" and subcommand in _WORK_STEPS:
        return sys.stdout
    return sys.stderr


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
    rendered, _ = render_display_outputs(
        snapshot,
        output,
        emit_offline_path=False,
        emit_artifact_path=False,
        # Runtime command stdout belongs to the command itself.  Preview refresh
        # is a best-effort side channel, so its display contract must never make
        # JSON-shaped or otherwise machine-readable command output unparsable.
        result_stream=sys.stderr,
        # Keep the legacy inline marker on stdout for the Runtime commands whose
        # primary output is plain human text; machine-readable commands use the
        # same stderr side channel as CARD_DISPLAY.
        legacy_stream=_legacy_inline_stream(args),
    )
    return str(rendered)
