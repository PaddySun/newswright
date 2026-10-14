"""登出与会话身份测试（UI2 W0c / 全局登出与会话引导）。

契约：POST /api/auth/logout 删当前会话行 + Set-Cookie 清除 nw_session
（Max-Age=0，与登录 cookie 同属性域）；无会话/已过期也 200 幂等。
GET /api/auth/me 有有效会话 → {"username","must_change_password"}；无/过期
→ 401 coded AUTH_REQUIRED；me 不受首登改密门禁拦截（must_change_password
字段正是给前端引导改密用——语义=查身份而非用功能）。
"""
import secrets

import app.config as cfg
from app.db import SessionLocal
from app.models import UserSession


def test_logout_deletes_session_row_and_clears_cookie(auth_client):
    """登出：会话行删除 + Set-Cookie Max-Age=0 清除 nw_session；登出后原
    cookie 再访问受保护端点 → 401（会话已吊销）。"""
    sid = auth_client.cookies["nw_session"]
    with SessionLocal() as db:
        assert db.get(UserSession, sid) is not None  # 前置：会话行在库
    r = auth_client.post("/api/auth/logout")
    assert r.status_code == 200
    assert r.json() == {"logged_out": True}
    set_cookie = r.headers["set-cookie"]
    assert "nw_session=" in set_cookie and "Max-Age=0" in set_cookie
    assert "HttpOnly" in set_cookie and "Path=/" in set_cookie  # 同属性域
    with SessionLocal() as db:
        assert db.get(UserSession, sid) is None  # 行已删
    r = auth_client.get("/api/items")
    assert r.status_code == 401
    assert r.json()["code"] == "AUTH_REQUIRED"


def test_logout_idempotent_without_session(api_client):
    """无会话登出 → 200 {"logged_out": true}（幂等，不报错）。"""
    r = api_client.post("/api/auth/logout")
    assert r.status_code == 200
    assert r.json() == {"logged_out": True}


def test_logout_expired_session_still_ok(api_client):
    """已过期会话登出 → 200 幂等且过期行被清理（无害的顺带回收）。"""
    assert api_client.post("/api/auth/login",
                           json={"username": "admin",
                                 "password": cfg.NEWSWRIGHT_ADMIN_PASSWORD}
                           ).status_code == 200
    sid = api_client.cookies["nw_session"]
    from datetime import datetime, timedelta, timezone

    with SessionLocal() as db:
        row = db.get(UserSession, sid)
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    r = api_client.post("/api/auth/logout")
    assert r.status_code == 200
    assert r.json() == {"logged_out": True}


def test_me_with_session_after_password_changed(auth_client):
    """me：有效会话（已改密）→ 200 + must_change_password=false。"""
    r = auth_client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json() == {"username": "admin", "must_change_password": False}


def test_me_with_session_before_password_changed(api_client):
    """me：首登未改密会话 → 200 且 must_change_password=true——不受改密门禁
    拦截（该字段正是前端引导改密的依据）。"""
    assert api_client.post("/api/auth/login",
                           json={"username": "admin",
                                 "password": cfg.NEWSWRIGHT_ADMIN_PASSWORD}
                           ).status_code == 200
    r = api_client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json() == {"username": "admin", "must_change_password": True}


def test_me_without_session_401_coded(api_client):
    """me：无会话 → 401 coded AUTH_REQUIRED。"""
    r = api_client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["code"] == "AUTH_REQUIRED"


def test_me_expired_session_401(api_client):
    """me：过期会话 → 401 AUTH_REQUIRED（get_valid_session 过期即 None）。"""
    assert api_client.post("/api/auth/login",
                           json={"username": "admin",
                                 "password": cfg.NEWSWRIGHT_ADMIN_PASSWORD}
                           ).status_code == 200
    from datetime import datetime, timedelta, timezone

    with SessionLocal() as db:
        row = db.get(UserSession, api_client.cookies["nw_session"])
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    r = api_client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["code"] == "AUTH_REQUIRED"
