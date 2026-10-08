"""搜索 provider 装配与解析契约：bocha 适配器请求/响应/错误三面 + 注册表会话归因。

覆盖对象：app/search/bocha.py（BochaSearchProvider._search/__init__）、
app/search/base.py（HTTPSearchProvider 构造与 _post_json 传输层）、
app/search/registry.py（get_provider 会话透传）。

条款依据（技术书 v1.9 / 产品书 v1.8，溯源见 docs/design-index.md）：
- ADR-8 provider 统一纪律：可重试状态语义（429/5xx retryable）、报错脱敏（Key 不进
  错误消息）、显式超时（§4.2：None 即无限等待失守）、出网统一出口的 UA 策略读取
  （R9——db 会话归因断裂即 honest 无邮箱形态）。
- bocha 模块 docstring 字段映射（官方 Web Search API）：data.webPages.value[] 的
  name→title、url→url、snippet→snippet、summary→content、datePublished→published_at；
  raw 原始条目存档（pipeline docstring「raw 条目存档于 item.raw」，e2e 断言面在库）。
- R8/AC-09.1：freshness 配置透传（source_config.freshness → 请求 payload["freshness"]，
  配置传入契约；服务端生效面实测无效已备案，不在断言面）。
- 分页参数 count：请求条数语义（官方 count ≤50 上限护栏，V10 实测口径；下限 1）。
- summary 请求构造：summary=true 才有 content（模块 docstring——全文承载请求面，
  生产调用恒走缺省 True）。
- 错误体处理：code 非 200 或 data 非 dict → SearchError（响应异常显式失败，不静默空结果）。

红线：全部 httpx MockTransport 打桩，零真实 API 调用；Key 注入测试值。
"""
import json
from datetime import datetime, timezone

import httpx
import pytest

import app.search.registry as search_registry
from app.search.base import SearchError
from app.search.bocha import BochaSearchProvider

_REAL_CLIENT = httpx.Client  # 模块导入时绑定：二次 patch 时不叠桩


class _Captured:
    def __init__(self):
        self.client_kwargs: dict | None = None
        self.request: httpx.Request | None = None


def _patch_client(monkeypatch, handler, captured: _Captured):
    def wrapped(request):
        captured.request = request
        return handler(request)

    def factory(**kwargs):
        captured.client_kwargs = dict(kwargs)
        return _REAL_CLIENT(transport=httpx.MockTransport(wrapped), **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)


def _provider(db_session=None, **kwargs) -> BochaSearchProvider:
    return BochaSearchProvider(api_key="k-test", db=db_session, **kwargs)


def _entry(**over) -> dict:
    base = {"name": "标题一", "url": "https://a.com/1", "snippet": "摘要一",
            "summary": "全文一", "datePublished": "2026-09-27"}
    base.update(over)
    return base


def _body(entries) -> dict:
    return {"code": 200, "data": {"webPages": {"value": entries}}}


# ---------- 请求构造（payload 四键 + 鉴权/类型头 + UA 策略 + 显式超时） ----------

def test_bocha_request_payload_and_auth_headers(monkeypatch):
    """请求 payload 四键逐字 + Bearer/application/json 两头（键名与值形态）。"""
    captured = _Captured()
    _patch_client(monkeypatch, lambda r: httpx.Response(200, json=_body([])), captured)
    p = _provider()
    p._search("查询词", 1, {"freshness": "oneDay"})
    assert json.loads(captured.request.read()) == {
        "query": "查询词", "count": 1, "summary": True, "freshness": "oneDay"}
    assert captured.request.headers.get("Authorization") == "Bearer k-test"
    assert captured.request.headers.get("Content-Type") == "application/json"


def test_bocha_count_upper_clamp_at_fifty(monkeypatch):
    """count 上限护栏：超配 clamp 到官方上限 50（V10 实测口径）。"""
    captured = _Captured()
    _patch_client(monkeypatch, lambda r: httpx.Response(200, json=_body([])), captured)
    p = _provider()
    p._search("查询词", 100, {})
    assert json.loads(captured.request.read())["count"] == 50


def test_bocha_ua_policy_reads_site_config_via_db(db_session, monkeypatch):
    """出网统一出口按 db 会话读 UA 策略（R9）：custom UA 生效——db 归因断裂即
    honest 无邮箱形态，请求 UA 立即可辨。"""
    from app.siteconfig import set_config

    set_config(db_session, "ua_strategy", "custom")
    set_config(db_session, "ua_custom", "TestUA/1.0 (contract)")
    db_session.commit()
    captured = _Captured()
    _patch_client(monkeypatch, lambda r: httpx.Response(200, json=_body([])), captured)
    p = _provider(db_session)
    p._search("查询词", 1, {})
    assert captured.request.headers.get("User-Agent") == "TestUA/1.0 (contract)"


def test_bocha_explicit_timeout_reaches_client(db_session, monkeypatch):
    """显式超时透传链：构造 timeout=45 → httpx.Client 以 45 构造（§4.2：None 即
    无限等待失守；缺省 30.0 与工厂缺省 60.0 均非 45，可辨）。"""
    captured = _Captured()
    _patch_client(monkeypatch, lambda r: httpx.Response(200, json=_body([])), captured)
    p = _provider(db_session, timeout=45.0)
    p._search("查询词", 1, {})
    assert captured.client_kwargs["timeout"] == 45.0


