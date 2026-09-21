"""Finite, explicit migration policy; never an active-routing compatibility bypass."""
from __future__ import annotations

# Retained shape-migration paths plus the supplied pre-upgrade task contracts.
# A supported source still needs schema, identity, artifact and transaction checks.
# This is not a promise that every historical deployment or PASS is compatible.
#
# 5.3.2 was added 2026-09-21 after those four checks were verified end to end on
# real project data in an isolated copy: SQLite integrity ok on schema_version 1;
# project/task identity and status.yaml consistent; root artifact contracts
# 5.3.2 -> 5.3.4 migrated (owner-role map is a no-op for canonical roles);
# non-retroactive journal/transaction path. Adoption still follows trusted
# events, never the version string alone.
SOURCE_CONTRACTS = frozenset({
    "5.1.1", "5.1.3", "5.2.3", "5.2.8", "5.2.9", "5.3.0", "5.3.1", "5.3.2",
})


def contract_migration_policy(source: str, target: str) -> dict:
    current = source == target
    supported = current or source in SOURCE_CONTRACTS
    return {
        "source_contract": source,
        "target_contract": target,
        "runtime_compatible": current,
        "migration_supported": supported,
        "action": "NO_CONTRACT_MIGRATION" if current else (
            "EXPLICIT_MIGRATION" if supported else "UNSUPPORTED_MIGRATION_SOURCE"
        ),
        "historical_evidence_rebound": False,
    }
