#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

OLD_ROLE_IDS = (
    "tp-requirement-analysis",
    "tp-product-design",
    "tp-architecture-design",
    "tp-architecture-review",
    "tp-development-engineering",
    "tp-verification-engineering",
    "tp-delivery-convergence",
)

_TEXT_EXTENSIONS = {
    ".py", ".ps1", ".md", ".yaml", ".yml", ".json", ".toml", ".txt", ".ini", ".cfg", ".sh",
}


@dataclass(frozen=True)
class RoleReference:
    path: str
    line: int
    old_role_id: str
    text: str
    classification: str


def _git_tracked(root: Path) -> list[Path]:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "-z"], stderr=subprocess.DEVNULL
        )
        rels = [p for p in out.decode("utf-8", errors="replace").split("\0") if p]
        return [root / p for p in rels]
    except Exception:
        return [p for p in root.rglob("*") if p.is_file()]


def _is_text_candidate(path: Path) -> bool:
    return path.suffix.lower() in _TEXT_EXTENSIONS or path.name in {"VERSION", "manifest.sha256"}


def classify_reference(path: str) -> str:
    p = path.replace("\\", "/")
    if p == "CHANGELOG.md" or p.startswith("docs/history/"):
        return "DOC_HISTORY"
    if p.startswith("cli/migrations/") or p.startswith("migrations/") or p.startswith("scripts/migration/"):
        return "MIGRATION_ONLY"
    if p.startswith("tests/fixtures/history/") or p.startswith("scripts/tests/fixtures/history/"):
        return "FIXTURE"
    if p.startswith("tests/migration/") or p.startswith("scripts/tests/migration/"):
        return "MIGRATION_TEST"
    if p.startswith("scripts/tests/") or p.startswith("tests/"):
        return "TEST"
    if p.startswith("governance/") or p == "governance/role-catalog.yaml":
        return "ACTIVE_GOVERNANCE"
    if p.startswith("agents/") or p.startswith("skills/"):
        return "ACTIVE_GOVERNANCE"
    if p.startswith("cli/"):
        return "ACTIVE_CLI"
    if p.startswith("scripts/"):
        return "ACTIVE_CLI"
    if p.startswith("docs/") or p in {"README.md", "CONTRIBUTING.md", "SECURITY.md"}:
        return "DOC_CURRENT"
    return "ACTIVE_RUNTIME"




LEGACY_TOKENS = (
    "legacy_workflow",
    "LEGACY_STATE_OWNERS",
    "LEGACY_TRANSITIONS",
    "transition_service",
)

def scan_legacy_dependencies(root: Path) -> list[dict]:
    root = root.resolve()
    rows: list[dict] = []
    for path in sorted(_git_tracked(root), key=lambda p: p.as_posix()):
        if not path.is_file() or not _is_text_candidate(path):
            continue
        try:
            content = path.read_text(encoding="utf-8-sig")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.resolve().relative_to(root).as_posix()
        for lineno, line in enumerate(content.splitlines(), start=1):
            hits = [token for token in LEGACY_TOKENS if token in line]
            if hits:
                rows.append({
                    "path": rel,
                    "line": lineno,
                    "tokens": hits,
                    "text": line.strip()[:500],
                    "classification": classify_reference(rel),
                })
    return rows

def scan_role_references(root: Path) -> list[RoleReference]:
    root = root.resolve()
    refs: list[RoleReference] = []
    for path in sorted(_git_tracked(root), key=lambda p: p.as_posix()):
        if not path.is_file() or not _is_text_candidate(path):
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.resolve().relative_to(root).as_posix()
        classification = classify_reference(rel)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for role_id in OLD_ROLE_IDS:
                if role_id in line:
                    refs.append(RoleReference(rel, lineno, role_id, line.strip()[:500], classification))
    return sorted(refs, key=lambda r: (r.path, r.line, r.old_role_id, r.text))


