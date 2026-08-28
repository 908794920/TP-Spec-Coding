# -*- coding: utf-8 -*-
"""V5.2.8 generated Agent/Role/Skill topology contract."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import yaml

from cli import orchestration

BASE = Path(__file__).resolve().parents[2]
CATALOG_PATH = BASE / "governance" / "role-catalog.yaml"


def _catalog() -> dict:
    return yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))


def _validator_module():
    path = BASE / "scripts" / "update_role_catalog.py"
    spec = importlib.util.spec_from_file_location("v527_role_catalog_validator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_catalog_contains_generated_agent_role_skill_topology_with_dual_labels():
    catalog = _catalog()
    topology = catalog["topology"]

    assert topology["schema"] == "tp-spec.role-topology/v1"
    assert topology["generated"] is True
    assert topology["root_id"] == "tp-spec-coding"

    nodes = topology["nodes"]
    assert nodes["tp-spec-coding"] == {
        "id": "tp-spec-coding",
        "name": "tp-统一入口",
        "kind": "product-entry",
        "path": "entry/tp-spec-coding/SKILL.md",
        "domain": "product",
    }
    assert nodes["tp-software-lifecycle"]["name"] == "tp-软件工程生命周期"
    assert nodes["tp-product-manager"]["name"] == "tp-产品经理"
    assert nodes["requirement-clarification"]["name"] == "需求澄清"
    assert nodes["requirement-clarification"]["kind"] == "capability-skill"
    assert nodes["tp-memory-capture"]["name"] == "项目记忆捕获"

    for node_id, node in nodes.items():
        assert node["id"] == node_id
        assert node["name"].strip()
        assert node["kind"] in {"product-entry", "domain-agent", "formal-role", "capability-skill"}

    edge_keys = {
        (edge["from"], edge["to"], edge["relation"], edge.get("mode", ""))
        for edge in topology["edges"]
    }
    assert ("tp-spec-coding", "tp-software-lifecycle", "routes-to", "") in edge_keys
    assert ("tp-software-lifecycle", "tp-product-manager", "owns-role", "") in edge_keys
    assert ("tp-product-manager", "requirement-clarification", "uses-skill", "conditional") in edge_keys
    assert ("tp-tech-lead", "delivery-planning", "uses-skill", "conditional") in edge_keys
    assert ("tp-tech-lead", "technical-review", "uses-skill", "conditional") in edge_keys
    assert ("tp-project-autonomy", "tp-autonomy-cycle", "uses-skill", "conditional") in edge_keys

    formal_roles = {
        node_id for node_id, node in nodes.items()
        if node["kind"] == "formal-role"
    }
    assert formal_roles
    for role_id in formal_roles:
        assert (role_id, "tp-memory-capture", "uses-skill", "conditional") in edge_keys


def test_topology_query_matches_both_id_and_name_without_scanning_skill_files():
    by_id = orchestration.search_role_topology("tp-product-manager", base_root=BASE)
    by_name = orchestration.search_role_topology("产品经理", base_root=BASE)
    by_skill_name = orchestration.search_role_topology("需求澄清", base_root=BASE)

    assert [node["id"] for node in by_id] == ["tp-product-manager"]
    assert [node["id"] for node in by_name] == ["tp-product-manager"]
    assert [node["id"] for node in by_skill_name] == ["requirement-clarification"]


def test_validator_detects_generated_topology_drift():
    module = _validator_module()
    catalog = _catalog()
    broken = copy.deepcopy(catalog)
    broken["topology"]["nodes"]["tp-product-manager"]["name"] = "错误名称"

    errors = module.validate(broken)

    assert any("topology drift" in error for error in errors)


def test_card_display_skill_is_lifecycle_capability_not_product_entry():
    catalog = _catalog()
    topology = catalog["topology"]
    nodes = topology["nodes"]
    edges = topology["edges"]

    assert nodes["tp-card-display"]["name"] == "卡片展示调度"
    assert nodes["tp-card-display"]["kind"] == "capability-skill"
    assert nodes["tp-card-display"]["path"] == "skills/capabilities/tp-card-display/SKILL.md"
    assert any(
        edge["from"] == "tp-software-lifecycle"
        and edge["to"] == "tp-card-display"
        and edge["relation"] == "uses-skill"
        for edge in edges
    )
    assert not any(edge["relation"] == "routes-to" and edge["to"] == "tp-card-display" for edge in edges)
    assert topology["root_id"] == "tp-spec-coding"


def test_card_display_skill_declares_read_only_host_routing_boundaries():
    text = (BASE / "skills" / "capabilities" / "tp-card-display" / "SKILL.md").read_text(encoding="utf-8")

    for required in ("CARD_DISPLAY", "tp-spec card", "Web Artifact", "离线 HTML", "宿主", "明确要求"):
        assert required in text
    for forbidden in ("新增 MCP", "写 Runtime", "后台服务", "自行编造 HTML"):
        assert forbidden in text
