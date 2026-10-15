"""传输脊 GET 面测试（transport.http.get_json）：采集型 JSON GET 出网的统一单点。

背景（热榜治理批）：post_json 只覆盖 POST 面，聚合 API 是 GET——此前热榜域经
ingest.http.http_client 直连（httpx 原生异常裸抛、无重试分类）。GET 面与 POST 面
共用同一客户端池与同一非 2xx 分类单点（分类逻辑不分叉）；差异仅在重定向策略：
follow_redirects 缺省 True（采集通道既有行为零变）——正常重定向链落到 2xx 不入错
（「非 2xx 入错」以重定向终态为准）；终态 3xx（裸 302 无 location 等）按可重试
TransportError 入错；超限重定向链以 TooManyRedirects 包装入错；httpx 原生异常
（读超时/连接失败等 HTTPError 族）在本面包装为可重试 TransportError，不裸逃逸。
重定向策略进客户端池键（同源 POST/GET 各自池化，不串台）。
网络纪律：MockTransport + 注入工厂，零真联网。
设计依据见 docs/design-index.md「HR-1」「TR-2」「TR-6」。
"""
import httpx
import pytest

from app.transport import http as transport_http
from app.transport.errors import SemanticError, TransportError


@pytest.fixture(autouse=True)
def _fresh_client_pool():
    """每用例复位客户端池：池观测不跨用例串台。"""
    transport_http.reset_client_pool()
    yield
    transport_http.reset_client_pool()


def _factory_with(handler, constructions: list, kwargs_log: list | None = None):
    """注入工厂：记录构造次数与构造参数，返回挂 MockTransport 的真实 Client。"""

    def factory(**kwargs):
        constructions.append(1)
        if kwargs_log is not None:
            kwargs_log.append(dict(kwargs))
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    return factory


_URL = "https://agg.example/api/s?id=weibo&latest"


def _get(factory, *, url=_URL, params=None, headers=None, follow_redirects=None):
    kw = {}
    if follow_redirects is not None:
        kw["follow_redirects"] = follow_redirects
    return transport_http.get_json(url, params=params, headers=headers,
                                   timeout=5.0, client_factory=factory, **kw)


# ---------- 2xx 契约与参数透传 ----------

def test_get_json_2xx_returns_raw_response():
    """2xx 返回原始 httpx.Response（调用方自行 .json()——与 post_json 契约一致）。"""

    def handler(request):
        return httpx.Response(200, json={"status": "success", "items": []})

    resp = _get(_factory_with(handler, []))
    assert isinstance(resp, httpx.Response)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


def test_get_json_forwards_params_and_headers():
    """params 进查询串、调用方 headers 原样上送（采集面聚合 API 语义）。"""
    seen: list = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": 1})

    _get(_factory_with(handler, []), params={"id": "zhihu"},
         headers={"X-Token": "tok-1"})
    assert "id=zhihu" in str(seen[0].url)
    assert seen[0].headers["X-Token"] == "tok-1"


# ---------- 重定向终态语义（follow_redirects 缺省 True） ----------

def test_get_json_follows_normal_redirect_chain_to_2xx():
    """正常重定向链落到 2xx 不入错（「非 2xx 入错」以重定向终态为准——
    采集通道既有跟随行为零变）。"""
    hops = {"n": 0}

    def handler(request):
        if "hop1" in str(request.url):
            hops["n"] += 1
            return httpx.Response(302, headers={"location": _URL})
        return httpx.Response(200, json={"items": [{"title": "t"}]})

    resp = _get(_factory_with(handler, []), url="https://agg.example/hop1")
    assert resp.status_code == 200
    assert hops["n"] == 1  # 真实经过了跳转，不是跳过


def test_get_json_bare_302_terminal_retryable_transport_error():
    """裸 302（无 location 可跟随，终态即 3xx）→ 可重试 TransportError 带
    status=302、location=None（终态 3xx 不放行为「成功」）。"""

    def handler(request):
        return httpx.Response(302, text="moved, no location")

    with pytest.raises(TransportError) as ei:
        _get(_factory_with(handler, []))
    e = ei.value
    assert e.retryable is True
    assert e.status == 302
    assert e.location is None


