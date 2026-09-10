"""Finite, explicit migration policy; never an active-routing compatibility bypass."""
from __future__ import annotations

# Retained shape-migration paths plus the supplied pre-upgrade task contracts.
# A supported source still needs schema, identity, artifact and transaction checks.
# This is not a promise that every historical deployment or PASS is compatible.
SOURCE_CONTRACTS = frozenset({
    "5.1.1", "5.1.3", "5.2.3", "5.2.8", "5.2.9", "5.3.0", "5.3.1",
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
