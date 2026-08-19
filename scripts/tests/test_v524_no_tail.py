from pathlib import Path

BASE = Path(__file__).resolve().parents[2]


def test_no_tail_allows_only_explicit_history_and_migration_paths(tmp_path):
    from scripts.migration.v5_2_3.role_reference_inventory import (
        OLD_ROLE_IDS,
        RoleReference,
        no_tail_violations,
    )

    old = OLD_ROLE_IDS[0]
    refs = [
        RoleReference("CHANGELOG.md", 1, old, old, "DOC_HISTORY"),
        RoleReference("cli/migrations/v5_2_3/role_map.py", 1, old, old, "MIGRATION_ONLY"),
        RoleReference("docs/history/v5.2.4-migration/x.md", 1, old, old, "DOC_HISTORY"),
        RoleReference("scripts/tests/fixtures/history/v5_1_0/x.py", 1, old, old, "FIXTURE"),
        RoleReference("scripts/tests/migration/test_role_map.py", 1, old, old, "TEST"),
        RoleReference("cli/runtime.py", 1, old, old, "ACTIVE_CLI"),
    ]

    bad = no_tail_violations(refs)
    assert [(r.path, r.old_role_id) for r in bad] == [("cli/runtime.py", old)]


def test_current_repository_has_no_active_v523_role_tail():
    from scripts.migration.v5_2_3.role_reference_inventory import (
        no_tail_violations,
        scan_role_references,
    )

    bad = no_tail_violations(scan_role_references(BASE))
    assert bad == []
