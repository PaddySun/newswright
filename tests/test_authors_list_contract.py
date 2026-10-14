"""作者列表端点契约测试（GET /api/authors——UI2 W0b，服务 P5 写作工作台
作者卡）。

覆盖口径：200 行全字段（含 direction_names 联表与 has_author_json）；
direction_names 跳过已删方向与失效 id（呈现只给活方向名）；last_article_at
有文章/无文章两态（W0a 新列的作者面聚合）；空 readable_directions = []。
设计依据见 docs/design-index.md「AC-10.1」。
"""
from datetime import datetime, timezone

from app.models import Article, Author, Direction


def _mk_author(db, name: str, **kw) -> Author:
    a = Author(name=name, model="m-default", **kw)
    db.add(a)
    db.commit()
    return a


def test_authors_list_returns_full_contract_fields(auth_client, db_session):
    """行全字段：身份/绑定/呈现位 + direction_names + last_article_at + has_author_json。"""
    d = Direction(name="列表联表方向", prompt="p", prompt_version=1)
    db_session.add(d)
    db_session.commit()
    published = datetime(2026, 10, 12, 6, 30, tzinfo=timezone.utc)
    a = _mk_author(db_session, "字段作者", enabled=False, public_visible=True,
                   bio="一句话简介",
                   readable_directions=[{"direction_id": d.id, "threshold": 30}],
                   author_json={"id": "x", "version": "v"})
    db_session.add(Article(author_id=a.id, title="成文", body="正文",
                           citations=[], created_at=published))
    db_session.commit()

    r = auth_client.get("/api/authors")
    assert r.status_code == 200
    rows = r.json()
    target = next(x for x in rows if x["name"] == "字段作者")
    assert set(target) == {
        "id", "name", "model", "enabled", "public_visible", "bio",
        "direction_names", "last_article_at", "has_author_json",
    }
    assert target["model"] == "m-default"
    assert target["enabled"] is False
    assert target["public_visible"] is True
    assert target["bio"] == "一句话简介"
    assert target["direction_names"] == ["列表联表方向"]
    # SQLite 时间往返落 naive（tz 丢弃为已知存储行为）——按时刻前缀断言
    assert target["last_article_at"].startswith("2026-10-12T06:30:00")
    assert target["has_author_json"] is True


def test_authors_list_skips_dead_directions(auth_client, db_session):
    """direction_names 只呈现活方向：已删（软删）与失效 id 均跳过。"""
    live = Direction(name="活方向", prompt="p", prompt_version=1)
    dead = Direction(name="已删方向", prompt="p", prompt_version=1)
    db_session.add_all([live, dead])
    db_session.commit()
    dead.apply_status(Direction.STATUS_DELETED)
    db_session.commit()
    _mk_author(db_session, "联表作者",
               readable_directions=[
                   {"direction_id": live.id, "threshold": 40},
                   {"direction_id": dead.id, "threshold": 50},
                   {"direction_id": 99999, "threshold": 60},
               ])

    r = auth_client.get("/api/authors")
    target = next(x for x in r.json() if x["name"] == "联表作者")
    assert target["direction_names"] == ["活方向"]


def test_authors_list_last_article_at_null_without_articles(auth_client, db_session):
    """无文章作者 last_article_at=null；多文章取 MAX(created_at)。"""
    from app.models import Article

    _mk_author(db_session, "无文作者")
    rich = _mk_author(db_session, "多文作者")
    db_session.add_all([
        Article(author_id=rich.id, title="早文", body="b", citations=[],
                created_at=datetime(2026, 10, 1, tzinfo=timezone.utc)),
        Article(author_id=rich.id, title="晚文", body="b", citations=[],
                created_at=datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)),
    ])
    db_session.commit()

    rows = auth_client.get("/api/authors").json()
    by_name = {x["name"]: x for x in rows}
    assert by_name["无文作者"]["last_article_at"] is None
    assert by_name["多文作者"]["last_article_at"].startswith("2026-10-13T09:00:00")


def test_authors_list_empty_directions_and_no_json(auth_client, db_session):
    """空 readable_directions=[]；未配置 author.json 的作者 has_author_json=false。"""
    _mk_author(db_session, "素作者")
    r = auth_client.get("/api/authors")
    target = next(x for x in r.json() if x["name"] == "素作者")
    assert target["direction_names"] == []
    assert target["has_author_json"] is False
