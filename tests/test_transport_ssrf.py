"""SSRF 三件套测试（BE-4/AC-1）：私网判定（IANA 保留网段黑名单+IPv4-mapped
归一+简写字面量+解析失败 fail-closed）、GET-only 拒绝 hook（重定向每一跳
拦截）、fetch_allow_private 放行口、工厂接线与富化面零改收编。

网络纪律：零真 DNS（IP 字面量直判/resolver 注入）、零出网（MockTransport）。
设计依据见 docs/design-index.md「TG-1」（BE-4 增补）。
"""
import logging
from functools import partial

import httpx
import pytest

import app.transport.throttle as throttle_mod
from app.siteconfig import DEFAULTS, set_config
from app.transport.http import http_client
from app.transport.ssrf import (
    PrivateAddressError,
    is_public_host,
    refuse_private_destination,
)


@pytest.fixture(autouse=True)
def _reset_process_state():
    """进程态复位判例（节流表与 hooks 同挂工厂，防测试间串台）。"""
    throttle_mod._reset_for_tests()
    yield
    throttle_mod._reset_for_tests()


# ---------- 判定函数：IP 字面量黑名单 ----------

PRIVATE_LITERAL_HOSTS = [
    # 环回（含 IPv4 简写 127.1 / 十进制 2130706433——ipaddress 原生覆盖）
    "127.0.0.1", "127.1", "2130706433", "127.255.255.254",
    # 私网三段
    "10.0.0.1", "172.16.0.1", "172.31.255.255", "192.168.1.1",
    # 链路本地（含云元数据 169.254.169.254）
    "169.254.169.254", "169.254.0.1",
    # CGNAT 共享地址段
    "100.64.0.1", "100.127.255.255",
    # 本特殊网 0.0.0.0/8
    "0.0.0.0", "0.1.2.3",
    # 组播与保留段（含广播）
    "224.0.0.1", "239.255.255.254", "240.0.0.1", "255.255.255.255",
    # 文档段 / 基准测试段 / IETF 协议分配段
    "192.0.2.1", "198.51.100.1", "203.0.113.9", "198.18.0.1", "192.0.0.9",
    # IPv6：环回/未指定/链路本地/唯一本地/组播/文档段
    "::1", "::", "fe80::1", "fd12:3456:789a::1", "fc00::1", "ff02::1",
    "2001:db8::1",
    # IPv4-mapped IPv6（先归一再查 v4 黑名单）
    "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:169.254.169.254",
]

PUBLIC_LITERAL_HOSTS = [
    "8.8.8.8", "1.1.1.1", "93.184.216.34",
    "2606:4700::1111", "2001:4860:4860::8888",
]


@pytest.mark.parametrize("host", PRIVATE_LITERAL_HOSTS)
def test_private_literals_rejected(host):
    """私网/环回/链路本地/组播/保留/CGNAT/文档段字面量全拒（零 DNS）。"""
    assert is_public_host(host) is False


@pytest.mark.parametrize("host", PUBLIC_LITERAL_HOSTS)
def test_public_literals_allowed(host):
    assert is_public_host(host) is True


def test_empty_host_rejected():
    """空 host 安全缺省拒绝。"""
    assert is_public_host("") is False
    assert is_public_host(None) is False  # type: ignore[arg-type]


# ---------- 判定函数：解析路径（resolver 注入，零真 DNS） ----------


def test_domain_resolving_to_public_allowed():
    assert is_public_host("example.com", resolver=lambda h: ["93.184.216.34"]) is True


def test_domain_with_any_private_record_rejected():
    """多记录夹带任一私网地址即整体拒绝（DNS rebinding 多记录形态）。"""
    got = []
    def mixed(host: str) -> list[str]:
        got.append(host)
        return ["93.184.216.34", "10.0.0.5"]
    assert is_public_host("mixed.example", resolver=mixed) is False
    assert got == ["mixed.example"]


def test_domain_resolution_failure_fail_closed():
    """resolver 抛错/空结果 → False（fail-closed：宁可误拒不放过）。"""
    def boom(host: str) -> list[str]:
        raise OSError("name resolution failure")
    assert is_public_host("nx.example", resolver=boom) is False
    assert is_public_host("empty.example", resolver=lambda h: []) is False


def test_domain_resolver_bad_value_fail_closed():
    """resolver 返回非法地址值 → False。"""
    assert is_public_host("bad.example", resolver=lambda h: ["not-an-ip"]) is False


# ---------- hook：GET-only 拒绝与放行口 ----------


