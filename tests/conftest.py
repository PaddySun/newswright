"""pytest 共享 fixture：每个测试独立的临时 SQLite 库。

G1 起测试环境注入 NEWSWRIGHT_ADMIN_PASSWORD（随机值，不进 git/日志）——必须在
app.config 导入前设置（config.py 缺失该变量即 SystemExit，D18/AC-01.1）。
"""
import os
import secrets

os.environ.setdefault("NEWSWRIGHT_ADMIN_PASSWORD", secrets.token_urlsafe(24))

import tempfile
from pathlib import Path

import pytest
import sqlalchemy
from sqlalchemy import create_engine

import app.config as cfg
import app.db as appdb


@pytest.fixture()
def db_session():
    tmp = Path(tempfile.mkdtemp())
    url = f"sqlite:///{(tmp / 't.db').as_posix()}"
    cfg.DATABASE_URL = url
    appdb.engine.dispose()
    appdb.engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)
    appdb.SessionLocal.configure(bind=appdb.engine)
    from app.db import init_db
    from app.db import SessionLocal as SL

    init_db()
    session = SL()
    try:
        yield session
    finally:
        session.close()
        appdb.engine.dispose()
        cfg.DATABASE_URL = f"sqlite:///{(cfg.PROJECT_ROOT / 'newswright.db').as_posix()}"


@pytest.fixture()
def api_client(db_session):
    """TestClient：走 /api/auth 前先引导 admin（每测试独立库，users 空表）。"""
    from fastapi.testclient import TestClient

    from app.auth import bootstrap_admin

    bootstrap_admin(db_session)
    import app.api.auth as auth_mod

    auth_mod.login_limiter._store.clear()  # 限速器进程内状态不跨测试泄漏
    from app.main import app

    return TestClient(app)


@pytest.fixture()
def auth_client(api_client):
    """已完成首改密的已登录 client（AC-01.5 后状态：cookie 有效 + must_change_password=false）。"""
    import app.config as cfg

    r = api_client.post("/api/auth/login",
                        json={"username": "admin", "password": cfg.NEWSWRIGHT_ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    new_password = "g1-test-" + secrets.token_urlsafe(12)
    r = api_client.post("/api/auth/password",
                        json={"old_password": cfg.NEWSWRIGHT_ADMIN_PASSWORD,
                              "new_password": new_password})
    assert r.status_code == 200, r.text
    return api_client


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """测试零出网结构性封禁：把 httpx 的真实网络传输层替换为抛 AssertionError 的哨兵。

    DeepSeekProvider（LLM）/ MoarkEmbedding（嵌入）/ 搜索 / 排序的出网方法全部经
    httpx Client POST 触达真实传输层——漏打桩的调用在这里当场红，而不是真发请求。
    三类既有打桩形态不受影响：替换 httpx.Client 类的假客户端、实例级替换
    _post/_post_json、FastAPI TestClient 的 ASGI 传输，均不经过真实传输层。
    """
    import httpx

    def _blocked(self, request):
        raise AssertionError(
            "测试出网封禁：真实 HTTP 传输被禁用（LLM/嵌入/搜索/排序 provider 必须打桩）。"
            f"目标: {request.url}"
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked, raising=True)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _blocked, raising=True)
