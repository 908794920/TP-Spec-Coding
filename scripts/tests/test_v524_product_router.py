import json

from cli import main as cli_main
from cli import product_router


def test_explicit_domain_signals_are_shallow_and_deterministic():
    assert product_router.route_domain("Review this commit").domain == "software"
    assert product_router.route_domain("更新项目 Wiki").domain == "wiki"
    assert product_router.route_domain("整理 knowledge 知识库").domain == "knowledge"
    assert product_router.route_domain("升级 TP-Spec 基座配置").domain == "base"
    assert product_router.route_domain("运行自治 cycle").domain == "autonomy"


def test_active_task_domain_wins_for_ambiguous_continue():
    d = product_router.route_domain("继续", active_task_domain="software")
    assert d.domain == "software"
    assert d.reason_code == "active_task_domain"


def test_ambiguous_without_context_requests_clarification():
    d = product_router.route_domain("继续")
    assert d.domain == "unknown"
    assert d.needs_clarification is True


def test_route_cli_emits_compact_json(capsys):
    rc = cli_main.main(["route", "--text", "review commit abc", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["domain"] == "software"
    assert set(payload) == {"domain", "confidence", "reason_code", "needs_clarification"}
