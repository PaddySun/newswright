"""FastAPI 入口：uvicorn app.main:app --port 8300"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api.auth import router as auth_router
from .api.feedback import router as feedback_router
from .api.routes import router
from .auth import bootstrap_admin
from .db import SessionLocal, init_db


def create_app() -> FastAPI:
    app = FastAPI(title="newswright-demo", version="0.1.0")
    init_db()
    with SessionLocal() as db:
        bootstrap_admin(db)  # AC-01.1：users 空表时创建 admin（已有用户不覆盖）
    app.include_router(auth_router)  # /api/auth：守卫豁免路由（先注册）
    app.include_router(feedback_router)  # /feedback：匿名反馈（守卫豁免，独立 router）
    app.include_router(router)

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
    def root():
        return {"app": "newswright-demo", "hint": "POST /pipeline/run 触发抓取+打分；POST /pipeline/write/{author_id} 触发写作"}

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
