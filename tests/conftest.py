"""pytest 共享 fixture：每个测试独立的临时 SQLite 库。

G1 起测试环境注入 NEWSWRIGHT_ADMIN_PASSWORD（随机值，不进 git/日志）——必须在
app.config 导入前设置（config.py 缺失该变量即 SystemExit，D18/AC-01.1）。
"""
import os
import secrets

os.environ.setdefault("NEWSWRIGHT_ADMIN_PASSWORD", secrets.token_urlsafe(24))

import tempfile
from pathlib import Path

import pytest
import sqlalchemy
from sqlalchemy import create_engine

import app.config as cfg
import app.db as appdb


@pytest.fixture()
def db_session():
    tmp = Path(tempfile.mkdtemp())
    url = f"sqlite:///{(tmp / 't.db').as_posix()}"
    cfg.DATABASE_URL = url
    appdb.engine.dispose()
    appdb.engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)
    appdb.SessionLocal.configure(bind=appdb.engine)
    from app.db import init_db
    from app.db import SessionLocal as SL

    init_db()
    session = SL()
    try:
        yield session
    finally:
        session.close()
        appdb.engine.dispose()
        cfg.DATABASE_URL = f"sqlite:///{(cfg.PROJECT_ROOT / 'newswright.db').as_posix()}"
