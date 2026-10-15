"""HotCallLog 落账测试：每平台每次取用一行终态，成败都记。

落账口径（热榜治理批，照 search_call_log 同语义）：
- 一行终态：中间重试尝试不逐行（3 次尝试仍 1 行）；成败各记一行；
- 字段：provider=聚合器 origin、platform、ok、status=HTTP 码或错误类别
  （RetryExhausted 取末次尝试链的状态码，无码则错误类别名）、latency_ms=
  整次取用耗时、error 脱敏（sk- 形态不落账）、fetched_at 默认时间；
- 这是新增持久账：不替代任务 payload 的 platform_stats（形态零变）；
- db 为 None（无会话）时跳过落账、不炸。

网络纪律：get_json 打桩面接到真传输脊 + MockTransport（零出网）。
设计依据见 docs/design-index.md「HR-3」。
"""
import httpx
import pytest

import app.config as app_config
import app.hot.service as hot_service
from app.models import HotCallLog
from app.transport import http as transport_http
from app.transport.errors import TransportError


@pytest.fixture(autouse=True)
def _fresh_client_pool():
    transport_http.reset_client_pool()
    yield
    transport_http.reset_client_pool()


def _wire_real_get_json(monkeypatch, handler):
    factory = lambda **kwargs: httpx.Client(  # noqa: E731
        transport=httpx.MockTransport(handler), **kwargs)

    def fake_get_json(url, **kw):
        kw.pop("client_factory", None)
        return transport_http.get_json(url, client_factory=factory, **kw)

    monkeypatch.setattr(hot_service, "get_json", fake_get_json)


def _items_payload(n=2):
    return {"status": "success",
            "items": [{"title": f"热搜{i}", "url": f"https://x.example/{i}"}
                      for i in range(1, n + 1)]}


# ---------- 成功行 ----------

def test_success_row_single_final_state(db_session, monkeypatch):
    """成功取用一行终态：3 次尝试（503×2 → 200）仍只 1 行，字段齐全。"""
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] <= 2:
            return httpx.Response(503, text="boom")
        return httpx.Response(200, json=_items_payload())

    _wire_real_get_json(monkeypatch, handler)
    items = hot_service.fetch_platform("weibo", db=db_session)
    assert len(items) == 2
    rows = db_session.query(HotCallLog).all()
    assert len(rows) == 1  # 中间尝试不逐行
    row = rows[0]
    assert row.provider == "https://newsnow.busiyi.world"  # 聚合器 origin
    assert row.platform == "weibo"
    assert row.ok is True
    assert row.status == "200"
    assert isinstance(row.latency_ms, int) and row.latency_ms >= 0
    assert row.error is None
    assert row.fetched_at is not None


# ---------- 失败行 ----------

def test_failure_row_status_from_http_code(db_session, monkeypatch):
    """失败行 status 取末次尝试链的 HTTP 码（429 链 → "429"，如实记录——
  动态降频不在本批，状态先如实落账）。"""

    def handler(request):
        return httpx.Response(429, headers={"retry-after": "1"}, text="slow")

    _wire_real_get_json(monkeypatch, handler)
    monkeypatch.setattr(hot_service.time, "sleep", lambda s: None)
    with pytest.raises(Exception):  # noqa: B017  终态形态见治理测试文件
        hot_service.fetch_platform("weibo", db=db_session)
    row = db_session.query(HotCallLog).one()
    assert row.ok is False
    assert row.status == "429"
    assert "RetryExhausted" in (row.error or "")


def test_failure_row_status_error_class_without_http_code(db_session, monkeypatch):
    """无 HTTP 码的终态（读超时链）→ status=错误类别名。"""

    def handler(request):
        raise httpx.ReadTimeout("read timed out")

    _wire_real_get_json(monkeypatch, handler)
    with pytest.raises(Exception):  # noqa: B017
        hot_service.fetch_platform("weibo", db=db_session)
    row = db_session.query(HotCallLog).one()
    assert row.ok is False
    assert row.status == "RetryExhausted"
    assert row.error and "ReadTimeout" in row.error


def test_failure_row_error_scrubbed(db_session, monkeypatch):
    """error 入账前脱敏：异常消息中的 sk- 形态不原样落账。"""

    def fake_get_json(url, **kw):
        raise TransportError("HTTP 500: boom sk-abcdef123456",
                             retryable=True, status=500)

    monkeypatch.setattr(hot_service, "get_json", fake_get_json)
    monkeypatch.setattr(hot_service.time, "sleep", lambda s: None)
    with pytest.raises(Exception):  # noqa: B017
        hot_service.fetch_platform("weibo", db=db_session)
    row = db_session.query(HotCallLog).one()
    assert "sk-abcdef123456" not in (row.error or "")
    assert "sk-***" in (row.error or "")


# ---------- 轮次集成与豁免语义 ----------

def test_run_hot_round_ledger_per_platform(db_session, monkeypatch):
    """一轮双平台（一成一败）：每平台各一行终态；platform_stats payload 形态
    零变（HotCallLog 是新增持久账，不替代 payload 统计）。"""
    monkeypatch.setattr(app_config, "HOT_PLATFORMS", ["weibo", "zhihu"])
    monkeypatch.setattr(hot_service.time, "sleep", lambda s: None)
    monkeypatch.setattr(hot_service, "_extract_keywords",
                        lambda db, topics: (["关键词"], "综述", "fake-model"))

    def handler(request):
        if "id=zhihu" in str(request.url):
            return httpx.Response(500, text="down")
        return httpx.Response(200, json=_items_payload())

    _wire_real_get_json(monkeypatch, handler)
    out = hot_service.run_hot_round(db_session, triggered_by="test")
    assert out["status"] == "DONE"  # 单平台失败不中断整轮

    rows = {r.platform: r for r in db_session.query(HotCallLog).all()}
    assert set(rows) == {"weibo", "zhihu"}
    assert rows["weibo"].ok is True and rows["weibo"].status == "200"
    assert rows["zhihu"].ok is False
    # payload 统计形态零变：platform/ok/ms（+成功侧 items）
    stats_by_p = {s["platform"]: s for s in out["platforms"]}
    assert stats_by_p["weibo"]["ok"] is True and stats_by_p["weibo"]["items"] == 2
    assert stats_by_p["zhihu"]["ok"] is False and "error" in stats_by_p["zhihu"]


def test_no_session_skips_ledger(monkeypatch):
    """db=None（无会话）跳过落账不炸（生产调用恒传会话）。"""

    def fake_get_json(url, **kw):
        class R:
            status_code = 200

            def json(self):
                return _items_payload()

        return R()

    monkeypatch.setattr(hot_service, "get_json", fake_get_json)
    items = hot_service.fetch_platform("weibo", db=None)
    assert len(items) == 2
