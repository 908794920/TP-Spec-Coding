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


def test_baseline_inventory_preserves_known_v523_hotspots_and_legacy_dependencies():
    inventory = json.loads((BASE / "docs/history/v5.2.4-migration/V523_ROLE_REFERENCE_INVENTORY.json").read_text(encoding="utf-8"))
    paths = {row["path"] for row in inventory["references"]}
    assert "cli/commit_cmd.py" in paths
    assert "cli/receipt_cmd.py" in paths

    legacy_text = (BASE / "docs/history/v5.2.4-migration/V523_LEGACY_CALL_GRAPH.md").read_text(encoding="utf-8")
    assert "cli/config_loader.py" in legacy_text
    assert "cli/workflow_loader.py" in legacy_text


def test_report_is_deterministic_and_json_serializable(tmp_path):
    from scripts.migration.v5_2_3.role_reference_inventory import scan_role_references, report_payload

    (tmp_path / "cli").mkdir()
    (tmp_path / "cli" / "x.py").write_text('x="tp-software-architect"\n', encoding="utf-8")
    first = report_payload(tmp_path, scan_role_references(tmp_path))
    second = report_payload(tmp_path, scan_role_references(tmp_path))
    assert first == second
    json.dumps(first, ensure_ascii=False, sort_keys=True)
