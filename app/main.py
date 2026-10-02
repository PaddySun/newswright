"""FastAPI 入口：uvicorn app.main:app --port 8300"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .api.auth import router as auth_router
from .api.routes import router
from .auth import bootstrap_admin
from .db import SessionLocal, init_db


def create_app() -> FastAPI:
    app = FastAPI(title="newswright-demo", version="0.1.0")
    init_db()
    with SessionLocal() as db:
        bootstrap_admin(db)  # AC-01.1：users 空表时创建 admin（已有用户不覆盖）
    app.include_router(auth_router)  # /api/auth：守卫豁免路由（先注册）
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

    @app.get("/")
    def root():
        return {"app": "newswright-demo", "hint": "POST /pipeline/run 触发抓取+打分；POST /pipeline/write/{author_id} 触发写作"}

    return app


app = create_app()
