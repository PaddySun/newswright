"""改密吊销全部旧会话（SR-2）：双会话场景——会话 B 改密 → 会话 A 的
cookie 立即 401、B 持新 cookie 继续 200；响应体含 sessions_revoked；
docstring 不再自认「旧会话不强制失效」。设计依据见 docs/design-index.md「AC-01.5」。
"""
import secrets

from fastapi.testclient import TestClient

import app.config as cfg
from app.auth import COOKIE_NAME
from app.models import UserSession


def _new_client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_password_change_revokes_all_other_sessions(api_client, db_session):
    """双会话：B 改密 → A 立即 401（全吊销）+ B 换发新 cookie 继续 200。"""
    r = api_client.post("/api/auth/login", json={
        "username": "admin", "password": cfg.NEWSWRIGHT_ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    pw1 = "be1-a-" + secrets.token_urlsafe(12)
    r = api_client.post("/api/auth/password", json={
        "old_password": cfg.NEWSWRIGHT_ADMIN_PASSWORD, "new_password": pw1})
    assert r.status_code == 200, r.text
    cookie_a = api_client.cookies.get(COOKIE_NAME)

    client_b = _new_client()
    r = client_b.post("/api/auth/login", json={
        "username": "admin", "password": pw1})
    assert r.status_code == 200, r.text
    cookie_b = client_b.cookies.get(COOKIE_NAME)
    assert cookie_a and cookie_b and cookie_a != cookie_b

    pw2 = "be1-b-" + secrets.token_urlsafe(12)
    r = client_b.post("/api/auth/password", json={
        "old_password": pw1, "new_password": pw2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sessions_revoked"] == 2  # A 与 B 的旧行全部删除
    assert body["must_change_password"] is False
    cookie_b2 = client_b.cookies.get(COOKIE_NAME)
    assert cookie_b2 and cookie_b2 != cookie_b  # 当前连接不断：换发新会话

    client_a = _new_client()
    client_a.cookies.set(COOKIE_NAME, cookie_a)
    assert client_a.get("/api/auth/me").status_code == 401  # 旧 cookie 立即失效
    assert client_b.get("/api/auth/me").status_code == 200  # 新 cookie 存活

    # sessions 表只剩 B 的新会话一行
    assert db_session.query(UserSession).count() == 1


def test_password_change_single_session_revoked_count(api_client):
    """单会话改密：吊销计数含当前会话自身（全删再换发）。"""
    r = api_client.post("/api/auth/login", json={
        "username": "admin", "password": cfg.NEWSWRIGHT_ADMIN_PASSWORD})
    assert r.status_code == 200
    r = api_client.post("/api/auth/password", json={
        "old_password": cfg.NEWSWRIGHT_ADMIN_PASSWORD,
        "new_password": "be1-c-" + secrets.token_urlsafe(12)})
    assert r.status_code == 200
    assert r.json()["sessions_revoked"] == 1
    # 换发后当前连接不断（新 cookie 可用）
    assert api_client.get("/api/auth/me").status_code == 200


def test_password_change_wrong_old_password_no_revocation(api_client):
    """旧密码错误 → 401 且不吊销任何会话（改密未成功不动会话面）。"""
    r = api_client.post("/api/auth/login", json={
        "username": "admin", "password": cfg.NEWSWRIGHT_ADMIN_PASSWORD})
    assert r.status_code == 200
    r = api_client.post("/api/auth/password", json={
        "old_password": "wrong-old-password",
        "new_password": "be1-d-" + secrets.token_urlsafe(12)})
    assert r.status_code == 401
    assert "sessions_revoked" not in r.json()
    assert api_client.get("/api/auth/me").status_code == 200


def test_password_change_docstring_no_stale_claim():
    """docstring 同步：不得再自认「旧会话不强制失效」。"""
    from app.api import auth as auth_api

    assert "旧会话不强制失效" not in auth_api.auth_password.__doc__
