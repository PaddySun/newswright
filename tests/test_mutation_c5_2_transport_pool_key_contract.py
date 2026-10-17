"""传输脊客户端池键与构造参数契约（transport.http）：TR-6 六元键补面。

背景（外部服务治理批后的传输脊条款）：JSON API 出网客户端按
（源, 鉴权头, 超时, 生效 UA, 客户端工厂, 重定向策略）六元键进程级复用、
双检锁线程安全。既有测试覆盖了同键复用/UA 值入键/工厂身份/线程安全主干，
本文件补齐：①鉴权头成分入键（不同鉴权不得并池复用同一客户端——POST 与
GET 两面）；②键整体不得塌缩（不同源请求各自构造）；③构造参数与池键成分
一致（超时原样进构造、POST 面重定向策略恒不跟随）；④GET 面/db 会话的
生效 UA 按站点策略解析（含 provider 出网经 self.db 传递会话的半边）；
⑤锁内二次检查命中已入池客户端即复用（竞态窗口不重复构造）。
设计依据见 docs/design-index.md「TR-6」「TR-2」「HR-1」「R9」。
"""
import httpx
import pytest

from app.providers.base import HTTPProvider
from app.siteconfig import set_config
from app.transport import http as transport_http
from app.transport.errors import TransportError

_URL_ORIGIN = "https://api.example.com"
_AUTH = {"Authorization": "Bearer k-one", "Content-Type": "application/json"}
_AUTH2 = {"Authorization": "Bearer k-two", "Content-Type": "application/json"}
_URL = _URL_ORIGIN + "/v1/chat/completions"
_URL2 = "https://other.example.com/v1/x"


@pytest.fixture(autouse=True)
def _fresh_client_pool():
    transport_http.reset_client_pool()
    yield
    transport_http.reset_client_pool()


def _factory_with(handler, constructions: list, kwargs_log: list | None = None):
    def factory(**kwargs):
        constructions.append(1)
        if kwargs_log is not None:
            kwargs_log.append(dict(kwargs))
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    return factory


def _ok_handler(request):
    return httpx.Response(200, json={"ok": 1})


# ---------- 鉴权头成分入键（POST / GET 两面） ----------

def test_post_json_authorization_is_pool_key_component():
    """POST 面：同源不同鉴权头各自构造客户端（鉴权头是六元键成分——
    请求级 headers 不携带鉴权语义时，池必须按鉴权分客户端）。"""
    c: list = []
    f = _factory_with(_ok_handler, c)
    transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0, client_factory=f)
    transport_http.post_json(_URL, {}, headers=_AUTH2, timeout=5.0, client_factory=f)
    assert len(c) == 2  # 鉴权不同 → 不同键 → 各自构造


def test_get_json_authorization_is_pool_key_component():
    """GET 面：同源不同鉴权头各自构造客户端（与 POST 面同规；鉴权取值按
    标准驼峰键名 "Authorization" 精确读取——取不到会并键只构造一次）。"""
    c: list = []
    f = _factory_with(_ok_handler, c)
    transport_http.get_json(_URL, headers=_AUTH, timeout=5.0, client_factory=f)
    transport_http.get_json(_URL, headers=_AUTH2, timeout=5.0, client_factory=f)
    assert len(c) == 2


# ---------- 键整体不塌缩 / 构造参数保真 ----------

def test_get_json_different_origins_build_separate_clients():
    """GET 面不同源（origin）各自构造客户端：池键整体不塌缩为单键。"""
    c: list = []
    f = _factory_with(_ok_handler, c)
    transport_http.get_json(_URL, timeout=5.0, client_factory=f)
    transport_http.get_json(_URL2, timeout=5.0, client_factory=f)
    assert len(c) == 2


def test_get_json_pool_call_carries_key_and_requested_timeout():
    """GET 面池取用：传入真实池键（非 None）且超时原样进构造参数
    （构造参数=池键成分——调用方显式超时不得在池化时丢失）。"""
    c: list = []
    kw: list = []
    f = _factory_with(_ok_handler, c, kw)
    transport_http.get_json(_URL, timeout=5.0, client_factory=f)
    assert kw[0]["timeout"] == 5.0


def test_post_json_pool_client_never_follows_redirects():
    """POST 面池客户端构造参数 follow_redirects 恒 False：JSON API POST
    面 3xx 必须在传输脊内拦截入错（跟随即网关 302 营销站漏网形态复现）。"""
    captured: dict = {}

    class RecordingClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def post(self, url, **kwargs):
            return httpx.Response(200, json={"ok": 1})

    transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0,
                             client_factory=RecordingClient)
    assert captured["follow_redirects"] is False


