from cli.migrations.v5_2_3.role_map import ROLE_MAP, map_active_owner


def test_v523_action_roles_map_exactly_to_v524_formal_roles():
    assert ROLE_MAP == {
        "tp-requirement-analysis": "tp-product-manager",
        "tp-product-design": "tp-product-manager",
        "tp-architecture-design": "tp-software-architect",
        "tp-architecture-review": "tp-software-architect",
        "tp-development-engineering": "tp-development-engineer",
        "tp-verification-engineering": "tp-test-engineer",
        "tp-delivery-convergence": "tp-integration-engineer",
    }


def test_v523_role_mapping_preserves_nonlegacy_identity():
    assert map_active_owner("human_owner") == "human_owner"
    assert map_active_owner("tp-software-lifecycle") == "tp-software-lifecycle"
