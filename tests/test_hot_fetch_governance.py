"""热榜取用治理测试（fetch_platform）：传输脊 GET 面接线、域级重试与分类上抛、
聚合器候选位取用。

治理口径（热榜治理批）：
- 出网一律经 transport.get_json（裸 httpx 异常零逃逸——302/读超时等由传输脊
  分类为 TransportError 形态上抛）；
- 域级重试 ≤2 次（首次 + 2 重试）：仅可重试 TransportError 重试，退避经
  retry_delay_ms 协商（服务端 Retry-After 优先采纳、否则随机化指数退避——
  RNG 纪律：只断言区间与次数，不依赖具体随机序列）；ContractError（items
  非列表等响应契约违例）与 SemanticError 不重试；
- 聚合器候选位 HOT_AGG_CANDIDATES 按序取用：首候选失败（重试耗尽或不可
  重试）→ 下一候选，全败抛 RetryExhausted 终态（reason 两态 + 尝试链）；
  缺省单候选 = 行为零变；
- 轮次层语义不变：单平台失败不中断整轮（test_hot.py 既有断言护航）。

网络纪律：hot 域 get_json 打桩面接到真传输脊 GET 面 + MockTransport 注入工厂
（不出网；分类/包装行为与生产一致）。sleep 打桩记录，不真等待。
设计依据见 docs/design-index.md「HR-1」「HR-2」「HR-4」。
"""
import httpx
import pytest

import app.config as app_config
import app.hot.service as hot_service
from app.models import HotCallLog
from app.transport import http as transport_http
from app.transport.errors import (
    REASON_ERROR_NOT_RETRYABLE,
    REASON_MAX_RETRIES_EXCEEDED,
    ContractError,
    ProviderError,
    RetryExhausted,
    SemanticError,
    TransportError,
)


@pytest.fixture(autouse=True)
def _fresh_client_pool():
    transport_http.reset_client_pool()
    yield
    transport_http.reset_client_pool()


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """重试退避不真等待：记录 sleep 值供协商断言（RNG 纪律=断言区间）。"""
    sleeps: list[float] = []
    monkeypatch.setattr(hot_service.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


def _wire_real_get_json(monkeypatch, handler):
    """把 hot 域 get_json 打桩面接到真传输脊 GET 面（注入工厂零出网）：
    fetch_platform 吃到的错误分类/包装与生产路径完全一致。"""
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


# ---------- 重试与终态分类（AC-H1） ----------

def test_transient_5xx_retries_then_succeeds(db_session, monkeypatch):
    """瞬态 5xx（可重试）重试后成功：共 3 次尝试、2 次退避，退避值在
    随机化指数区间内（2**attempt × uniform(0.5,1.5) 秒）。"""
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] <= 2:
            return httpx.Response(503, text="upstream boom")
        return httpx.Response(200, json=_items_payload())

    _wire_real_get_json(monkeypatch, handler)
    items = hot_service.fetch_platform("weibo", db=db_session)
    assert len(items) == 2
    assert state["n"] == 3  # 首次 + 2 次重试


def test_retry_backoff_within_jittered_ranges(db_session, monkeypatch):
    """退避值落在随机化指数区间：第 1 次重试 ∈ (0.5,1.5]s、第 2 次 ∈ (1,3]s
    （断言区间与形态，不依赖具体随机序列）。"""
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] <= 2:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=_items_payload())

    _wire_real_get_json(monkeypatch, handler)
    monkeypatch.setattr(app_config, "HOT_AGG_CANDIDATES",
                        [app_config.HOT_AGG_BASE])
    sleeps: list[float] = []
    monkeypatch.setattr(hot_service.time, "sleep", lambda s: sleeps.append(s))
    hot_service.fetch_platform("weibo", db=db_session)
    assert len(sleeps) == 2
    assert 0.5 <= sleeps[0] <= 1.5
    assert 1.0 <= sleeps[1] <= 3.0


def test_retry_adopt_server_retry_after_over_backoff(db_session, monkeypatch):
    """429 携带 Retry-After → 退避协商优先采纳服务端值（确定性秒数，非退避区间）。"""
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "3"}, text="slow")
        return httpx.Response(200, json=_items_payload())

    _wire_real_get_json(monkeypatch, handler)
    sleeps: list[float] = []
    monkeypatch.setattr(hot_service.time, "sleep", lambda s: sleeps.append(s))
    items = hot_service.fetch_platform("weibo", db=db_session)
    assert len(items) == 2
    assert sleeps == [3.0]  # Retry-After=3s 夹逼区间内 → 原样采纳


def test_read_timeout_retry_exhausted_classified(db_session, monkeypatch):
    """读超时（httpx 原生异常）全程失败 → RetryExhausted 终态：reason=
    max_retries_exceeded、尝试链 3 条全为 TransportError——裸 httpx 异常零逃逸。"""

    def handler(request):
        raise httpx.ReadTimeout("read timed out")

    _wire_real_get_json(monkeypatch, handler)
    with pytest.raises(RetryExhausted) as ei:
        hot_service.fetch_platform("weibo", db=db_session)
    e = ei.value
    assert e.reason == REASON_MAX_RETRIES_EXCEEDED
    assert len(e.errors) == 3
    assert all(isinstance(x, TransportError) and "ReadTimeout" in str(x)
               for x in e.errors)
    assert isinstance(e, ProviderError)  # 兼容根：既有 except 面可捕


def test_bare_302_retryable_then_exhausted(db_session, monkeypatch):
    """裸 302（终态 3xx）→ 可重试 TransportError，重试耗尽后 RetryExhausted
    （网关 302 营销站漏网形态在热榜域的终态处置）。"""

    def handler(request):
        return httpx.Response(302, text="moved")

    _wire_real_get_json(monkeypatch, handler)
    with pytest.raises(RetryExhausted) as ei:
        hot_service.fetch_platform("weibo", db=db_session)
    assert ei.value.reason == REASON_MAX_RETRIES_EXCEEDED
    assert all(x.status == 302 for x in ei.value.errors)