def _get_req(url: str) -> httpx.Request:
    return httpx.Request("GET", url)


def test_hook_rejects_private_get_names_host_and_toggle():
    with pytest.raises(PrivateAddressError) as ei:
        refuse_private_destination(_get_req("http://127.0.0.1:9999/x"))
    assert "127.0.0.1" in str(ei.value)
    assert "fetch_allow_private" in str(ei.value)


def test_hook_allows_post_to_private():
    """POST 面零设防（自有 API 域——设计而非遗漏）：私网 POST 不抛不解析。"""
    req = httpx.Request("POST", "http://127.0.0.1:8000/v1/chat", json={"q": 1})
    refuse_private_destination(req)  # 不抛即过


def test_hook_allows_public_get():
    refuse_private_destination(_get_req("http://8.8.8.8/ok"))


def test_hook_domain_via_injected_resolver():
    """hook 的 resolver 注入位：域名目标按解析结果判。"""
    req = _get_req("http://evil.example/doc")
    with pytest.raises(PrivateAddressError):
        refuse_private_destination(req, resolver=lambda h: ["10.0.0.9"])


def test_fetch_allow_private_toggle_permits(db_session, caplog):
    """放行口：site_config fetch_allow_private=True 时私网 GET 放行+log.info。"""
    set_config(db_session, "fetch_allow_private", True)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="internal doc")

    hook = partial(refuse_private_destination, db=db_session)
    with httpx.Client(transport=httpx.MockTransport(handler),
                      event_hooks={"request": [hook]}) as client:
        with caplog.at_level(logging.INFO, logger="app.transport.ssrf"):
            resp = client.get("http://10.20.30.40/x")
    assert resp.status_code == 200
    assert any("fetch_allow_private" in r.getMessage() for r in caplog.records)


def test_fetch_allow_private_default_off_in_defaults():
    """缺省 False：不放行（站长未示内网源场景，最简全局开关）。"""
    assert DEFAULTS["fetch_allow_private"] is False


# ---------- hook 语义：重定向每一跳拦截 + httpx 捕获面收编 ----------


def test_private_address_error_in_httpx_capture_face():
    """继承 httpx.TransportError——既有 except httpx.HTTPError 捕获面零改收编。"""
    assert issubclass(PrivateAddressError, httpx.TransportError)
    try:
        raise PrivateAddressError("x")
    except httpx.HTTPError:
        pass  # 收编成立


def test_redirect_hop_to_private_blocked():
    """公网 302 → 私网目标：重定向第二跳被 hook 拦截（httpx 每跳发前过检）。"""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "93.184.216.34":
            return httpx.Response(
                302, headers={"Location": "http://169.254.169.254/latest/meta-data"})
        return httpx.Response(200, text="leaked")

    with httpx.Client(transport=httpx.MockTransport(handler),
                      event_hooks={"request": [refuse_private_destination]},
                      follow_redirects=True) as client:
        with pytest.raises(PrivateAddressError):
            client.get("http://93.184.216.34/hop")


# ---------- 工厂接线（真实 http_client 全路径，MockTransport 零出网） ----------


def test_factory_get_to_private_refused(db_session):
    """统筹冒烟同款形态：真工厂 GET http://127.0.0.1:9999/x → 拒绝。"""
    client = http_client(db_session,
                         transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    try:
        with pytest.raises(PrivateAddressError):
            client.get("http://127.0.0.1:9999/x")
    finally:
        client.close()


def test_factory_post_to_private_not_blocked(db_session):
    """工厂 POST 面（腾讯/池化 JSON 域同形态）零误伤：hook 放行非 GET。"""
    client = http_client(
        db_session,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"Response": {}})))
    try:
        resp = client.post("http://127.0.0.1:9999/v1/xxx", json={})
        assert resp.status_code == 200
    finally:
        client.close()


def test_enrich_private_url_keeps_summary(db_session, monkeypatch):
    """A1 语义回归：enrich 条目 URL 指向私网 → SSRF 拒绝 → 保留摘要不致命。"""
    import app.ingest.web as web_mod
    from app.transport.http import http_client as real_factory

    mock = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>长正文</html>"))
    monkeypatch.setattr(web_mod, "http_client",
                        lambda db=None, **kw: real_factory(db, transport=mock, **kw))
    out = web_mod.enrich_entry_text(
        "http://127.0.0.1:8000/doc", "短摘要",
        page_url="https://public.example/list", db=db_session)
    assert out == "短摘要"
