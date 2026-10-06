"""匿名访客身份测试（产品书 §0 匿名反馈去重决策，设计依据见
docs/design-index.md「D7」）：HttpOnly cookie 签发 + visitor_hash 主备双链
（cookie 优先、IP+UA 哈希兜底——只用 IP 会把 NAT 下全体访客误并为一个身份）。
"""
import httpx
import pytest

from app.api.deps import VISITOR_COOKIE_NAME, get_client_ip, visitor_hash


class _FakeRequest:
    def __init__(self, *, cookies=None, headers=None, client_host="203.0.113.7"):
        self.cookies = cookies or {}
        self.headers = httpx.Headers(headers or {})  # 大小写不敏感（同真实请求头）
        self.client = type("C", (), {"host": client_host})()


def test_visitor_hash_prefers_cookie():
    req = _FakeRequest(cookies={VISITOR_COOKIE_NAME: "abc123"},
                       headers={"user-agent": "UA/1"}, client_host="1.2.3.4")
    assert visitor_hash(req) == "cookie:abc123"


def test_visitor_hash_falls_back_to_ip_ua_hash():
    req = _FakeRequest(headers={"user-agent": "UA/1"}, client_host="203.0.113.7")
    h1 = visitor_hash(req)
    assert h1.startswith("anon:")
    # 同 IP 同 UA → 同身份（兜底链稳定）
    assert visitor_hash(_FakeRequest(headers={"user-agent": "UA/1"},
                                     client_host="203.0.113.7")) == h1


def test_visitor_hash_ip_only_merges_nat_visitors():
    """只用 IP 的反面证：NAT 出口同 IP、不同 UA 的两访客——IP+UA 链可区分
    （纯 IP 会误并为一个身份，一人点赞即全员 already_counted）。"""
    a = visitor_hash(_FakeRequest(headers={"user-agent": "UA/A"},
                                  client_host="198.51.100.9"))
    b = visitor_hash(_FakeRequest(headers={"user-agent": "UA/B"},
                                  client_host="198.51.100.9"))
    assert a != b


def test_visitor_hash_uses_configured_client_ip_header(db_session):
    """兜底链复用 get_client_ip 单一实现（配置头优先——与登录限速同口径）。"""
    from app.siteconfig import set_config

    set_config(db_session, "client_ip_header", "CF-Connecting-IP")
    req = _FakeRequest(headers={"user-agent": "UA/1", "cf-connecting-ip": "203.0.113.99"},
                       client_host="10.0.0.1")
    h_via_header = visitor_hash(req, db_session)
    assert h_via_header != visitor_hash(_FakeRequest(headers={"user-agent": "UA/1"},
                                                     client_host="10.0.0.1"), db_session)
    assert get_client_ip(req, db_session) == "203.0.113.99"


def test_visitor_cookie_issued_on_first_visit_and_stable(api_client):
    """中间件签发：首访响应带 Set-Cookie（HttpOnly）；带 cookie 复访不重签。"""
    r1 = api_client.get("/healthz")
    set_cookie = r1.headers.get("set-cookie", "")
    assert VISITOR_COOKIE_NAME in set_cookie and "HttpOnly" in set_cookie

    api_client.cookies.set(VISITOR_COOKIE_NAME, "fixed-id")
    r2 = api_client.get("/healthz")
    assert VISITOR_COOKIE_NAME not in (r2.headers.get("set-cookie") or "")
