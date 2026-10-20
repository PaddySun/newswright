"""BE-7/PG-3 余额主动探测测试：两家供应商每日一查+落账+阈值告警。

覆盖（任务书 §五必含用例逐项）：
- DeepSeek CNY string 解析（balance_infos 多币种取 CNY）；无 CNY 记录取首条
  并注记币种；moark number 解析；
- 低阈值（缺省 ¥5）→ balance_low 恰一次；不低不发；
- 探测自身失败（5xx/网络错）→ 落 error 不告警（次日再试）；
- 落账 JSON 形态（amount/currency/probed_at/ok/error——状态端点读此）；
- 宿主=_tick_backup 第四段（独立 try，A14 先例）。

出网零真发：get_json 经注入 client_factory 挂 MockTransport（池化面真路径）。
"""
import httpx
import pytest

from app.siteconfig import get_config
from app.transport import http as transport_http


@pytest.fixture(autouse=True)
def _fresh_client_pool():
    transport_http.reset_client_pool()
    yield
    transport_http.reset_client_pool()


def _factory(handler):
    """注入工厂：返回挂 MockTransport 的真实 Client（池化面真路径）。"""

    def factory(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    return factory


@pytest.fixture()
def notify_recorder(monkeypatch):
    """balance 触发器打桩记录（hub 行为由触发器测试覆盖）。"""
    calls: list[dict] = []
    monkeypatch.setattr("app.providers.balance.notify_balance_low",
                        lambda db, **kw: calls.append(kw) or {"queued": True})
    return calls


# ---------- 解析与落账 ----------


def test_probe_deepseek_cny_string_parsed(db_session, notify_recorder):
    """DeepSeek：balance_infos 多币种取 CNY 的 total_balance（string→float），
    落账 JSON 形态完整（amount/currency/probed_at/ok）。"""
    from app.providers.balance import probe_all

    def handler(request: httpx.Request) -> httpx.Response:
        if "deepseek" not in request.url.host:
            return httpx.Response(200, json={"balance": 20})  # 另一家：不低不响
        assert request.url.path.endswith("/user/balance")
        assert request.headers["Authorization"].startswith("Bearer ")
        return httpx.Response(200, json={
            "is_available": True,
            "balance_infos": [
                {"currency": "USD", "total_balance": "1.50"},
                {"currency": "CNY", "total_balance": "12.34"},
            ]})

    out = probe_all(db_session, client_factory=_factory(handler))
    rec = out["deepseek"]
    assert rec["ok"] is True and rec["amount"] == 12.34 and rec["currency"] == "CNY"
    stored = get_config(db_session, "balance_last_deepseek")
    assert stored["amount"] == 12.34 and stored["ok"] is True
    assert stored["probed_at"] and stored["error"] is None
    assert notify_recorder == []  # 12.34 ≥ 阈值 5：不发


def test_probe_deepseek_no_cny_takes_first_with_currency(db_session):
    """DeepSeek 无 CNY 记录：取首条并按实际币种记账（currency 注记）。"""
    from app.providers.balance import probe_all

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "is_available": True,
            "balance_infos": [{"currency": "USD", "total_balance": "9.9"}]})

    out = probe_all(db_session, client_factory=_factory(handler))
    rec = out["deepseek"]
    assert rec["ok"] is True and rec["amount"] == 9.9 and rec["currency"] == "USD"


def test_probe_moark_number_parsed(db_session, notify_recorder):
    """moark：balance 为 number（资源包余额，人民币元口径）。"""
    from app.providers.balance import probe_all

    def handler(request: httpx.Request) -> httpx.Response:
        if "deepseek" in request.url.host:
            return httpx.Response(200, json={
                "balance_infos": [{"currency": "CNY", "total_balance": "30"}]})
        assert request.url.path.endswith("/v1/tokens/packages/balance")
        return httpx.Response(200, json={
            "total_amount": 100, "used_amount": 94.5, "balance": 5.5,
            "details": []})

    out = probe_all(db_session, client_factory=_factory(handler))
    rec = out["moark"]
    assert rec["ok"] is True and rec["amount"] == 5.5
    assert get_config(db_session, "balance_last_moark")["amount"] == 5.5
    assert notify_recorder == []  # 5.5 ≥ 5：不发


def test_probe_all_covers_both_providers(db_session):
    """probe_all 两家各查各落账（一家失败不拖另一家）。"""
    from app.providers.balance import probe_all

    def handler(request: httpx.Request) -> httpx.Response:
        if "deepseek" in request.url.host:
            return httpx.Response(200, json={
                "balance_infos": [{"currency": "CNY", "total_balance": "20"}]})
        return httpx.Response(200, json={"balance": 8})

    out = probe_all(db_session, client_factory=_factory(handler))
    assert set(out) == {"deepseek", "moark"}
    assert all(r["ok"] for r in out.values())


# ---------- 阈值告警与失败语义 ----------


def test_low_balance_notifies_exactly_once(db_session, notify_recorder):
    """amount < 阈值（缺省 5）→ balance_low 恰一次（name+amount+threshold）；
  同轮另一家不低不滥发。"""
    from app.providers.balance import probe_all

    def handler(request: httpx.Request) -> httpx.Response:
        if "deepseek" in request.url.host:
            return httpx.Response(200, json={
                "balance_infos": [{"currency": "CNY", "total_balance": "4.2"}]})
        return httpx.Response(200, json={"balance": 6.0})

    probe_all(db_session, client_factory=_factory(handler))
    assert len(notify_recorder) == 1
    assert notify_recorder[0]["name"] == "deepseek"
    assert notify_recorder[0]["amount"] == 4.2
    assert notify_recorder[0]["threshold"] == 5


def test_probe_failure_records_error_without_notify(db_session, notify_recorder):
    """探测自身失败（5xx）→ 落 error（脱敏）不告警（次日再试）。"""
    from app.providers.balance import probe_all

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream boom")

    out = probe_all(db_session, client_factory=_factory(handler))
    rec = out["deepseek"]
    assert rec["ok"] is False and rec["amount"] is None
    assert rec["error"] and "sk-" not in rec["error"]
    stored = get_config(db_session, "balance_last_deepseek")
    assert stored["ok"] is False and stored["error"]
    assert notify_recorder == []


def test_probe_network_error_same_failure_semantics(db_session, notify_recorder):
    """网络层失败（连接拒绝，get_json 包装为 TransportError）同 5xx 语义。"""
    from app.providers.balance import probe_all

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    out = probe_all(db_session, client_factory=_factory(handler))
    assert all(r["ok"] is False for r in out.values())
    assert notify_recorder == []


# ---------- 宿主：_tick_backup 第四段 ----------


def test_daily_backup_tick_hosts_balance_probe(db_session, monkeypatch):
    """_tick_backup 第四段（独立 try，A14 同款）：每日轮顺带余额探测。"""
    from app import scheduler
    from app.providers import balance

    called: list = []
    monkeypatch.setattr(balance, "probe_all",
                        lambda db, **kw: called.append(1) or {})
    scheduler._tick_backup()
    assert len(called) == 1
