from pathlib import Path
import json
import sys

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from cli.migrations.v5_2_3.role_map import ROLE_MAP
OLD = next(k for k, v in ROLE_MAP.items() if v == "tp-development-engineer")


def test_scan_finds_active_and_legacy_callers(tmp_path):
    from scripts.migration.v5_2_3.role_reference_inventory import scan_role_references

    (tmp_path / "cli").mkdir()
    (tmp_path / "cli" / "commit_cmd.py").write_text(f'ACTOR = "{OLD}"\n', encoding="utf-8")
    (tmp_path / "cli" / "config_loader.py").write_text(
        'from .legacy_workflow import LEGACY_STATE_OWNERS\n', encoding="utf-8"
    )
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "role_map.py").write_text(f'OLD = "{OLD}"\n', encoding="utf-8")

    refs = scan_role_references(tmp_path)
    by_path = {r.path: r for r in refs}
    assert by_path["cli/commit_cmd.py"].classification == "ACTIVE_CLI"
    assert by_path["migrations/role_map.py"].classification == "MIGRATION_ONLY"


def test_removed_role_inventory_is_not_shipped():
    assert not any(p.is_file() or p.is_symlink() for p in (BASE / "docs/history").rglob("*")) if (BASE / "docs/history").exists() else True

def test_report_is_deterministic_and_json_serializable(tmp_path):
    from scripts.migration.v5_2_3.role_reference_inventory import scan_role_references, report_payload

    (tmp_path / "cli").mkdir()
    (tmp_path / "cli" / "x.py").write_text('x="tp-software-architect"\n', encoding="utf-8")
    first = report_payload(tmp_path, scan_role_references(tmp_path))
    second = report_payload(tmp_path, scan_role_references(tmp_path))
    assert first == second
    json.dumps(first, ensure_ascii=False, sort_keys=True)
