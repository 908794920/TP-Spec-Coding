from pathlib import Path

BASE = Path(__file__).resolve().parents[2]


def read(rel: str) -> str:
    return (BASE / rel).read_text(encoding="utf-8-sig")


def test_implementation_template_contains_pre_and_post_change_contract():
    text = read("templates/5.2.9/implementation.md")
    for marker in [
        "### Usage Footprint",
        "### 可复用代码",
        "### 事实前提修正",
        "### 明确不做",
        "### 变更理由映射",
        "### 简化与删除",
    ]:
        assert marker in text


def test_development_and_review_roles_encode_maintainable_defaults():
    developer = read("skills/roles/tp-development-engineer/SKILL.md")
    reviewer = read("skills/roles/tp-code-reviewer/SKILL.md")
    assert "新增或修改的人工注释默认使用中文" in developer
    assert "1～3 年" in developer
    assert "没有确定 Finding 时不修改代码" in reviewer
    assert "No findings" in reviewer
    assert "只读" in reviewer


def test_lifecycle_and_integration_keep_external_implementation_review_only():
    lifecycle = read("agents/tp-software-lifecycle/SKILL.md")
    integration = read("skills/roles/tp-integration-engineer/SKILL.md")
    assert "外部 AI 已完成实现" in lifecycle
    assert "Test Engineer + Code Reviewer" in lifecycle
    assert "Integration 发现问题必须返回 Development" in integration


def test_capability_references_capture_overdevelopment_and_low_value_tests():
    implementation = read("skills/capabilities/implementation-control/SKILL.md")
    anti_patterns = read("skills/capabilities/implementation-control/references/anti-patterns.md")
    test_value = read("skills/capabilities/testing-strategy/references/test-value.md")
    assert "THINK" in implementation
    assert "SIMPLIFY" in implementation
    assert "SURGICAL CHANGE" in implementation
    assert "GOAL-DRIVEN VERIFY" in implementation
    for phrase in [
        "顺手重构一下",
        "为了以后扩展先抽象",
        "多写几个测试更保险",
        "没找到静态调用所以可以直接删",
        "Delivery 中只改一行不用回开发",
        "静态页面契约全绿所以视觉通过",
    ]:
        assert phrase in anti_patterns
    for phrase in [
        "不为静态常量本身写测试",
        "不测试 Mock 自身",
        "test-only helper",
        "源码 grep/DOM 字符串断言只能保护结构契约",
    ]:
        assert phrase in test_value


def test_test_guide_separates_visual_and_non_visual_validation():
    guide = read("templates/5.2.9/requirement-test-guide.md")
    assert "## 非可视化验证" in guide
    assert "## 可视化验证" in guide
    assert "登录策略" in guide
    assert "目标视口" in guide
