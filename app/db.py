"""数据库 engine/session。SQLite 文件库，ORM 写法保持 PG 可迁移。

init_db 在 create_all 之后做一次轻量列迁移：对既有表缺失的新增列执行
ALTER TABLE ADD COLUMN（SQLite/PG 均支持加列），并对历史行回填默认值。
"""
from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from . import config

log = logging.getLogger("newswright.db")

_connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(config.DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _migrate_added_columns() -> None:
    """为既有表补齐后加的列（create_all 不会 ALTER 已存在表）。"""
    from . import models

    insp = inspect(engine)
    # 表名 → {列名: DDL 片段（列类型 + 默认）}；仅列追加，不改不改删
    additions: dict[str, dict[str, str]] = {
        "source": {
            "backoff_failures": "INTEGER NOT NULL DEFAULT 0",
            "backoff_skips": "INTEGER NOT NULL DEFAULT 0",
        },
        "item": {
            "sanitize_status": "VARCHAR(20) NOT NULL DEFAULT 'PENDING'",
            "sanitize_reason": "VARCHAR(500)",
            "sanitize_detail": "JSON",
        },
    }
    with engine.begin() as conn:
        backfill_sanitize = False
        for table, cols in additions.items():
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in cols.items():
                if col in existing:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                if table == "item" and col == "sanitize_status":
                    backfill_sanitize = True
                log.info("migrate: %s.%s 已补列", table, col)
        # 历史行回填（仅补列当次执行）：sanitize 字段上线前入库的条目视为已通过骨架过滤
        if backfill_sanitize:
            conn.execute(text(
                "UPDATE item SET sanitize_status='PASSED', "
                "sanitize_reason='demo:零信任过滤未启用(历史回填)' WHERE sanitize_status='PENDING'"
            ))


def init_db() -> None:
    from . import models  # noqa: F401  确保模型注册后再建表

    models.Base.metadata.create_all(engine)
    _migrate_added_columns()


def get_session() -> Iterator[Session]:
    """FastAPI 依赖用；脚本侧直接用 SessionLocal()。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
