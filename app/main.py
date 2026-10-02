"""FastAPI 入口：uvicorn app.main:app --port 8300"""
from __future__ import annotations

from fastapi import FastAPI

from .api.routes import router
from .auth import bootstrap_admin
from .db import SessionLocal, init_db


def create_app() -> FastAPI:
    app = FastAPI(title="newswright-demo", version="0.1.0")
    init_db()
    with SessionLocal() as db:
        bootstrap_admin(db)  # AC-01.1：users 空表时创建 admin（已有用户不覆盖）
    app.include_router(router)

    @app.get("/")
    def root():
        return {"app": "newswright-demo", "hint": "POST /pipeline/run 触发抓取+打分；POST /pipeline/write/{author_id} 触发写作"}

    return app


app = create_app()
