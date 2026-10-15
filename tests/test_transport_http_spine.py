"""传输脊柱 HTTP 出口测试（transport.http）：非 2xx 全入错 + 客户端池。

背景（外部服务治理批）：post_json 是全部 JSON API 出网的单点——2xx 返回原始
httpx.Response（调用方自行 .json()，与既有 HTTPProvider._post_json 契约一致）；
非 2xx 一律入错：3xx=可重试 TransportError 带 location（网关 302 营销站漏网
成「成功空响应」的实锤教训）、429/5xx=可重试 TransportError（挂载 Retry-After
解析值）、其余 4xx=不可重试 SemanticError（官方错误码语义映射）。客户端池按
（源、鉴权头、超时、生效 UA、客户端工厂）进程级复用、线程安全。
设计依据见 docs/design-index.md「TR-1」「TR-2」「TR-6」。
"""
import threading

import httpx
import pytest

from app.siteconfig import set_config
from app.transport import http as transport_http
from app.transport.errors import ProviderError, SemanticError, TransportError


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


_AUTH = {"Authorization": "Bearer k-test", "Content-Type": "application/json"}
_URL = "https://api.example.com/v1/chat/completions"


def _post(factory, handler_response, *, url=_URL, db=None, headers=_AUTH):
    constructions: list = []
    factory_fn = _factory_with(handler_response, constructions)
    resp = transport_http.post_json(
        url, {"m": 1}, headers=headers, timeout=5.0, db=db, client_factory=factory_fn)
    return resp, constructions


# ---------- 2xx 契约 ----------

def test_post_json_2xx_returns_raw_response_for_caller_json():
    """2xx 返回原始 httpx.Response：调用方自行 .json()（与既有
    HTTPProvider._post_json 返回契约一致——迁移零行为变）。"""

    def handler(request):
        return httpx.Response(200, json={"ok": True})

    resp, _ = _post(None, handler)
    assert isinstance(resp, httpx.Response)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_post_json_forwards_payload_and_auth_headers():
    """请求体逐字透传 + 调用方鉴权头原样上送（域适配器语义不变）。"""
    seen: list = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": 1})

    _post(None, handler)
    assert seen[0].headers["Authorization"] == "Bearer k-test"
    import json as _json
    assert _json.loads(seen[0].read()) == {"m": 1}


# ---------- 3xx 全入错（AC-T1） ----------

def test_post_json_302_retryable_transport_error_with_location():
    """302 → 可重试 TransportError，status/location 结构化记录且消息含两者
    （此前 3xx 漏网成「成功空响应」，下游 .json() 神秘炸 JSONDecodeError）。"""

    def handler(request):
        return httpx.Response(302, headers={"location": "https://mkt.example/promo"},
                              text="<html>promo sk-secret123</html>")

    with pytest.raises(TransportError) as ei:
        transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0,
                                 client_factory=_factory_with(handler, []))
    e = ei.value
    assert e.retryable is True
    assert e.status == 302
    assert e.location == "https://mkt.example/promo"
    assert "302" in str(e) and "https://mkt.example/promo" in str(e)
    assert "sk-secret123" not in str(e)  # 错误体脱敏


def test_post_json_304_retryable_without_location():
    """304（无 location 头形态）同样入错可重试、location 为 None——
    非 2xx 一律不得放行为「成功」。"""

    def handler(request):
        return httpx.Response(304, text="")

    with pytest.raises(TransportError) as ei:
        transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0,
                                 client_factory=_factory_with(handler, []))
    assert ei.value.retryable is True
    assert ei.value.status == 304
    assert ei.value.location is None


# ---------- 429/5xx 可重试 + Retry-After 挂载 ----------

def test_post_json_429_mounts_retry_after_seconds_form():
    """429 挂载 Retry-After delta-seconds 解析值（供退避协商优先采纳）。"""

    def handler(request):
        return httpx.Response(429, headers={"retry-after": "10"}, text="rate limited")

    with pytest.raises(TransportError) as ei:
        transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0,
                                 client_factory=_factory_with(handler, []))
    assert ei.value.retryable is True
    assert ei.value.status == 429
    assert ei.value.retry_after == 10.0


def test_post_json_429_mounts_retry_after_http_date_form():
    """429 挂载 Retry-After HTTP-date 形态解析值（双形态解析进脊，B3 判例）。"""
    import time as _time
    from email.utils import formatdate

    def handler(request):
        return httpx.Response(
            429, headers={"retry-after": formatdate(_time.time() + 120, usegmt=True)},
            text="slow down")

    with pytest.raises(TransportError) as ei:
        transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0,
                                 client_factory=_factory_with(handler, []))
    assert ei.value.retry_after is not None
    assert 100 < ei.value.retry_after <= 120  # 解析为「距今秒数」而非原始串


def test_post_json_5xx_retryable_transport_error():
    """5xx → 可重试 TransportError，消息保持 `HTTP <status>: <脱敏体>` 形态
    （与迁移前 providers/search 域消息格式一致）。"""
    for status in (500, 502, 503, 504):
        def handler(request, s=status):
            return httpx.Response(s, text="upstream boom")

        with pytest.raises(TransportError) as ei:
            transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0,
                                     client_factory=_factory_with(handler, []))
        assert ei.value.retryable is True
        assert ei.value.status == status
        assert f"HTTP {status}" in str(ei)


# ---------- 4xx 致命域（官方语义映射） ----------

