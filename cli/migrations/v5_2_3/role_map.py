"""One-shot V5.2.3 Action-role -> V5.2.4 formal-role migration map.

This module is migration-only. Active V5.2.4 routing must never import it.
Historical task events keep their original actor_role unchanged; only the
current non-terminal task owner is mapped during `task migrate`.
"""
from __future__ import annotations

ROLE_MAP = {
    "tp-requirement-analysis": "tp-product-manager",
    "tp-product-design": "tp-product-manager",
    "tp-architecture-design": "tp-software-architect",
    "tp-architecture-review": "tp-software-architect",
    "tp-development-engineering": "tp-development-engineer",
    "tp-verification-engineering": "tp-test-engineer",
    "tp-delivery-convergence": "tp-integration-engineer",
}


def map_active_owner(role: str) -> str:
    """Map only known V5.2.3 Action roles; preserve canonical/human identities."""
    value = str(role or "").strip()
    return ROLE_MAP.get(value, value)