def test_contract_error_not_retried(db_session, monkeypatch):
    """响应契约违例（items 非列表）→ ContractError 不重试（仅 1 次请求），
    终态 reason=error_not_retryable（替换治理前的裸 ValueError 形态）。"""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"status": "success", "items": "oops"})

    _wire_real_get_json(monkeypatch, handler)
    with pytest.raises(RetryExhausted) as ei:
        hot_service.fetch_platform("weibo", db=db_session)
    assert calls["n"] == 1  # 契约错误不烧重试
    assert ei.value.reason == REASON_ERROR_NOT_RETRYABLE
    assert isinstance(ei.value.errors[-1], ContractError)


def test_contract_error_non_json_body(db_session, monkeypatch):
    """响应非 JSON 体 → ContractError（同为契约违例，不重试）。"""

    def handler(request):
        return httpx.Response(200, text="<html>challenge page</html>")

    _wire_real_get_json(monkeypatch, handler)
    with pytest.raises(RetryExhausted) as ei:
        hot_service.fetch_platform("weibo", db=db_session)
    assert isinstance(ei.value.errors[-1], ContractError)


def test_semantic_404_not_retried(db_session, monkeypatch):
    """致命 4xx（404）→ SemanticError 不重试（1 次请求即终态）。"""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404, text="not found")

    _wire_real_get_json(monkeypatch, handler)
    with pytest.raises(RetryExhausted) as ei:
        hot_service.fetch_platform("weibo", db=db_session)
    assert calls["n"] == 1
    assert ei.value.reason == REASON_ERROR_NOT_RETRYABLE
    assert isinstance(ei.value.errors[-1], SemanticError)


# ---------- 聚合器候选位（AC-H3） ----------

def test_candidates_default_single_element_zero_change():
    """缺省配置：HOT_AGG_CANDIDATES == [HOT_AGG_BASE] 单元素（候选结构就位、
    默认行为零变——无切换路径可触发）。"""
    assert app_config.HOT_AGG_CANDIDATES == [app_config.HOT_AGG_BASE]
    assert len(app_config.HOT_AGG_CANDIDATES) == 1


def test_candidate_failover_first_down_second_serves(db_session, monkeypatch):
    """双候选：首候选重试耗尽 → 取次候选成功；请求计数 3+1。"""
    counts = {"a": 0, "b": 0}

    def handler(request):
        host = httpx.URL(str(request.url)).host
        counts["a" if host == "a.example" else "b"] += 1
        if host == "a.example":
            return httpx.Response(503, text="a down")
        return httpx.Response(200, json=_items_payload())

    _wire_real_get_json(monkeypatch, handler)
    monkeypatch.setattr(app_config, "HOT_AGG_CANDIDATES",
                        ["https://a.example/api/s", "https://b.example/api/s"])
    items = hot_service.fetch_platform("weibo", db=db_session)
    assert len(items) == 2
    assert counts == {"a": 3, "b": 1}
    # 落账归属取用成功的候选（次聚合器 origin）
    row = db_session.query(HotCallLog).one()
    assert row.provider == "https://b.example"
    assert row.ok is True


def test_candidate_failover_non_retryable_skips_to_next(db_session, monkeypatch):
    """首候选契约违例（不可重试）→ 不烧重试直接换次候选。"""
    counts = {"a": 0, "b": 0}

    def handler(request):
        host = httpx.URL(str(request.url)).host
        counts["a" if host == "a.example" else "b"] += 1
        if host == "a.example":
            return httpx.Response(200, json={"items": None})
        return httpx.Response(200, json=_items_payload())

    _wire_real_get_json(monkeypatch, handler)
    monkeypatch.setattr(app_config, "HOT_AGG_CANDIDATES",
                        ["https://a.example/api/s", "https://b.example/api/s"])
    items = hot_service.fetch_platform("weibo", db=db_session)
    assert len(items) == 2
    assert counts == {"a": 1, "b": 1}


def test_all_candidates_failed_terminal(db_session, monkeypatch):
    """全候选失败 → RetryExhausted（尝试链跨候选累计）；单平台终态上抛，
    轮次层容错照旧兜住（run_hot_round 语义见 test_hot.py）。"""

    def handler(request):
        raise httpx.ConnectError("refused")

    _wire_real_get_json(monkeypatch, handler)
    monkeypatch.setattr(app_config, "HOT_AGG_CANDIDATES",
                        ["https://a.example/api/s", "https://b.example/api/s"])
    with pytest.raises(RetryExhausted) as ei:
        hot_service.fetch_platform("weibo", db=db_session)
    assert ei.value.reason == REASON_MAX_RETRIES_EXCEEDED
    assert len(ei.value.errors) == 6  # 每候选 3 次尝试
    # 落账归属末次尝试的候选
    row = db_session.query(HotCallLog).one()
    assert row.ok is False
    assert row.provider == "https://b.example"


def test_request_url_shape_unchanged(db_session, monkeypatch):
    """请求 URL 形态零变：HOT_AGG_BASE?id=<platform>&latest（平台名进请求）。"""
    seen: list[str] = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json=_items_payload())

    _wire_real_get_json(monkeypatch, handler)
    monkeypatch.setattr(app_config, "HOT_AGG_CANDIDATES", [app_config.HOT_AGG_BASE])
    hot_service.fetch_platform("weibo", db=db_session)
    assert seen == [f"{app_config.HOT_AGG_BASE}?id=weibo&latest"]
