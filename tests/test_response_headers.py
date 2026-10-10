"""响应头契约三段式测试（P2-4）。

路径判定域矩阵：API/状态端点 no-store；静态资源 immutable；HTML 页与 SEO
文件 no-cache, must-revalidate；healthz 自带头不被覆盖（R2 第一责任方）。
/docs 生产门禁（P1-8）：默认关闭，env DOCS_ENABLED 显式开启才提供。
设计依据见 docs/design-index.md「ADR-5」「P1-8」；纯函数判定见
app/api/middleware.py。
"""
import pytest

from app.api.middleware import (
    POLICY_IMMUTABLE,
    POLICY_NO_CACHE,
    POLICY_NO_STORE,
    cache_policy_for,
)


def test_cache_policy_pure_function_matrix():
    """纯函数路径判定矩阵（脱离 ASGI 可单测）。判定域为 HTML 白名单式（守卫
    路由双挂载后 demo 兼容形态同为 API 端点，未知路径兜底 no-store 取保守侧
    ——适配注记：兜底方向由 no-cache 反转为 no-store，语义更紧不放松）。"""
    assert cache_policy_for("/api/items") == POLICY_NO_STORE
    assert cache_policy_for("/api") == POLICY_NO_STORE
    assert cache_policy_for("/api/auth/login") == POLICY_NO_STORE
    assert cache_policy_for("/feedback") == POLICY_NO_STORE
    assert cache_policy_for("/healthz") == POLICY_NO_STORE
    assert cache_policy_for("/stream/b") == POLICY_NO_STORE   # demo 兼容形态 API
    assert cache_policy_for("/items") == POLICY_NO_STORE       # demo 兼容形态 API
    assert cache_policy_for("/stats/search") == POLICY_NO_STORE
    assert cache_policy_for("/static/css/design-system.css?v=1") == POLICY_IMMUTABLE
    assert cache_policy_for("/static/js/public-like.js") == POLICY_IMMUTABLE
    assert cache_policy_for("/public") == POLICY_NO_CACHE
    assert cache_policy_for("/public/article/1") == POLICY_NO_CACHE
    assert cache_policy_for("/login") == POLICY_NO_CACHE
    assert cache_policy_for("/app") == POLICY_NO_CACHE
    assert cache_policy_for("/sitemap.xml") == POLICY_NO_CACHE
    assert cache_policy_for("/robots.txt") == POLICY_NO_CACHE
    assert cache_policy_for("/feed.xml") == POLICY_NO_CACHE
    assert cache_policy_for("/staticfoo") == POLICY_NO_STORE  # 未知路径兜底禁缓存


def test_api_responses_carry_no_store(auth_client):
    """API 响应实带头：no-store 全域落地（登录态端点实响应断言）。"""
    import app.config as cfg

    r = auth_client.get("/api/items")
    assert r.headers["cache-control"] == POLICY_NO_STORE


def test_html_pages_carry_no_cache(auth_client, db_session):
    """HTML 页与 SEO 文件实带头：no-cache, must-revalidate（随模式配置即时
    变化的渲染面禁止陈旧缓存）。"""
    from app import siteconfig

    siteconfig.set_config(db_session, "public_mode", "B")
    db_session.commit()
    for path in ("/login", "/public", "/robots.txt", "/sitemap.xml"):
        r = auth_client.get(path)
        assert r.headers["cache-control"] == POLICY_NO_CACHE, path


def test_static_assets_carry_immutable(auth_client):
    """静态资源实带头：immutable（内容由版本 query 锚定，可永久缓存）。"""
    r = auth_client.get("/static/css/design-system.css")
    assert r.status_code == 200
    assert r.headers["cache-control"] == POLICY_IMMUTABLE


def test_healthz_header_not_overridden(api_client, db_session):
    """healthz 自带 no-store 不被中间件覆盖（第一责任方语义保持，R2）。"""
    r = api_client.get("/healthz")
    assert r.headers["cache-control"] == "no-store"


def test_docs_disabled_by_default_and_enabled_by_env(db_session, monkeypatch):
    """/docs 生产门禁（P1-8）：默认 docs/redoc/openapi 全关（404）；
    env DOCS_ENABLED=true 时恢复（开发形态）。模式 A 合规期不得泄露 API 结构。"""
    from fastapi.testclient import TestClient

    from app.auth import bootstrap_admin
    from app.main import create_app

    bootstrap_admin(db_session)
    monkeypatch.delenv("DOCS_ENABLED", raising=False)
    app_closed = create_app()
    client_closed = TestClient(app_closed)
    assert client_closed.get("/docs").status_code == 404
    assert client_closed.get("/openapi.json").status_code == 404

    monkeypatch.setenv("DOCS_ENABLED", "true")
    app_open = create_app()
    client_open = TestClient(app_open)
    assert client_open.get("/docs").status_code == 200
    assert client_open.get("/openapi.json").status_code == 200
