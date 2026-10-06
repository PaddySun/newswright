"""书签端点测试：POST /api/articles/{id}/bookmark 幂等置位 + bookmarked 过滤。

条款口径（产品书 US-15.1，设计依据见 docs/design-index.md「AC-15.1」）：
未书签文章 POST → 200；GET /api/articles?bookmarked=true 含该文章；
再调用一次 POST 仍为一书签（幂等——书签位收敛，不产生第二份记录）；
文章不存在 → 404 ARTICLE_NOT_FOUND（错误体 code 精确断言，技术书 §5 错误码表钉死）。
"""
import pytest

from app.models import Article, Author


@pytest.fixture()
def one_article(db_session):
    author = Author(name="书签作者", model="m")
    db_session.add(author)
    db_session.commit()
    article = Article(author_id=author.id, title="待书签文章", body="正文",
                      citations=[], status="PUBLISHED_TO_C")
    db_session.add(article)
    db_session.commit()
    return article


def test_bookmark_marks_and_filter_returns_article(auth_client, one_article):
    r = auth_client.post(f"/api/articles/{one_article.id}/bookmark")
    assert r.status_code == 200
    assert r.json() == {"article_id": one_article.id, "bookmarked": True}

    listed = auth_client.get("/api/articles", params={"bookmarked": "true"})
    assert listed.status_code == 200
    ids = [row["id"] for row in listed.json()]
    assert one_article.id in ids


def test_bookmark_repeated_call_still_single_bookmark(auth_client, one_article):
    """幂等全景：第二次 POST 仍 200，库内该书签位仍为一（单行单列收敛，
    无第二份书签记录可产生）。"""
    first = auth_client.post(f"/api/articles/{one_article.id}/bookmark")
    second = auth_client.post(f"/api/articles/{one_article.id}/bookmark")
    assert first.status_code == 200 and second.status_code == 200

    rows = auth_client.get("/api/articles", params={"bookmarked": "true"}).json()
    hits = [row for row in rows if row["id"] == one_article.id]
    assert len(hits) == 1
    # 未书签过滤位此时为空（同一文章不得同时出现在两个过滤位）
    unbookmarked = auth_client.get("/api/articles", params={"bookmarked": "false"}).json()
    assert one_article.id not in [row["id"] for row in unbookmarked]


def test_bookmark_article_not_found_coded_error(auth_client):
    r = auth_client.post("/api/articles/99999/bookmark")
    assert r.status_code == 404
    assert r.json() == {"code": "ARTICLE_NOT_FOUND", "message": "文章不存在"}


def test_bookmark_requires_session(api_client, one_article):
    """书签属登录态 C 流能力：未登录访问落 401。"""
    r = api_client.post(f"/api/articles/{one_article.id}/bookmark")
    assert r.status_code == 401
