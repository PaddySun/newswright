"""文章成文时间列迁移测试（article.created_at——UI2 W0a）。

覆盖口径（两形态）：旧库形态（列上线前的 article+write_run 历史形状 → init_db
补列）回填 = 该文章 write_run 成文时间 MIN，无 write_run 的行回填不到留 null；
新库形态（create_all 直接有列）ORM 写入默认落成文时刻。
回填口径定案：docs/design-index.md「UI2 W0a 迁移表」——write_run.created_at
取 MIN，回填不到留 null（前端按时间未知呈现）。
夹具模式沿用 tests/test_db_migration.py 的历史形状裸建 + init_db 由测试自调。
"""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

import app.config as cfg
import app.db as appdb

# created_at 上线前的 article 形状（含 F2 呈现三列，不含 created_at）
_OLD_ARTICLE_NO_CREATED_AT = """
CREATE TABLE article (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id INTEGER REFERENCES author(id),
    title VARCHAR(2000),
    body TEXT,
    citations JSON,
    status VARCHAR(30) DEFAULT 'PUBLISHED_TO_C',
    citation_violated BOOLEAN DEFAULT 0,
    bookmarked BOOLEAN DEFAULT 0,
    public BOOLEAN DEFAULT 0,
    ai_label BOOLEAN DEFAULT 1
)"""

_OLD_WRITE_RUN = """
CREATE TABLE write_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id INTEGER REFERENCES author(id),
    triggered_by VARCHAR(50) DEFAULT 'manual',
    reading_set_item_ids JSON,
    payload JSON,
    prompt_snapshot TEXT,
    decision VARCHAR(10),
    article_id INTEGER REFERENCES article(id),
    skip_reason TEXT,
    skip_thinking TEXT,
    model VARCHAR(100),
    status VARCHAR(20) DEFAULT 'OK',
    error TEXT,
    created_at DATETIME
)"""


@pytest.fixture()
def article_created_at_old_db(tmp_path):
    """旧库夹具：article 无 created_at；文章 1 有两次成文（09-01 与 09-05），
    文章 2 无 write_run（SKIP/失败等无产物路径）。"""
    url = f"sqlite:///{(tmp_path / 'article_created_at_old.db').as_posix()}"
    cfg.DATABASE_URL = url
    appdb.engine.dispose()
    appdb.engine = create_engine(url, connect_args={"check_same_thread": False},
                                 future=True)
    appdb.SessionLocal.configure(bind=appdb.engine)
    with appdb.engine.begin() as conn:
        conn.execute(text(_OLD_ARTICLE_NO_CREATED_AT))
        conn.execute(text(_OLD_WRITE_RUN))
        conn.execute(text(
            "INSERT INTO article (author_id, title, body) VALUES (1, '旧文一', 'b')"))
        conn.execute(text(
            "INSERT INTO article (author_id, title, body) VALUES (1, '旧文二', 'b')"))
        conn.execute(text(
            "INSERT INTO write_run (author_id, article_id, model, created_at) "
            "VALUES (1, 1, 'm', '2026-09-01 10:00:00')"))
        conn.execute(text(
            "INSERT INTO write_run (author_id, article_id, model, created_at) "
            "VALUES (1, 1, 'm', '2026-09-05 20:30:00')"))
    yield
    appdb.engine.dispose()
    cfg.DATABASE_URL = f"sqlite:///{(cfg.PROJECT_ROOT / 'newswright.db').as_posix()}"


def test_migrate_old_article_backfills_write_run_min(article_created_at_old_db):
    """补列当次回填：文章 1 的成文时间 = 两次 write_run 的 MIN（09-01）。"""
    from app.db import init_db

    init_db()
    columns = {c["name"] for c in inspect(appdb.engine).get_columns("article")}
    assert "created_at" in columns
    with appdb.engine.connect() as conn:
        value = conn.execute(text(
            "SELECT created_at FROM article WHERE title = '旧文一'")).scalar_one()
    assert str(value) == "2026-09-01 10:00:00"


def test_migrate_old_article_without_write_run_stays_null(article_created_at_old_db):
    """回填不到留 null：无 write_run 的文章成文时间未知（呈现归前端降级）。"""
    from app.db import init_db

    init_db()
    with appdb.engine.connect() as conn:
        value = conn.execute(text(
            "SELECT created_at FROM article WHERE title = '旧文二'")).scalar_one()
    assert value is None


def test_new_db_article_created_at_column_and_orm_default(db_session):
    """新库形态：create_all 直接有列；ORM 写入不显式赋值时默认落成文时刻。"""
    from datetime import datetime, timedelta, timezone

    from app.models import Article, Author

    author = Author(name="成文时间作者", model="m")
    db_session.add(author)
    db_session.commit()
    before = datetime.now(timezone.utc)
    article = Article(author_id=author.id, title="新文", body="b", citations=[])
    db_session.add(article)
    db_session.commit()
    columns = {c["name"]
               for c in inspect(appdb.engine).get_columns("article")}
    assert "created_at" in columns
    assert article.created_at is not None
    # 属性值为 ORM 默认注入的时刻（tz-aware）；与当前时刻统一拍掉时区后比较，
    # 留 5 秒钟余量防边界抖动
    created = article.created_at
    if created.tzinfo is not None:
        created = created.replace(tzinfo=None)
    assert created >= before.replace(tzinfo=None) - timedelta(seconds=5)
