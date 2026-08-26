# -*- coding: utf-8 -*-
"""Self-contained offline HTML renderer for TP-Spec information cards."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import hashlib
import json
import os
import re
import tempfile

from cli import environment

_TEMPLATE = Path(__file__).resolve().parent / "assets" / "card.html"
_INLINE_MAX_BYTES = 1_000_000
_INLINE_TRUNCATION_NOTICE = {
    "code": "INLINE_CONTENT_TRUNCATED",
    "severity": "warning",
    "message": "会话卡片内容过多，已截断展示；完整内容请查看 Web Artifact 或离线 HTML。",
}
_SENSITIVE_KEY = re.compile(r"(?:password|passwd|token|secret|api[_-]?key|access[_-]?key|private[_-]?key|credential|authorization|cookie)", re.I)
_ALLOWED_TOP = {
    "global_config": {"card_type", "title", "generated_at", "health", "version", "user_root", "base", "wiki", "knowledge", "workspace", "resolver", "registry", "autonomy", "registered_projects", "problems"},
    "current_project": {"card_type", "title", "generated_at", "health", "project", "wiki", "knowledge", "registry", "task_statistics", "in_progress_tasks", "completed_tasks", "summary", "problems"},
    "active_task": {"card_type", "title", "generated_at", "health", "task", "workflow", "latest_checkpoint", "blockers", "verification", "evidence", "timeline", "summary", "problems"},
}


def _strip_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _strip_sensitive(v) for k, v in value.items() if not _SENSITIVE_KEY.search(str(k))}
    if isinstance(value, list):
        return [_strip_sensitive(v) for v in value]
    if isinstance(value, tuple):
        return [_strip_sensitive(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def sanitize_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    card_type = str(snapshot.get("card_type") or "")
    allowed = _ALLOWED_TOP.get(card_type)
    if not allowed:
        raise ValueError(f"unsupported card_type: {card_type!r}")
    return _strip_sensitive({key: snapshot.get(key) for key in allowed if key in snapshot})


def _safe_name(value: str, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip(".-")
    return text or fallback


def _output_root() -> Path:
    explicit = os.environ.get("TP_SPEC_CARD_OUTPUT_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve(strict=False)
    user_root = environment.user_tp_spec_root()
    if user_root.exists():
        return user_root / "previews" / "cards"
    return Path(tempfile.gettempdir()).resolve(strict=False) / "tp-spec-cards"


def artifact_output_path(root: "str | Path | None" = None) -> Path:
    """Return the fixed project-local Web Artifact entrypoint.

    This path is presentation-only. It never participates in project identity
    resolution or Runtime truth. Explicit roots win, then the optional test/host
    override, then the current working directory.
    """
    explicit = os.environ.get("TP_SPEC_CARD_ARTIFACT_ROOT")
    base = Path(root if root is not None else (explicit or Path.cwd())).expanduser().resolve(strict=False)
    return base / ".tp-spec-preview" / "card" / "index.html"


def default_output_path(card_type: str, identifier: Optional[str] = None) -> Path:
    root = _output_root()
    if card_type == "global_config":
        return root / "global-config.html"
    if card_type == "current_project":
        return root / "projects" / f"{_safe_name(identifier or '', 'current-project')}.html"
    if card_type == "active_task":
        return root / "tasks" / f"{_safe_name(identifier or '', 'current-task')}.html"
    raise ValueError(f"unsupported card_type: {card_type!r}")


def _encode_payload(clean: Dict[str, Any]) -> str:
    payload = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
    # Keep application/json inert even when values contain HTML/script terminators.
    return payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _snapshot_payload(snapshot: Dict[str, Any]) -> str:
    return _encode_payload(sanitize_snapshot(snapshot))


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    suffix = "…"
    room = max(0, max_bytes - len(suffix.encode("utf-8")))
    return encoded[:room].decode("utf-8", errors="ignore") + suffix


def _compact_inline_value(value: Any, *, max_string_bytes: int, max_collection_items: int, depth: int = 0) -> Any:
    if isinstance(value, dict):
        items = list(value.items())
        if depth > 0:
            items = items[:max_collection_items]
        return {
            _truncate_utf8(str(key), 256): _compact_inline_value(
                item,
                max_string_bytes=max_string_bytes,
                max_collection_items=max_collection_items,
                depth=depth + 1,
            )
            for key, item in items
        }
    if isinstance(value, (list, tuple)):
        return [
            _compact_inline_value(
                item,
                max_string_bytes=max_string_bytes,
                max_collection_items=max_collection_items,
                depth=depth + 1,
            )
            for item in list(value)[:max_collection_items]
        ]
    if isinstance(value, str):
        return _truncate_utf8(value, max_string_bytes)
    return value


def _write_atomic(output: "str | Path", content: str) -> Path:
    target = Path(output).expanduser().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, target)
    return target


def _template_parts(template: str) -> tuple[str, str, str]:
    style_start = template.index("<style>") + len("<style>")
    style_end = template.index("</style>", style_start)
    body_start = template.index("<body>") + len("<body>")
    data_start = template.index('<script id="card-data"', body_start)
    script_start = template.index("<script>", data_start) + len("<script>")
    script_end = template.index("</script>", script_start)
    return template[style_start:style_end].strip(), template[body_start:data_start].strip(), template[script_start:script_end].strip()


def _inline_style(style: str) -> str:
    scoped = style.replace(":root {", ":host {", 1)
    scoped = scoped.replace("  color-scheme: dark;\n", "")
    scoped = re.sub(r"\nhtml, body \{[^}]*\}\n", "\n", scoped, count=1)
    scoped = re.sub(r"\nbody \{.*?\n\}\n", "\n", scoped, count=1, flags=re.S)
    scoped = scoped.replace("height: 100%; ", "")
    scoped = scoped.replace("min-height: 0; ", "")
    scoped = scoped.replace("overflow-y: auto; ", "")
    scoped = scoped.replace("position: sticky; ", "")
    scoped = scoped.replace("top: 0; ", "")
    scoped = scoped.replace("z-index: 10; ", "")
    return scoped + """
