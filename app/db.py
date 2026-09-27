"""数据库 engine/session。SQLite 文件库，ORM 写法保持 PG 可迁移。"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from . import config

_connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(config.DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    from . import models  # noqa: F401  确保模型注册后再建表

    models.Base.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """FastAPI 依赖用；脚本侧直接用 SessionLocal()。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
