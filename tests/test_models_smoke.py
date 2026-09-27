"""M1 冒烟：建表 + 唯一约束 (source_id, guid) 生效。"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, init_db
from app.models import Direction, Item, Source


@pytest.fixture(scope="module")
def tables(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("m1")
    import app.config as cfg

    old = cfg.DATABASE_URL
    cfg.DATABASE_URL = f"sqlite:///{(tmp / 'm1.db').as_posix()}"
    import app.db as db

    db.engine.dispose()
    db.engine = __import__("sqlalchemy", fromlist=["create_engine"]).create_engine(
        cfg.DATABASE_URL, connect_args={"check_same_thread": False}, future=True
    )
    db.SessionLocal.configure(bind=db.engine)
    init_db()
    yield
    db.engine.dispose()
    cfg.DATABASE_URL = old


def test_create_all(tables):
    with SessionLocal() as s:
        d = Direction(name="AI 工程", prompt="p", threshold=60)
        s.add(d)
        s.commit()
        src = Source(direction_id=d.id, url="https://example.com/feed")
        s.add(src)
        s.commit()
        s.add(Item(source_id=src.id, guid="g1", title="t"))
        s.commit()


def test_unique_source_guid(tables):
    with SessionLocal() as s:
        src = s.query(Source).one()
        s.add(Item(source_id=src.id, guid="g1", title="dup"))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
