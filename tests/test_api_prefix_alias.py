"""守卫路由双挂载契约测试（demo 兼容形态 + /api 契约形态）。

背景：demo 以来守卫端点以无前缀路径注册（/stream/b、/items 等），而技术书
§3 OpenAPI 契约与 SPA 消费一律 /api 前缀——曾致 SPA 调用 404。修复形态=
路由表双挂载（装饰器不带前缀，挂载点统一产生两种路径），每端点恰两条服务
路径且无 /api/api 冗余。路由在位性以实请求判定（未登录 401=路由存在，
404=不存在；新版本 FastAPI 的 include 路由组不暴露顶层 path，无法走路由表
枚举）。设计依据见 docs/design-index.md「R1」。
"""


def test_dual_mount_produces_both_path_forms(api_client):
    """双挂载：抽样端点两种形态均在位——401（守卫拦截）或 405（路径在位但
    方法不符）均证明路由存在，404 才是缺失。"""
    for demo, contract in [
        ("/stream/b", "/api/stream/b"),
        ("/items", "/api/items"),
        ("/stats/search", "/api/stats/search"),
        ("/directions", "/api/directions"),
        ("/settings/notify", "/api/settings/notify"),
        ("/pipeline/run", "/api/pipeline/run"),
    ]:
        assert api_client.get(demo).status_code in (401, 405), f"demo 形态缺失: {demo}"
        assert api_client.get(contract).status_code in (401, 405), f"契约形态缺失: {contract}"


def test_no_api_api_redundant_paths(api_client):
    """装饰器去前缀后不产生 /api/api/* 冗余路径（应为 404）。"""
    assert api_client.get("/api/api/stream/b").status_code == 404
    assert api_client.get("/api/api/items").status_code == 404


def test_api_alias_endpoints_respond(auth_client):
    """/api 契约形态实响应：SPA 消费的关键端点经别名可达（登录态冒烟）。"""
    for path in ("/api/stream/b", "/api/articles", "/api/scheduler/status"):
        r = auth_client.get(path)
        assert r.status_code == 200, f"{path} → {r.status_code}: {r.text[:120]}"
    # /healthz 契约本为根路径（无守卫独立端点，技术书 §3 同款）——不取别名
    assert auth_client.get("/healthz").status_code == 200


def test_demo_form_still_serves_existing_consumers(auth_client):
    """demo 兼容形态在位（既有测试与历史消费者零迁移）。"""
    assert auth_client.get("/stream/b").status_code == 200
    assert auth_client.get("/items").status_code == 200
