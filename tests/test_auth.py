"""G1/W1 认证与会话测试（AC-01.1~01.5；技术书 §8 映射表行 01.1-01.5）。

会话过期用 site_config 缩短期限等价验证（AC-01.4），不真等 7 天；
登录限速冷却用注入时钟等价验证，不真等 15 分钟。
"""
import secrets
from datetime import datetime, timedelta, timezone

import app.api.auth as auth_mod
import app.config as cfg
from app import siteconfig
from app.db import SessionLocal
from app.models import User, UserSession


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite 取回 naive


def _login(client, password=None):
    return client.post("/api/auth/login",
                       json={"username": "admin",
                             "password": password or cfg.NEWSWRIGHT_ADMIN_PASSWORD})


def test_login_ok(api_client):
    """AC-01.1b：正确凭据 → 200 + HttpOnly 会话 cookie + {"username":"admin"}。"""
    r = _login(api_client)
    assert r.status_code == 200
    assert r.json() == {"username": "admin"}
    set_cookie = r.headers["set-cookie"]
    assert "nw_session=" in set_cookie and "HttpOnly" in set_cookie and "Path=/" in set_cookie
    # 会话行已落库且未过期（默认保持期限 7 天）
    with SessionLocal() as db:
        row = db.get(UserSession, api_client.cookies["nw_session"])
        assert row is not None
        assert timedelta(days=6) < _aware(row.expires_at) - datetime.now(timezone.utc) <= timedelta(days=7)


def test_login_wrong_password(api_client):
    """AC-01.2 前半：错误密码 → 401 {"code":"AUTH_INVALID"}（规范 4XX，D11）。"""
    r = _login(api_client, "wrong-pass")
    assert r.status_code == 401
    assert r.json()["code"] == "AUTH_INVALID"


def test_rate_limit_429(api_client, monkeypatch):
    """AC-01.2 后半：连续 5 次失败后第 6 次起 429 AUTH_RATE_LIMITED；冷却 15 分钟后恢复。
    冷却用注入时钟等价验证。"""
    base = datetime.now(timezone.utc)
    clock = {"t": base}
    monkeypatch.setattr(auth_mod.login_limiter, "now", lambda: clock["t"])

    for _ in range(5):
        r = _login(api_client, "wrong-pass")
        assert r.status_code == 401
    # 第 6 次：即使密码正确也 429
    r = _login(api_client)
    assert r.status_code == 429
    assert r.json()["code"] == "AUTH_RATE_LIMITED"
    # 冷却期内仍 429
    clock["t"] = base + timedelta(minutes=14)
    assert _login(api_client).status_code == 429
    # 冷却结束（15 分钟后）恢复，正确密码可登录
    clock["t"] = base + timedelta(minutes=16)
    assert _login(api_client).status_code == 200


def test_session_expiry_short_duration(api_client):
    """AC-01.4：site_config session_duration_days 缩短 → 会话按配置签发
    （负值 = 签发即过期，等价验证；受保护端点的 401 断言见 protected 用例）。"""
    assert _login(api_client).status_code == 200
    with SessionLocal() as db:
        siteconfig.set_config(db, "session_duration_days", -1)
    api_client.cookies.clear()
    assert _login(api_client).status_code == 200
    with SessionLocal() as db:
        row = db.get(UserSession, api_client.cookies["nw_session"])
        assert _aware(row.expires_at) <= datetime.now(timezone.utc)  # 已按配置过期


def test_protected_401(api_client):
    """AC-01.3：未携带会话 cookie 访问既有受保护端点 → 401 AUTH_REQUIRED。"""
    r = api_client.get("/items")
    assert r.status_code == 401
    assert r.json()["code"] == "AUTH_REQUIRED"


def test_first_login_gating_403(api_client):
    """AC-01.1：首登未改密时除 /api/auth/* 外一切 API → 403 PASSWORD_CHANGE_REQUIRED；
    改密后同端点放行。"""
    assert _login(api_client).status_code == 200  # 初始 admin：must_change_password=true
    r = api_client.get("/items")
    assert r.status_code == 403
    assert r.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    # 改密端点本身放行（豁免端点），完成后门禁解除
    r = api_client.post("/api/auth/password",
                        json={"old_password": cfg.NEWSWRIGHT_ADMIN_PASSWORD,
                              "new_password": "g1-new-" + secrets.token_urlsafe(8)})
    assert r.status_code == 200
    assert api_client.get("/items").status_code == 200


def test_expired_session_401_on_protected(api_client):
    """AC-01.4 收尾：过期会话访问受保护端点 → 401 AUTH_REQUIRED（期限缩短等价验证）。"""
    with SessionLocal() as db:
        siteconfig.set_config(db, "session_duration_days", -1)
    assert _login(api_client).status_code == 200  # 签发即过期
    r = api_client.get("/items")
    assert r.status_code == 401
    assert r.json()["code"] == "AUTH_REQUIRED"


def test_change_password(api_client):
    """AC-01.5：改密 → 200 + must_change_password=false；旧密码立即可验证失效。"""
    assert _login(api_client).status_code == 200
    new_password = "g1-new-" + secrets.token_urlsafe(8)
    r = api_client.post("/api/auth/password",
                        json={"old_password": cfg.NEWSWRIGHT_ADMIN_PASSWORD,
                              "new_password": new_password})
    assert r.status_code == 200
    assert r.json()["must_change_password"] is False

    with SessionLocal() as db:
        user = db.query(User).filter_by(username="admin").one()
        assert user.must_change_password is False

    # 旧密码立即可验证失效（AC-01.5 口径：旧密码登录落 401）；新密码可登录
    api_client.cookies.clear()
    r = _login(api_client)
    assert r.status_code == 401 and r.json()["code"] == "AUTH_INVALID"
    assert _login(api_client, new_password).status_code == 200
