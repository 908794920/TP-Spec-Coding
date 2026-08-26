# -*- coding: utf-8 -*-
"""CLI surface for explicit TP-Spec HTML information cards."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import sys

from .render import artifact_output_path, default_output_path, render_card, render_inline_card
from .snapshot import build_global_snapshot, build_project_snapshot, build_task_snapshot


def _emit(
    snapshot,
    output_arg: Optional[str],
    *,
    identifier: str = "",
    artifact_root: Optional[str] = None,
    inline_output_arg: Optional[str] = None,
) -> int:
    output = Path(output_arg).expanduser().resolve(strict=False) if output_arg else default_output_path(snapshot["card_type"], identifier)
    path = render_card(snapshot, output)
    print(str(path))

    try:
        artifact = artifact_output_path(artifact_root)
        if artifact != path:
            artifact = render_card(snapshot, artifact)
        print(f"WEB_ARTIFACT: {artifact}")
    except Exception as exc:
        # The fixed Web Artifact is a host-facing convenience. Offline preview
        # remains the fallback and an artifact failure must not erase it.
        print(f"CARD_ARTIFACT_WARNING: {type(exc).__name__}: {exc}", file=sys.stderr)

    if inline_output_arg:
        try:
            inline = render_inline_card(snapshot, inline_output_arg)
            print(f"INLINE_VISUALIZATION: {inline}")
        except Exception as exc:
            # Conversation rendering is host-facing and best-effort. Keep the
            # independently generated offline and Web Artifact outputs intact.
            print(f"CARD_INLINE_WARNING: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


def cmd_global(args) -> int:
    snapshot = build_global_snapshot(home=args.home, installation_path=args.installation, registry_path=args.registry)
    return _emit(snapshot, args.output, artifact_root=args.artifact_root, inline_output_arg=args.inline_output)


def cmd_project(args) -> int:
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
    global_parser.add_argument("--artifact-root", default=None, help="workspace root for fixed .tp-spec-preview/card/index.html Web Artifact")
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
    task_parser.add_argument("--artifact-root", default=None, help="workspace root for fixed .tp-spec-preview/card/index.html Web Artifact")
    task_parser.add_argument("--inline-output", default=None, help="host visualization HTML fragment output path")
    task_parser.set_defaults(func=cmd_task)
