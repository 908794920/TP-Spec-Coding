# -*- coding: utf-8 -*-
"""CLI surface for explicit TP-Spec HTML information cards."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import json
import os
import sys

# Only parser registration is loaded by normal CLI commands. Presentation
# implementations are imported on explicit use so their failure stays optional.


def _error_summary(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _resolve_inline_output(inline_output_arg: Optional[str]) -> Optional[str]:
    explicit = str(inline_output_arg or "").strip()
    if explicit:
        return explicit
    environment = str(os.environ.get("TP_SPEC_CARD_INLINE_OUTPUT") or "").strip()
    return environment or None


def render_display_outputs(
    snapshot: Dict[str, Any],
    output: Path,
    *,
    artifact_root: Optional[str] = None,
    inline_output_arg: Optional[str] = None,
    emit_offline_path: bool = True,
    emit_artifact_path: bool = True,
    result_stream=None,
    legacy_stream=None,
) -> Tuple[Path, Dict[str, Any]]:
    """Render all requested presentation artifacts and emit one stable result contract.

    Runtime facts are never read or mutated here.  Each host-facing artifact is
    best-effort after the canonical offline HTML succeeds.
    """
    from .render import artifact_output_path, render_card, render_inline_card

    stream = result_stream or sys.stdout
    legacy = legacy_stream or stream
    path = render_card(snapshot, output)
    if emit_offline_path:
        print(str(path), file=stream)

    result: Dict[str, Any] = {
        "schema": "tp-spec.card-display/v1",
        "card_type": str(snapshot.get("card_type") or ""),
        "offline_html": str(path),
        "web_artifact": None,
        "artifact": {"status": "failed", "error": None},
        "inline": {"requested": False, "status": "not_requested", "path": None, "error": None},
    }

    try:
        artifact = artifact_output_path(artifact_root)
        if artifact != path:
            artifact = render_card(snapshot, artifact)
        result["web_artifact"] = str(artifact)
        result["artifact"] = {"status": "generated", "error": None}
        if emit_artifact_path:
            print(f"WEB_ARTIFACT: {artifact}", file=stream)
    except Exception as exc:
        error = _error_summary(exc)
        result["artifact"] = {"status": "failed", "error": error}
        print(f"CARD_ARTIFACT_WARNING: {error}", file=sys.stderr)

    inline_output = _resolve_inline_output(inline_output_arg)
    if inline_output:
        result["inline"]["requested"] = True
        try:
            inline = render_inline_card(snapshot, inline_output)
            result["inline"].update({"status": "generated", "path": str(inline), "error": None})
            print(f"INLINE_VISUALIZATION: {inline}", file=legacy)
        except Exception as exc:
            error = _error_summary(exc)
            result["inline"].update({"status": "failed", "path": None, "error": error})
            print(f"CARD_INLINE_WARNING: {error}", file=sys.stderr)

    print("CARD_DISPLAY: " + json.dumps(result, ensure_ascii=False, separators=(",", ":")), file=stream)
    return path, result


def _emit(
    snapshot,
    output_arg: Optional[str],
    *,
    identifier: str = "",
    artifact_root: Optional[str] = None,
    inline_output_arg: Optional[str] = None,
) -> int:
    from .render import default_output_path

    output = Path(output_arg).expanduser().resolve(strict=False) if output_arg else default_output_path(snapshot["card_type"], identifier)
    render_display_outputs(
        snapshot,
        output,
        artifact_root=artifact_root,
        inline_output_arg=inline_output_arg,
    )
    return 0


def cmd_global(args) -> int:
    from .snapshot import build_global_snapshot

    snapshot = build_global_snapshot(home=args.home, installation_path=args.installation, registry_path=args.registry)
    return _emit(snapshot, args.output, artifact_root=args.artifact_root, inline_output_arg=args.inline_output)


def cmd_project(args) -> int:
    from .snapshot import build_project_snapshot

    snapshot = build_project_snapshot(args.root, registry_path=args.registry, installation_path=args.installation)
    identifier = str((snapshot.get("project") or {}).get("project_id") or "current-project")
    return _emit(
        snapshot,
        args.output,
        identifier=identifier,
        artifact_root=args.artifact_root or args.root,
        inline_output_arg=args.inline_output,
    )


def cmd_task(args) -> int:
    from .snapshot import build_task_snapshot

    snapshot = build_task_snapshot(args.task, db_path=args.db, registry_path=args.registry, base_root=args.base_root)
    identifier = str((snapshot.get("task") or {}).get("task_id") or "current-task")
    return _emit(
        snapshot,
        args.output,
        identifier=identifier,
        artifact_root=args.artifact_root,
        inline_output_arg=args.inline_output,
    )


def add_card_subparsers(subparsers) -> None:
    parser = subparsers.add_parser("card", help="Generate read-only offline HTML information cards")
    sub = parser.add_subparsers(dest="card_type", required=True)

    global_parser = sub.add_parser("global", help="Generate TP-Spec global configuration snapshot")
    global_parser.add_argument("--home", default=None, help="optional Home root for fixture/testing")
    global_parser.add_argument("--installation", default=None, help="installation.yaml path override")
    global_parser.add_argument("--registry", default=None, help="registry.local.json path override")
    global_parser.add_argument("--output", default=None, help="offline HTML output path")
    global_parser.add_argument("--artifact-root", default=None, help="workspace root for fixed .tp-spec/card/index.html Web Artifact")
    global_parser.add_argument("--inline-output", default=None, help="host visualization HTML fragment output path")
    global_parser.set_defaults(func=cmd_global)

    project_parser = sub.add_parser("project", help="Generate current project snapshot")
    project_parser.add_argument("--root", default=".", help="workspace root used for strict project resolution")
    project_parser.add_argument("--installation", default=None, help="installation.yaml path override")
    project_parser.add_argument("--registry", default=None, help="registry.local.json path override")
    project_parser.add_argument("--output", default=None, help="offline HTML output path")
    project_parser.add_argument("--artifact-root", default=None, help="override workspace root for fixed Web Artifact; defaults to --root")
    project_parser.add_argument("--inline-output", default=None, help="host visualization HTML fragment output path")
    project_parser.set_defaults(func=cmd_project)

    task_parser = sub.add_parser("task", help="Generate task progress snapshot; missing task_id stays an explicit empty state")
    task_parser.add_argument("--task", default=None, help="explicit task id; never guessed from recent tasks")
    task_parser.add_argument("--db", default=None, help="explicit Runtime database path")
    task_parser.add_argument("--registry", default=None, help="registry.local.json path override")
    task_parser.add_argument("--base-root", default=None, help="Base root used by workflow resolver")
    task_parser.add_argument("--output", default=None, help="offline HTML output path")
    task_parser.add_argument("--artifact-root", default=None, help="workspace root for fixed .tp-spec/card/index.html Web Artifact")
    task_parser.add_argument("--inline-output", default=None, help="host visualization HTML fragment output path")
    task_parser.set_defaults(func=cmd_task)
