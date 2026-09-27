"""pytest 共享 fixture：每个测试独立的临时 SQLite 库。"""
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
