"""stats/pipeline 端点单次注册测试（UI2 W0c / W0a 备账清理）。

背景：routes.py 的 @router.get("/stats/pipeline") 装饰器曾重复注册两行，
每次 OpenAPI 生成发两条 Duplicate Operation ID UserWarning。本测试双钉：
结构面（守卫 router 内该路径恰一条 GET 路由）+ 生成面（Duplicate Operation
ID 告警升 error 后 openapi() 干净）；另钉功能不回归。
"""
import warnings

from app.main import app


def _get_registrations(router, path: str) -> list:
    return [r for r in router.routes
            if getattr(r, "path", None) == path
            and "GET" in (getattr(r, "methods", None) or set())]


def test_stats_pipeline_registered_once_in_guarded_router():
    """守卫 router 内 GET /stats/pipeline 恰注册一条（重复装饰器已去重；
    双挂载（无前缀 + /api 前缀）复用同一 router 对象，单次注册即两形态全对）。"""
    from app.api.routes import router as guarded_router

    regs = _get_registrations(guarded_router, "/stats/pipeline")
    assert len(regs) == 1


def test_openapi_generation_no_duplicate_operation_id_warning():
    """openapi 生成零 Duplicate Operation ID 告警（该类告警升 error 后应
    干净生成——重复注册已消除且全仓无其他重复）。"""
    app.openapi_schema = None  # 清缓存强制重生成（防前序测试缓存空转）
    with warnings.catch_warnings():
        warnings.filterwarnings("error", message=".*Duplicate Operation ID.*")
        spec = app.openapi()
    # 双挂载两形态都在册（纯去重不丢契约面）
    assert "/stats/pipeline" in spec["paths"]
    assert "/api/stats/pipeline" in spec["paths"]


def test_stats_pipeline_function_not_regressed(auth_client):
    """功能不回归：GET /api/stats/pipeline 200（体检载荷可达）。"""
    r = auth_client.get("/api/stats/pipeline")
    assert r.status_code == 200
