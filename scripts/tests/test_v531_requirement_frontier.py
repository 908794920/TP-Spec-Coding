"""v5.3.3 Requirement Frontier method contracts."""
from __future__ import annotations

from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parents[2]
CAPABILITY = BASE / "skills" / "capabilities" / "requirement-clarification" / "SKILL.md"
PRODUCT_ROLE = BASE / "skills" / "roles" / "tp-product-manager" / "SKILL.md"
TEMPLATE_ROOT = BASE / "templates" / "5.3.3"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert_contains(text: str, *tokens: str) -> None:
    for token in tokens:
        assert token in text, token


def test_frontier_is_a_conditional_method_not_a_default_questionnaire():
    text = _read(CAPABILITY)
    _assert_contains(
        text,
        "Requirement Frontier",
        "复杂 L2/L3",
        "多个关键决策存在前置依赖",
        "L0/L1",
        "不启用 Frontier",
        "最小澄清路径",
        "用户明确要求系统性决策梳理",
        "明确请求不覆盖 L0/L1",
        "没有前置依赖",
    )
    assert not (BASE / "skills" / "capabilities" / "requirement-frontier").exists()


def test_frontier_tracks_all_currently_decidable_and_asks_only_blocking_decisions():
    text = _read(CAPABILITY)
    _assert_contains(
        text,
        "Current Frontier",
        "所有前置条件已解决",
        "不以 `blocking` 作为成员资格",
        "满足条件的未决节点进入 `FRONTIER`",
        "真正 blocking",
        "prerequisites",
        "WAITING_PREREQUISITE",
        "FRONTIER",
        "前置条件已解决",
        "下游问题",
        "不得提前提出",
        "最小 coherent batch",
        "本轮其他答案",
    )
    assert "满足条件的 blocking 节点进入 `FRONTIER`" not in text


def test_fact_investigation_and_human_decisions_remain_separate():
    text = _read(CAPABILITY)
    _assert_contains(
        text,
        "WAITING_FACT",
        "技术事实",
        "Wiki、Knowledge、Memory",
        "只读调查",
        "不把用户当作代码检索工具",
        "推荐答案",
        "范围、架构、风险、兼容性或验收",
        "数据、权限、安全、生产或核心业务",
        "不得静默默认",
    )


def test_frontier_converges_fail_closed_and_preserves_decision_history():
    text = _read(CAPABILITY)
    _assert_contains(
        text,
        "RESOLVED",
        "DEFAULTED",
        "SUPERSEDED",
        "EXCLUDED",
        "重新评估分支适用性",
        "不再相关的下游节点标记为 `EXCLUDED`",
        "不计入 `blocking_open`",
        "reopened",
        "保留原 decision",
        "重新加入 Current Frontier",
        "blocking_open",
        "全部未解决",
        "只要存在未解决的 blocking 节点",
        "`requirement-clarifications.md`",
        "`blocking_open > 0`",
        "`requirement-decisions.md` 不能替代",
        "循环依赖",
        "建模错误",
        "不得判定 Requirement Ready",
    )


def test_product_manager_uses_frontier_without_turning_it_into_a_gate():
    text = _read(PRODUCT_ROLE)
    _assert_contains(
        text,
        "Requirement Frontier",
        "复杂 L2/L3",
        "前置依赖",
        "Current Frontier",
        "L0/L1",
        "不增加固定问卷",
        "不新增 Runtime state",
    )


def test_frontier_does_not_extend_role_catalog_or_runtime_states():
    catalog = yaml.safe_load(_read(BASE / "governance" / "role-catalog.yaml"))
    role_ids = {row["workflow_role"] for row in catalog["roles"]}
    assert "requirement-frontier" not in role_ids

    workflow = yaml.safe_load(_read(BASE / "governance" / "workflow.yaml"))
    states = set(workflow["states"])
    assert states == {"NEW", "ACTIVE", "BLOCKED", "COMPLETED", "CANCELLED"}
    assert not (BASE / "cli" / "requirement_frontier.py").exists()



def test_existing_requirement_templates_can_record_frontier_without_new_artifact():
    requirement = _read(TEMPLATE_ROOT / "requirement.md")
    clarifications = _read(TEMPLATE_ROOT / "requirement-clarifications.md")
    decisions = _read(TEMPLATE_ROOT / "requirement-decisions.md")

    _assert_contains(
        requirement,
        "Decision Dependencies / Current Frontier",
        "仅复杂 L2/L3",
        "没有依赖决策时删除本节",
    )
    _assert_contains(
        clarifications,
        "Fact Investigation",
        "| decision_id | 待调查技术事实 | status | evidence_refs | 置信度 | 调查结论 |",
        "Current Frontier",
        "Deferred Decisions",
        "WAITING_FACT",
        "WAITING_PREREQUISITE",
        "只向用户展示 `FRONTIER`",
        "| decision_id | blocking | 问题 |",
        "本轮其他答案",
    )
    _assert_contains(
        decisions,
        "decision_id",
        "prerequisites",
        "status",
        "blocking",
        "recommendation",
        "human decision / 受控默认",
        "impact",
        "evidence_refs",
        "supersedes / history",
        "保留原 decision",
    )
    assert not (TEMPLATE_ROOT / "requirement-frontier.md").exists()


def test_clarification_template_keeps_blocking_open_distinct_from_current_frontier():
    path = TEMPLATE_ROOT / "requirement-clarifications.md"
    text = _read(path)
    assert text.startswith("---\n")
    front_matter = yaml.safe_load(text.split("---", 2)[1])
    assert front_matter["blocking_open"] == 0
    assert isinstance(front_matter["blocking_open"], int)
    assert "current_frontier" not in front_matter
    _assert_contains(
        text,
        "blocking_open",
        "全部未解决",
        "WAITING_FACT",
        "WAITING_PREREQUISITE",
        "FRONTIER",
        "不是 Current Frontier 的条目数",
    )


def test_template_readme_preserves_record_first_and_conditional_use():
    text = _read(TEMPLATE_ROOT / "README.md")
    _assert_contains(
        text,
        "Requirement Frontier",
        "复杂 L2/L3",
        "L0/L1",
        "不创建空工件",
        "不新增 Runtime state",
        "blocking_open",
        "全部未解决",
    )


def test_b05_templates_offer_one_optional_current_region_and_keep_history_separate():
    # The template is the user-facing editing contract; behavior lives in the
    # production CLI tests, not in these literal assertions.
    for name in ('task.md', 'requirement.md'):
        text = _read(TEMPLATE_ROOT / name)
        assert text.count('<!-- tp-spec:current:start -->') == 1
        assert text.count('<!-- tp-spec:current:end -->') == 1
        assert text.index('<!-- tp-spec:current:start -->') < text.index('<!-- tp-spec:current:end -->')
        assert 'SUPERSEDED' in text[text.index('<!-- tp-spec:current:end -->'):]
    capability = _read(CAPABILITY)
    assert '当前有效范围与决策' in capability
    assert '单一维护位置' in capability
    assert '技术事实' in capability and '不授予' in capability