def test_post_json_fatal_status_semantic_error_official_message():
    """400/401/402/422 → 不可重试 SemanticError，消息携带官方错误码语义
    （与迁移前 LLM 域 FATAL_STATUS_MESSAGE 映射逐字一致）。"""
    markers = {400: "请求体格式错误", 401: "认证失败",
               402: "余额不足", 422: "请求参数错误"}
    for status, marker in markers.items():
        def handler(request, s=status):
            return httpx.Response(s, text="boom")

        with pytest.raises(SemanticError) as ei:
            transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0,
                                     client_factory=_factory_with(handler, []))
        assert ei.value.retryable is False
        assert ei.value.status == status
        assert marker in str(ei.value) and str(status) in str(ei.value)


def test_post_json_fatal_other_status_plain_http_prefix():
    """其余 ≥400（如 403/404）无官方映射：消息回退 `HTTP <status>` 前缀。"""

    def handler(request):
        return httpx.Response(403, text="forbidden")

    with pytest.raises(SemanticError) as ei:
        transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0,
                                 client_factory=_factory_with(handler, []))
    assert "HTTP 403" in str(ei.value)


def test_post_json_scrubs_key_pattern_from_error_body():
    """报错脱敏纪律随迁移保持：错误响应体中的 sk- 串不原样进异常消息。"""

    def handler(request):
        return httpx.Response(400, text="bad key sk-abcdef123456")

    with pytest.raises(ProviderError) as ei:
        transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0,
                                 client_factory=_factory_with(handler, []))
    assert "sk-abcdef123456" not in str(ei.value)


# ---------- 客户端池（AC-T5） ----------

def test_client_pool_same_identity_same_instance():
    """同（源、鉴权、超时、UA、工厂）两次调用复用同一 Client 实例
    （注入工厂观测：构造恰一次、两次请求都 200）。"""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"ok": True})

    constructions: list = []
    factory = _factory_with(handler, constructions)
    r1 = transport_http.post_json(_URL, {"i": 1}, headers=_AUTH, timeout=5.0,
                                  client_factory=factory)
    r2 = transport_http.post_json(_URL, {"i": 2}, headers=_AUTH, timeout=5.0,
                                  client_factory=factory)
    assert len(constructions) == 1  # 池命中：不重建
    assert r1.status_code == 200 and r2.status_code == 200
    assert calls["n"] == 2  # 两次请求都真实发出


def test_client_pool_user_agent_value_in_key(db_session):
    """池键含生效 UA 值：site_config 切 UA 策略后新 UA 生效=新客户端构造
    （否则管理员运行时切 UA 不生效——池缓存旧头）。"""

    def handler(request):
        return httpx.Response(200, json={"ok": 1})

    constructions: list = []
    kwargs_log: list = []
    factory = _factory_with(handler, constructions, kwargs_log)
    transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0,
                             db=db_session, client_factory=factory)
    set_config(db_session, "ua_strategy", "custom")
    set_config(db_session, "ua_custom", "MyAgent/9.9 (+https://me.example)")
    transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0,
                             db=db_session, client_factory=factory)
    assert len(constructions) == 2  # UA 变 → 新客户端
    uas = [kw["headers"]["User-Agent"] for kw in kwargs_log]
    assert "MyAgent/9.9" in uas[1] and uas[0] != uas[1]


def test_client_pool_different_factory_identity_isolated():
    """工厂身份入池键：不同工厂（测试注入互异）各自构造——同进程桩替换
    不串台；生产路径工厂恒为 httpx.Client 同对象，池稳定复用。"""

    def handler(request):
        return httpx.Response(200, json={"ok": 1})

    c1: list = []
    c2: list = []
    transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0,
                             client_factory=_factory_with(handler, c1))
    transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0,
                             client_factory=_factory_with(handler, c2))
    assert len(c1) == 1 and len(c2) == 1


def test_client_pool_thread_safe_single_construction():
    """线程安全：并发同键请求只构造一个 Client（全部请求都成功）。"""
    n_threads = 8
    barrier = threading.Barrier(n_threads)
    results: list = []

    def handler(request):
        return httpx.Response(200, json={"ok": 1})

    constructions: list = []
    lock = threading.Lock()

    def factory(**kwargs):
        with lock:  # 构造计数须线程安全（池本身保证单构造，计数器自保护）
            constructions.append(1)
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    def worker():
        barrier.wait()  # 尽量同时进池取客户端
        resp = transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0,
                                        client_factory=factory)
        results.append(resp.status_code)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert len(results) == n_threads and all(s == 200 for s in results)
    assert len(constructions) == 1


def test_client_pool_client_carries_ua_and_proxy(db_session, monkeypatch):
    """池客户端构造参数：默认 UA 按站点策略解析 + proxy 参数位透传
    （env HTTPX_PROXY 注入即启用，归口 config 读取）。构造参数观测——
    不真发请求（httpx 的 proxy mount 与 MockTransport 互斥，出网封禁照常生效）。"""
    from app.config import PROXY_ENV_KEY

    monkeypatch.setenv(PROXY_ENV_KEY, "http://proxy.local:3128")
    set_config(db_session, "contact_email", "ops@example.com")

    captured: dict = {}

    class RecordingClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def post(self, url, **kwargs):
            return httpx.Response(200, json={"ok": 1})

    transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0, db=db_session,
                             client_factory=RecordingClient)
    assert captured["proxy"] == "http://proxy.local:3128"
    assert "ops@example.com" in captured["headers"]["User-Agent"]
    assert captured["timeout"] == 5.0


def test_client_pool_no_proxy_env_no_proxy_kwarg(monkeypatch):
    """未配置 proxy 时不传 proxy 构造参数（不配置行为不变）。"""
    from app.config import PROXY_ENV_KEY

    monkeypatch.delenv(PROXY_ENV_KEY, raising=False)

    def handler(request):
        return httpx.Response(200, json={"ok": 1})

    kwargs_log: list = []
    transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0,
                             client_factory=_factory_with(handler, [], kwargs_log))
    assert "proxy" not in kwargs_log[0]