:host {
  display: block;
  color: var(--foreground);
  --tp-bg: transparent;
  --tp-panel: var(--background);
  --tp-panel2: var(--card);
  --tp-panel3: var(--muted);
  --tp-hover: var(--accent);
  --tp-border: var(--border);
  --tp-border-strong: var(--border);
  --tp-text: var(--foreground);
  --tp-secondary: var(--muted-foreground);
  --tp-muted: var(--muted-foreground);
  --tp-blue: var(--blue);
  --tp-green: var(--green);
  --tp-green-soft: color-mix(in srgb, var(--green) 12%, transparent);
  --tp-yellow: var(--yellow);
  --tp-red: var(--red);
  --tp-gray: var(--muted-foreground);
  --tp-shadow: none;
}
.page { height: auto; margin: 0; padding: 0; }
.grid { overflow: visible; }
.card-nav { position: static; }
"""


def _inline_script(script: str, root_id: str) -> str:
    transformed = script.replace(
        "const data = JSON.parse(document.getElementById('card-data').textContent || '{}');",
        "const data = JSON.parse(cardRoot.getElementById('card-data').textContent || '{}');",
    )
    transformed = transformed.replace(
        "const app = document.getElementById('app');",
        "const app = cardRoot.getElementById('app');",
    )
    transformed = transformed.replace("document.body.appendChild(textarea);", "cardRoot.appendChild(textarea);")
    transformed = transformed.replace("document.getElementById('title')", "cardRoot.getElementById('title')")
    transformed = transformed.replace("document.getElementById('meta')", "cardRoot.getElementById('meta')")
    return f"""(() => {{
'use strict';
const host = document.getElementById('{root_id}');
if (!host || host.shadowRoot) return;
const template = host.querySelector('template');
if (!template) return;
const cardRoot = host.attachShadow({{mode: 'open'}});
cardRoot.appendChild(template.content.cloneNode(true));
template.remove();
{transformed}
}})();"""


def _build_inline_fragment(template: str, target: Path, clean: Dict[str, Any]) -> str:
    style, markup, script = _template_parts(template)
    payload = _encode_payload(clean)
    digest_source = f"{target}\0{payload}".encode("utf-8")
    root_id = f"tp-spec-card-{hashlib.sha256(digest_source).hexdigest()[:12]}"
    return f"""<div id="{root_id}">
  <template>
    <style>
{_inline_style(style)}
    </style>
{markup}
    <script id="card-data" type="application/json">{payload}</script>
  </template>
</div>
<script>
{_inline_script(script, root_id)}
</script>
"""


def render_card(snapshot: Dict[str, Any], output: "str | Path") -> Path:
    template = _TEMPLATE.read_text(encoding="utf-8")
    payload = _snapshot_payload(snapshot)
    html = template.replace("__TP_SPEC_CARD_DATA__", payload)
    return _write_atomic(output, html)


def render_inline_card(snapshot: Dict[str, Any], output: "str | Path") -> Path:
    """Render a host-ingestible HTML fragment for in-conversation display."""
    target = Path(output).expanduser().resolve(strict=False)
    template = _TEMPLATE.read_text(encoding="utf-8")
    clean = sanitize_snapshot(snapshot)
    fragment = _build_inline_fragment(template, target, clean)
    if len(fragment.encode("utf-8")) < _INLINE_MAX_BYTES:
        return _write_atomic(target, fragment)

    for max_string_bytes, max_collection_items in (
        (16_384, 200),
        (8_192, 100),
        (4_096, 50),
        (2_048, 25),
        (1_024, 12),
        (512, 6),
    ):
        projected = _compact_inline_value(
            clean,
            max_string_bytes=max_string_bytes,
            max_collection_items=max_collection_items,
        )
        projected["problems"] = [_INLINE_TRUNCATION_NOTICE, *(projected.get("problems") or [])]
        fragment = _build_inline_fragment(template, target, projected)
        if len(fragment.encode("utf-8")) < _INLINE_MAX_BYTES:
            return _write_atomic(target, fragment)

    raise ValueError("inline card cannot be reduced below the 1 MB host limit")