def test_post_and_follow_get_pools_stay_isolated():
    """重定向策略入池键且两策略各自池化：GET（跟随）入池的客户端不得
    被 POST（不跟随）复用——否则 POST 302 被跟随成「成功空响应」
    （TR-6：两种策略各自池化不串台；POST 面 3xx 脊内拦截）。"""

    def handler(request):
        if request.url.path == "/redir":
            return httpx.Response(302, headers={"location": _URL_ORIGIN + "/landed"})
        return httpx.Response(200, json={"ok": 1})

    constructions: list = []
    factory = _factory_with(handler, constructions)
    # GET 面跟随重定向（终态 200 入池，键第六元=True）
    resp = transport_http.get_json(_URL_ORIGIN + "/redir", headers=_AUTH,
                                   timeout=5.0, client_factory=factory)
    assert resp.status_code == 200
    # 同源同鉴权同超时 POST 走 302：必须新构造不跟随客户端并按
    # 可重试 TransportError 入错（若与 GET 池串台，302 会被跟随成 200）
    with pytest.raises(TransportError):
        transport_http.post_json(_URL_ORIGIN + "/redir", {}, headers=_AUTH,
                                 timeout=5.0, client_factory=factory)


def test_collect_client_factory_defaults_to_follow_redirects(monkeypatch):
    """采集通道客户端工厂（http_client）：follow_redirects 缺省 True——
    采集 GET 面跟随重定向、以终态语义判定（既有行为，治理批后成条款）。"""
    captured: dict = {}
    real_client = httpx.Client

    def recording_client(**kwargs):
        captured.update(kwargs)
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "Client", recording_client)
    transport_http.http_client().close()
    assert captured["follow_redirects"] is True


# ---------- 生效 UA 按站点策略解析（GET 面 / provider 出网） ----------

def test_get_json_resolves_user_agent_from_site_config(db_session):
    """GET 面生效 UA 按 site_config 策略解析：db 会话传入时 custom UA
    生效（策略键→UA 值的解析半边在 GET 面同样成立）。"""
    set_config(db_session, "ua_strategy", "custom")
    set_config(db_session, "ua_custom", "MyAgent/9.9 (+https://me.example)")
    c: list = []
    kw: list = []
    f = _factory_with(_ok_handler, c, kw)
    transport_http.get_json(_URL, timeout=5.0, db=db_session, client_factory=f)
    assert "MyAgent/9.9" in kw[0]["headers"]["User-Agent"]


def test_http_provider_post_json_passes_session_for_ua(db_session, monkeypatch):
    """HTTPProvider._post_json 把 provider 会话透传给传输脊 post_json
    （db=None 会让出网 UA 退化为无邮箱诚实形态——站点 UA 策略随会话传递）。"""
    captured: dict = {}

    def fake_post_json(url, payload, *, headers, timeout, db=None,
                       client_factory=None):
        captured["db"] = db
        return httpx.Response(200, json={"ok": 1})

    import app.providers.base as base_mod
    monkeypatch.setattr(base_mod, "post_json", fake_post_json)

    class _Probe(HTTPProvider):
        name = "probe"

        def _post(self, payload):
            return {}, {}

    probe = _Probe(db_session, base_url="https://api.test", api_key="k")
    probe._post_json("/x", {})
    assert captured["db"] is db_session


# ---------- 双检锁：锁内二次检查命中即复用 ----------

def test_pooled_client_second_check_reuses_pooled_instance(monkeypatch):
    """锁内二次检查：外层快路径 miss（竞态窗口内另一线程已入池）时，
    锁内复查命中已入池客户端即复用、不再构造（双检锁的语义半边）。
    桩按锁持有状态分流：外层 get 恒 miss、锁内 get 返回真池——模拟
    「外层查时池空、进锁时他线程已入池」的竞态窗口（确定性观测）。"""
    import threading
    pooled = object()
    real_pool = {("k",): pooled}
    lock_state = {"held": False}
    real_lock = threading.Lock()

    class HeldAwareLock:
        def __enter__(self):
            lock_state["held"] = True
            return real_lock.__enter__()

        def __exit__(self, *exc):
            lock_state["held"] = False
            return real_lock.__exit__(*exc)

    class RaceWindowPool(dict):
        def get(self, key):
            if lock_state["held"]:      # 锁内复查：他线程已入池
                return real_pool.get(key)
            return None                 # 外层快路径：窗口内仍空

    monkeypatch.setattr(transport_http, "_pool_lock", HeldAwareLock())
    monkeypatch.setattr(transport_http, "_client_pool", RaceWindowPool())
    constructions: list = []

    def factory(**kwargs):
        constructions.append(1)
        return object()

    client = transport_http._pooled_client(
        ("k",), factory, timeout=5.0, user_agent="ua", follow_redirects=False)
    assert client is pooled       # 锁内复查命中 → 复用既有客户端
    assert constructions == []    # 不重复构造
