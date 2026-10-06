"""文章列表作者筛选测试（产品书 US-15.2，设计依据见 docs/design-index.md「AC-15.2」）：
作者 2 三篇、作者 3 三篇 → ?author_id=2 仅返回作者 2 的三篇。
"""
import pytest

from app.models import Article, Author


@pytest.fixture()
def two_authors_six_articles(db_session):
    a2 = Author(name="作者2", model="m")
    a3 = Author(name="作者3", model="m")
    db_session.add_all([a2, a3])
    db_session.commit()
    for i in range(3):
        db_session.add(Article(author_id=a2.id, title=f"作者2第{i}篇", body="b", citations=[]))
        db_session.add(Article(author_id=a3.id, title=f"作者3第{i}篇", body="b", citations=[]))
    db_session.commit()
    return a2, a3


def test_author_filter_returns_only_that_author(auth_client, two_authors_six_articles):
    a2, a3 = two_authors_six_articles
    r = auth_client.get("/api/articles", params={"author_id": a2.id})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 3
    assert all(row["author_id"] == a2.id for row in rows)
    assert all(row["author_id"] != a3.id for row in rows)


def test_author_filter_other_author_symmetric(auth_client, two_authors_six_articles):
    a2, a3 = two_authors_six_articles
    rows = auth_client.get("/api/articles", params={"author_id": a3.id}).json()
    assert len(rows) == 3
    assert all(row["author_id"] == a3.id for row in rows)


def test_no_filter_returns_all(auth_client, two_authors_six_articles):
    rows = auth_client.get("/api/articles").json()
    assert len(rows) == 6