def test_bocha_missing_api_key_rejected(monkeypatch):
    """缺 Key 拒构造（类型化 SearchError）。"""
    import app.config as cfg

    monkeypatch.setattr(cfg, "BOCHA_API_KEY", "")
    with pytest.raises(SearchError):
        BochaSearchProvider()


# ---------- 响应解析（字段映射/归一化/strip/缺省条目） ----------

def test_bocha_response_field_mapping(monkeypatch):
    """字段映射逐字段（含 strip 与缺字段条目）+ published_at 解析 + raw 存档。"""
    captured = _Captured()
    full = _entry()
    padded = {"name": "  标题二  ", "url": "  https://a.com/2  ",
              "snippet": "  ", "summary": "  ", "datePublished": ""}
    bare = {}  # 全缺字段条目：各域兜底 ""
    _patch_client(monkeypatch,
                  lambda r: httpx.Response(200, json=_body([full, padded, bare])),
                  captured)
    p = _provider()
    out = p._search("查询词", 5, {})

    assert len(out) == 3
    r0 = out[0]
    assert r0.title == "标题一" and r0.url == "https://a.com/1"
    assert r0.snippet == "摘要一" and r0.content == "全文一"
    assert r0.published_at == datetime(2026, 9, 27, tzinfo=timezone.utc)
    assert r0.raw == full  # 原始条目存档
    r1 = out[1]
    assert r1.title == "标题二" and r1.url == "https://a.com/2"
    assert r1.snippet == "" and r1.content == "" and r1.published_at is None
    r2 = out[2]
    assert r2.title == "" and r2.url == "" and r2.snippet == "" and r2.content == ""
    assert r2.published_at is None and r2.raw == {}


# ---------- 错误体处理（coded 响应异常必须显式失败） ----------

def test_bocha_non_200_code_raises_even_with_data(monkeypatch):
    """code 非 200：即便 data 可解析也必须 SearchError（错误码检查本体）。"""
    captured = _Captured()
    _patch_client(
        monkeypatch,
        lambda r: httpx.Response(200, json=_body([_entry()]) | {"code": 403}),
        captured)
    p = _provider()
    with pytest.raises(SearchError):
        p._search("查询词", 5, {})


def test_bocha_missing_or_non_dict_data_raises(monkeypatch):
    """code=200 但 data 缺失/非 dict：SearchError（不静默空结果）。"""
    captured = _Captured()
    p = _provider()
    for bad in ({"code": 200}, {"code": 200, "data": ["not-a-dict"]}):
        _patch_client(monkeypatch, lambda r, b=bad: httpx.Response(200, json=b), captured)
        with pytest.raises(SearchError):
            p._search("查询词", 5, {})


# ---------- 传输层（HTTPSearchProvider._post_json） ----------

def test_post_json_retryable_status_flags_error(monkeypatch):
    """429/5xx → SearchError 且 retryable=True（ADR-8 可重试状态语义）。"""
    captured = _Captured()
    _patch_client(monkeypatch, lambda r: httpx.Response(429, text="rate"), captured)
    p = _provider()
    with pytest.raises(SearchError) as ei:
        p._post_json("https://api.bocha.cn/v1/web-search", {"q": 1}, {})
    assert getattr(ei.value, "retryable", False) is True


def test_post_json_fatal_status_with_json_body_raises(monkeypatch):
    """400（非 retryable 域）带合法 JSON 体：仍必须报错，不放行为成功。"""
    captured = _Captured()
    _patch_client(
        monkeypatch, lambda r: httpx.Response(400, json={"error": "bad"}), captured)
    p = _provider()
    with pytest.raises(SearchError):
        p._post_json("https://api.bocha.cn/v1/web-search", {"q": 1}, {})


def test_post_json_scubs_key_pattern_from_error_body(monkeypatch):
    """报错脱敏：错误响应体中的 sk- 串不原样进入异常消息（ADR-8 报错脱敏）。"""
    captured = _Captured()
    _patch_client(
        monkeypatch, lambda r: httpx.Response(400, text="bad key sk-abcdef123456"),
        captured)
    p = _provider()
    with pytest.raises(SearchError) as ei:
        p._post_json("https://api.bocha.cn/v1/web-search", {"q": 1}, {})
    assert "sk-abcdef123456" not in str(ei.value)


# ---------- 注册表会话归因 ----------

def test_registry_get_provider_passes_db_to_factory(db_session):
    """get_provider 将 db 透传工厂（UA 策略读取面/计量落账依赖会话归因）。"""
    seen = {}

    def factory(**kwargs):
        seen.update(kwargs)
        return object()

    search_registry.register("cap_factory_test", factory)
    try:
        search_registry.get_provider("cap_factory_test", db_session)
    finally:
        search_registry._registry.pop("cap_factory_test", None)
    assert seen.get("db") is db_session
