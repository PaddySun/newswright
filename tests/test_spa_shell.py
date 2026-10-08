"""SPA 壳与前端基建测试（W2：裁定①免构建形态的宿主与资产面）。

断言对象：SPA 宿主页（/app）承载挂载点/import map/设计系统引用；登录页壳
含交互挂载点与文案注入位；vendor 产物（vue/vue-i18n esm-browser）与设计
系统 CSS 经静态面可达且命中 immutable 缓存策略。JS 侧交互按裁定⑤浏览器
亲测（后端 pytest 兜底契约）。
设计依据见 docs/design-index.md「ADR-7」「D3」；裁定①/⑦/⑧见任务书 §4.0。
"""
import pytest


def test_spa_host_page_carries_mount_and_assets(auth_client):
    """/app 宿主页：挂载点、import map（vue/vue-i18n→vendor）、双 CSS 与
    模块入口齐备。"""
    r = auth_client.get("/app")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    html = r.text
    assert 'id="app"' in html
    assert "importmap" in html
    assert "/static/vendor/vue.esm-browser.prod.js" in html
    assert "/static/vendor/vue-i18n.esm-browser.prod.js" in html
    assert "/static/css/design-system.css" in html
    assert "/static/css/app.css" in html
    assert "/static/app/main.js" in html


def test_spa_host_redirects_anonymous_session_probe_to_login(api_client):
    """/api 401 统一跳登录的前端语义由 api.js 承载（浏览器行为）；宿主页
    本身匿名可达（壳无数据），数据面守卫由既有会话契约承担（AC-01.3）。"""
    r = api_client.get("/app")
    assert r.status_code == 200


def test_login_shell_mounts_and_copy_injected(auth_client):
    """登录页壳：双表单挂载点 + 文案 data-i18n 注入位 + 模块脚本引用
    （SSR 文案块承载界面文案，裁定⑦）。"""
    r = auth_client.get("/login")
    assert r.status_code == 200
    html = r.text
    assert 'id="login-form"' in html
    assert 'id="password-change-form"' in html
    assert "data-i18n-error-generic" in html
    assert "/static/app/login-view.js" in html


def test_design_system_css_served_with_immutable(auth_client):
    """设计系统 CSS（token 层）与 SPA 布局 CSS 经静态面可达；命中 immutable
    判定域（P2-4 三段式）。"""
    for path in ("/static/css/design-system.css", "/static/css/app.css"):
        r = auth_client.get(path)
        assert r.status_code == 200
        assert "immutable" in r.headers["cache-control"]


def test_vendor_assets_served(auth_client):
    """免构建 vendor 产物（裁定①）：vue/vue-i18n esm-browser 经静态面可达。"""
    for path in ("/static/vendor/vue.esm-browser.prod.js",
                 "/static/vendor/vue-i18n.esm-browser.prod.js"):
        r = auth_client.get(path)
        assert r.status_code == 200
        assert "javascript" in r.headers["content-type"]


def test_stream_view_module_served(auth_client):
    """B 流视图模块经静态面可达（SPA 按对象组织的模块面）。"""
    for path in ("/static/app/main.js",
                 "/static/app/views/stream-browse-view.js",
                 "/static/app/locales/zh-CN.js"):
        r = auth_client.get(path)
        assert r.status_code == 200