def report_payload(root: Path, refs: Iterable[RoleReference]) -> dict:
    rows = [asdict(r) for r in refs]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    return {
        "schema": "tp-spec.role-reference-inventory/v1",
        "root": str(root.resolve()),
        "old_role_ids": list(OLD_ROLE_IDS),
        "count": len(rows),
        "classification_counts": dict(sorted(counts.items())),
        "references": rows,
    }


def _markdown(payload: dict) -> str:
    lines = [
        "# V5.2.3 Role Reference Inventory",
        "",
        f"Total references: **{payload['count']}**",
        "",
        "| Classification | Count |",
        "|---|---:|",
    ]
    for key, value in payload["classification_counts"].items():
        lines.append(f"| `{key}` | {value} |")
    lines += ["", "| Path | Line | Old role | Class |", "|---|---:|---|---|"]
    for row in payload["references"]:
        lines.append(
            f"| `{row['path']}` | {row['line']} | `{row['old_role_id']}` | `{row['classification']}` |"
        )
    return "\n".join(lines) + "\n"


def _legacy_call_graph(refs: list[RoleReference], legacy_rows: list[dict]) -> str:
    lines = ["# V5.2.3 Legacy Call Graph", "", "Active references that require split/migrate/retire:", ""]
    seen: set[tuple[str, int]] = set()
    for row in legacy_rows:
        if row["classification"] not in {"ACTIVE_CLI", "ACTIVE_RUNTIME", "ACTIVE_GOVERNANCE"}:
            continue
        key = (row["path"], row["line"])
        if key not in seen:
            seen.add(key)
            lines.append(f"- `{row['path']}:{row['line']}` — `{row['text']}`")
    if len(lines) == 4:
        lines.append("- No active legacy dependency found.")
    lines.extend([
        "",
        "Known direct active imports requiring explicit migration:",
        "- `cli/config_loader.py` → `LEGACY_STATE_OWNERS`",
        "- `cli/workflow_loader.py` → `LEGACY_STATE_OWNERS`, `LEGACY_TRANSITIONS`",
        "- `cli/commit_cmd.py` / `cli/event_cmd.py` / `cli/review_cmd.py` / validators → legacy transition helpers",
        "",
    ])
    return "\n".join(lines)


_DEFAULT_ALLOW_PREFIXES = (
    "cli/migrations/",
    "migrations/",
    "scripts/migration/",
    "tests/migration/",
    "scripts/tests/migration/",
    "scripts/tests/fixtures/history/",
    "tests/fixtures/history/",
    "docs/history/",
)


def no_tail_violations(refs: Iterable[RoleReference]) -> list[RoleReference]:
    violations: list[RoleReference] = []
    for ref in refs:
        if ref.path == "CHANGELOG.md" or any(ref.path.startswith(p) for p in _DEFAULT_ALLOW_PREFIXES):
            continue
        violations.append(ref)
    return violations


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[3]))
    ap.add_argument("--write-report", action="store_true")
    ap.add_argument("--no-tail", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    refs = scan_role_references(root)
    legacy_rows = scan_legacy_dependencies(root)
    payload = report_payload(root, refs)
    if args.write_report:
        out_dir = root / "docs" / "history" / "v5.2.4-migration"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "V523_ROLE_REFERENCE_INVENTORY.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        (out_dir / "V523_ROLE_REFERENCE_INVENTORY.md").write_text(_markdown(payload), encoding="utf-8", newline="\n")
        (out_dir / "V523_LEGACY_CALL_GRAPH.md").write_text(_legacy_call_graph(refs, legacy_rows), encoding="utf-8", newline="\n")
    if args.no_tail:
        bad = no_tail_violations(refs)
        if bad:
            for ref in bad:
                print(f"ROLE_TAIL_FAIL {ref.path}:{ref.line} {ref.old_role_id} [{ref.classification}]")
            return 1
        print("ROLE_TAIL_PASS: no active v5.2.3 role references")
        return 0
    print(json.dumps({"count": len(refs), "classification_counts": payload["classification_counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
