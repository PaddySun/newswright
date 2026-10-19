"""安全响应头（SR-3）：security_headers 纯函数（常量防漂移）+ 全域中间件
（五头全带、CSP nonce 与页面 nonce 属性一致）。设计依据见 docs/design-index.md
「P2-5」。"""
import re

from app.api.middleware import security_headers


def _assert_five_headers(headers):
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert headers.get("Strict-Transport-Security") == "max-age=31536000"
    assert "Content-Security-Policy" in headers


def test_security_headers_pure_function():
    h = security_headers("TESTNONCE")
    assert set(h) == {
        "Content-Security-Policy", "X-Content-Type-Options",
        "X-Frame-Options", "Referrer-Policy", "Strict-Transport-Security",
    }
    csp = h["Content-Security-Policy"]
    assert "'nonce-TESTNONCE'" in csp
    for directive in (
        "default-src 'self'",
        "script-src 'self' 'nonce-TESTNONCE'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: https:",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ):
        assert directive in csp, f"CSP 缺指令: {directive}"


def test_api_response_carries_all_headers(api_client):
    r = api_client.get("/api/auth/me")  # 401 但响应头同域生效
    assert r.status_code == 401
    _assert_five_headers(r.headers)


def test_spa_host_nonce_attribute_matches_csp_header(api_client):
    """AC-3.3：/app 页 importmap 的 nonce 属性与该响应 CSP 头内 nonce 一致。"""
    r = api_client.get("/app")
    assert r.status_code == 200
    _assert_five_headers(r.headers)
    m = re.search(r"'nonce-([^']+)'", r.headers["Content-Security-Policy"])
    assert m, "CSP 头内应有 nonce"
    nonce = m.group(1)
    assert f'nonce="{nonce}"' in r.text
    # importmap 是全站唯一 inline script：nonce 属性恰好出现一次
    assert r.text.count('nonce="') == 1


def test_login_page_carries_headers(api_client):
    r = api_client.get("/login")
    assert r.status_code == 200
    _assert_five_headers(r.headers)


def test_public_page_carries_headers(api_client, db_session):
    from app.siteconfig import set_config

    set_config(db_session, "public_mode", "B")
    r = api_client.get("/public")
    assert r.status_code == 200
    _assert_five_headers(r.headers)


def test_healthz_carries_headers(api_client):
    r = api_client.get("/healthz")
    assert r.status_code in (200, 503)
    _assert_five_headers(r.headers)
    # 只补缺不覆盖语义保持：healthz 自带的契约头不受影响
    assert r.headers.get("Cache-Control") == "no-store"


def test_nonce_rotates_per_request(api_client):
    """每请求独立 nonce（不可跨请求复用）。"""
    r1 = api_client.get("/app")
    r2 = api_client.get("/app")
    n1 = re.search(r"'nonce-([^']+)'",
                   r1.headers["Content-Security-Policy"]).group(1)
    n2 = re.search(r"'nonce-([^']+)'",
                   r2.headers["Content-Security-Policy"]).group(1)
    assert n1 != n2