def test_get_json_redirect_loop_wraps_too_many_redirects():
    """超限重定向链（httpx TooManyRedirects）→ 包装为可重试 TransportError，
    httpx 原生异常不裸逃逸。"""

    def handler(request):
        return httpx.Response(302, headers={"location": str(request.url)})

    with pytest.raises(TransportError) as ei:
        _get(_factory_with(handler, []))
    assert ei.value.retryable is True
    assert "TooManyRedirects" in str(ei.value)


def test_get_json_follow_redirects_false_bare_302_raises():
    """显式 follow_redirects=False：3xx 即刻入错（与 POST 面同形态——
    网关 302 营销站漏网教训的脊内拦截）。"""

    def handler(request):
        return httpx.Response(302, headers={"location": "https://mkt.example/p"},
                              text="promo")

    with pytest.raises(TransportError) as ei:
        _get(_factory_with(handler, []), follow_redirects=False)
    assert ei.value.status == 302
    assert ei.value.location == "https://mkt.example/p"


# ---------- 非 2xx 分类单点（与 post_json 同一实现） ----------

def test_get_json_429_retryable_mounts_retry_after():
    """429 → 可重试 TransportError 挂 Retry-After 解析值（分类单点不分叉）。"""

    def handler(request):
        return httpx.Response(429, headers={"retry-after": "7"}, text="slow")

    with pytest.raises(TransportError) as ei:
        _get(_factory_with(handler, []))
    assert ei.value.retryable is True
    assert ei.value.status == 429
    assert ei.value.retry_after == 7.0


def test_get_json_404_semantic_error():
    """致命 4xx（404）→ 不可重试 SemanticError。"""

    def handler(request):
        return httpx.Response(404, text="not found")

    with pytest.raises(SemanticError) as ei:
        _get(_factory_with(handler, []))
    assert ei.value.retryable is False
    assert ei.value.status == 404


# ---------- httpx 原生异常包装 ----------

def test_get_json_read_timeout_wrapped_retryable():
    """读超时（httpx.ReadTimeout）→ 可重试 TransportError（消息含原生异常
    类名），不裸逃逸。"""

    def handler(request):
        raise httpx.ReadTimeout("read timed out")

    with pytest.raises(TransportError) as ei:
        _get(_factory_with(handler, []))
    assert ei.value.retryable is True
    assert "ReadTimeout" in str(ei.value)


def test_get_json_connect_error_wrapped_retryable():
    """连接失败（httpx.ConnectError）同样包装为可重试 TransportError。"""

    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(TransportError) as ei:
        _get(_factory_with(handler, []))
    assert ei.value.retryable is True
    assert "ConnectError" in str(ei.value)


# ---------- 客户端池：重定向策略进池键 ----------

def test_get_json_pool_same_identity_reuses_client():
    """同（源、超时、UA、工厂、重定向策略）两次 GET 复用同一 Client 实例。"""

    def handler(request):
        return httpx.Response(200, json={"ok": 1})

    constructions: list = []
    factory = _factory_with(handler, constructions)
    r1 = _get(factory)
    r2 = _get(factory)
    assert len(constructions) == 1
    assert r1.status_code == 200 and r2.status_code == 200


def test_get_json_pool_redirect_policy_in_key_isolates_post_pool():
    """重定向策略进池键：同源 POST（不跟随）与 GET（跟随）各自构造客户端，
    不串台；构造参数如实携带各自策略。"""

    def handler(request):
        return httpx.Response(200, json={"ok": 1})

    constructions: list = []
    kwargs_log: list = []
    factory = _factory_with(handler, constructions, kwargs_log)
    auth = {"Authorization": "Bearer k-test"}
    transport_http.post_json(_URL, {"m": 1}, headers=auth, timeout=5.0,
                             client_factory=factory)
    _get(factory)
    assert len(constructions) == 2  # 两种重定向策略 → 两个客户端
    flags = [kw["follow_redirects"] for kw in kwargs_log]
    assert flags == [False, True]
