from pathlib import Path

BASE = Path(__file__).resolve().parents[2]


def read(rel: str) -> str:
    return (BASE / rel).read_text(encoding="utf-8-sig")


def test_implementation_template_contains_pre_and_post_change_contract():
    text = read("templates/5.3.0/implementation.md")
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


def test_systematic_debugging_requires_executed_red_feedback_loop_before_product_change():
    debugging = read("skills/capabilities/systematic-debugging/SKILL.md")
    for phrase in [
        "修改产品代码之前",
        "已经实际执行",
        "Red-capable",
        "Deterministic",
        "Fast",
        "Agent-runnable",
        "LOOP_UNAVAILABLE",
        "已有失败测试",
        "新增最小回归测试",
        "CLI/HTTP fixture",
        "Headless Browser",
        "Trace/Event replay",
        "Throwaway harness",
        "Property/Fuzz loop",
        "Differential/Bisect loop",
        "结构化 HITL",
        "原始、未最小化的反馈回路",
        "临时诊断 instrumentation",
        "错误的浅层测试",
    ]:
        assert phrase in debugging
    assert debugging.index("已经实际执行") < debugging.index("提出少量可证伪假设")



def test_implementation_control_uses_ordered_solution_ladder_without_weakening_quality():
    implementation = read("skills/capabilities/implementation-control/SKILL.md")
    ladder = [
        "当前功能是否真的需要存在",
        "当前代码库是否已有可直接复用实现",
        "只需修改现有实现",
        "JDK / 标准库",
        "框架或平台原生能力",
        "项目已安装依赖",
        "最简单的局部表达",
        "新增满足当前需求的最小实现",
    ]
    positions = [implementation.index(token) for token in ladder]
    assert positions == sorted(positions)
    for phrase in [
        "信任边界输入验证",
        "防数据丢失的错误处理",
        "安全、权限和隐私",
        "可访问性",
        "事务、一致性、并发、幂等",
        "兼容性",
        "最小充分验证",
    ]:
        assert phrase in implementation


def test_implementation_control_exposes_simplification_audit_lenses_without_new_finding_schema():
    anti_patterns = read("skills/capabilities/implementation-control/references/anti-patterns.md")
    for lens in ["`delete`", "`stdlib`", "`native`", "`yagni`", "`shrink`"]:
        assert lens in anti_patterns
    assert "不创建第二套 Finding schema" in anti_patterns
    for severity in ["必须修复", "建议修复", "可选优化", "无需修改"]:
        assert severity in anti_patterns



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
    guide = read("templates/5.3.0/requirement-test-guide.md")
    assert "## 非可视化验证" in guide
    assert "## 可视化验证" in guide
    assert "登录策略" in guide
    assert "目标视口" in guide
