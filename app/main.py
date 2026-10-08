"""FastAPI 入口：uvicorn app.main:app --port 8300"""
from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .api.auth import router as auth_router
from .api.feedback import router as feedback_router
from .api.middleware import cache_header_middleware
from .api.public import public_mode, router as public_router
from .api.routes import router
from .auth import bootstrap_admin
from .db import SessionLocal, get_session, init_db


def _docs_enabled() -> bool:
    """/docs 生产门禁（P1-8）：env DOCS_ENABLED 显式开启才提供文档面；
    默认关闭——模式 A 合规期不得泄露 API 结构（部署矩阵硬条款②）。"""
    return os.environ.get("DOCS_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def create_app() -> FastAPI:
    docs_open = _docs_enabled()
    app = FastAPI(
        title="newswright-demo",
        version="0.1.0",
        docs_url="/docs" if docs_open else None,
        redoc_url="/redoc" if docs_open else None,
        openapi_url="/openapi.json" if docs_open else None,
    )
    init_db()
    with SessionLocal() as db:
        bootstrap_admin(db)  # AC-01.1：users 空表时创建 admin（已有用户不覆盖）
    app.include_router(auth_router)  # /api/auth：守卫豁免路由（先注册）
    app.include_router(feedback_router)  # /feedback：匿名反馈（守卫豁免，独立 router）
    app.include_router(router)
    app.include_router(public_router)  # 公开页 SSR + SEO 三件 + 登录页（无守卫）
    # 静态资源（CSS/JS/vendor）：immutable 段由中间件按路径判定域赋头
    app.mount("/static", StaticFiles(directory=str(_static_dir())), name="static")

    @app.exception_handler(HTTPException)
    async def coded_error_handler(request, exc: HTTPException):
        """D11 错误体契约：detail={"code","message"} 的异常输出规范错误体；
        既有 string detail 端点行为不变（G1 只覆盖 auth 族，/api 前缀统一属后续）。"""
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            return JSONResponse(
                status_code=exc.status_code,
                content={"code": exc.detail["code"], "message": exc.detail.get("message", "")},
                headers=getattr(exc, "headers", None),
            )
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request, exc: RequestValidationError):
        """请求体校验失败 → 400 VALIDATION_ERROR（message 含字段路径）。
        FastAPI 默认 422 与契约错误码表不符（400），统一在此归一。"""
        parts = [
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        ]
        return JSONResponse(status_code=400,
                            content={"code": "VALIDATION_ERROR", "message": "; ".join(parts)})

    from .logging_setup import reset_log_context, set_log_context, setup_logging

    setup_logging()

    @app.middleware("http")
    async def visitor_cookie_middleware(request, call_next):
        """匿名访客身份签发：首次访问（无 nw_visitor cookie）即签发 HttpOnly
        随机 id——匿名反馈去重的主链（缺失时 IP+UA 哈希兜底，见 deps.visitor_hash）。
        已带 cookie 不重签（身份稳定，跨请求可去重）。"""
        import secrets as _secrets

        from .api.deps import VISITOR_COOKIE_NAME

        response = await call_next(request)
        if VISITOR_COOKIE_NAME not in request.cookies:
            response.set_cookie(VISITOR_COOKIE_NAME, _secrets.token_urlsafe(24),
                                httponly=True, samesite="lax", path="/")
        return response

    @app.middleware("http")
    async def cache_contract_middleware(request, call_next):
        """响应头契约三段式（P2-4）：路径判定域纯函数见 api/middleware.py；
        只补缺不覆盖（healthz 等自带契约头的端点保持第一责任方）。"""
        return await cache_header_middleware(request, call_next)

    @app.middleware("http")
    async def log_context_middleware(request, call_next):
        """请求侧日志上下文注入：route + actor（会话身份）经 contextvars 写入，
        业务代码不手工拼上下文字段。请求完成记一条 INFO 行（访问面留痕）。"""
        token = set_log_context(route=request.url.path,
                                actor=_session_actor(request))
        import logging as _logging

        try:
            response = await call_next(request)
            _logging.getLogger("newswright.http").info(
                "http %s %s", request.method, request.url.path,
                extra={"http_status": response.status_code})
            return response
        finally:
            reset_log_context(token)

    @app.get("/")
    def root(request: Request, db: Session = Depends(get_session)):
        """站点根：模式 A=404 合规页（AC-02.1 未登录首页 404 无内容泄露，
        原 JSON 提示面随公开模式契约退役——demo 残留、无契约在册、测试零覆盖，
        变更已在 UI 批汇报声明）；模式 B/C=重定向公开首页。"""
        if public_mode(db) == "A":
            from .api.public import mode_a_404

            return mode_a_404(request)
        return RedirectResponse(url="/public", status_code=307)

    @app.get("/healthz")
    def healthz():
        """健康自省三态端点（无鉴权，security: []；外部探测以此报警）。

        200 = 健康；200+degraded = 增值层故障的合法稳态（不触发外部报警）；
        503 = 仅基本功能故障（DB 不可写/抓取停滞超阈/任务堆积超阈）。
        响应头 Cache-Control: no-store——前置层永不缓存，防"假活"复刻。
        """
        from .observability import health_payload

        with SessionLocal() as db:
            status_code, payload = health_payload(db)
        return JSONResponse(status_code=status_code, content=payload,
                            headers={"Cache-Control": "no-store"})

    return app


def _static_dir():
    from pathlib import Path

    return Path(__file__).resolve().parent / "static"


def _session_actor(request) -> str | None:
    """请求会话身份（日志 actor 字段）：cookie → 未过期会话 → 用户名；匿名 None。"""
    from .auth import COOKIE_NAME, get_valid_session
    from .models import User

    sid = request.cookies.get(COOKIE_NAME)
    if not sid:
        return None
    try:
        from .db import SessionLocal as _SL

        with _SL() as db:
            sess = get_valid_session(db, sid)
            if sess is None:
                return None
            user = db.get(User, sess.user_id)
            return user.username if user else None
    except Exception:  # noqa: BLE001  actor 解析失败不影响请求本身
        return None


app = create_app()
