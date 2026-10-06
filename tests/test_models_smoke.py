"""M1 冒烟：建表 + 唯一约束 (source_id, guid) 生效。G1 扩展：users/sessions/site_config 三表。"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, init_db
from app.models import Direction, Item, SiteConfig, Source, User, UserSession


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


def test_apply_status_mirrors_enabled(tables):
    """方向生命周期切换同步 enabled 镜像列（仅 active 为真）——status 是唯一
    真值，enabled 是旧读路径镜像。设计依据见 docs/design-index.md「AC-03.3」。"""
    with SessionLocal() as s:
        d = Direction(name="镜像方向", prompt="p", threshold=60)
        s.add(d)
        s.commit()

        d.apply_status(Direction.STATUS_DISABLED)
        assert d.status == "disabled" and d.enabled is False
        s.commit()

        d.apply_status(Direction.STATUS_ACTIVE)
        assert d.status == "active" and d.enabled is True

        d.apply_status(Direction.STATUS_DELETED)
        assert d.status == "deleted" and d.enabled is False
        assert d.deleted_at is not None
        s.commit()


def test_users_sessions_siteconfig_tables(tables):
    """G1/W1：users(username 唯一)、sessions(字符串主键)、site_config(key TEXT PK)。"""
    with SessionLocal() as s:
        u = User(username="admin", password_hash="argon2id$fake", must_change_password=True)
        s.add(u)
        s.commit()
        dup = User(username="admin", password_hash="x")
        s.add(dup)
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()

        from datetime import datetime, timedelta, timezone

        sess = UserSession(id="tok123", user_id=u.id,
                           expires_at=datetime.now(timezone.utc) + timedelta(days=7))
        s.add(sess)
        s.commit()
        assert s.get(UserSession, "tok123").user_id == u.id

        s.add(SiteConfig(key="session_duration_days", value=7))
        s.commit()
        assert s.get(SiteConfig, "session_duration_days").value == 7
        # must_change_password 默认 true
        u2 = User(username="u2", password_hash="x")
        s.add(u2)
        s.commit()
        assert u2.must_change_password is True
