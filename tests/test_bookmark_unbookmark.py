"""取消书签端点测试（DELETE /api/articles/{id}/bookmark——UI2 W0a）。

覆盖口径：幂等清位（重复 DELETE 收敛同一终态，与 POST 置位对偶——书签状态
是文章行上的布尔位而非独立书签行）；404 coded ARTICLE_NOT_FOUND；与 POST 的
对偶往返（置位→清位→过滤视图同步翻转）。
设计依据见 docs/design-index.md「AC-15.1」。
"""
import pytest

from app.models import Article, Author


@pytest.fixture()
def one_article(db_session):
    author = Author(name="书签往返作者", model="m")
    db_session.add(author)
    db_session.commit()
    article = Article(author_id=author.id, title="书签往返文章", body="正文",
                      citations=[], status="PUBLISHED_TO_C")
    db_session.add(article)
    db_session.commit()
    return article


def test_unbookmark_clears_flag_and_idempotent(auth_client, one_article, db_session):
    auth_client.post(f"/api/articles/{one_article.id}/bookmark")
    first = auth_client.delete(f"/api/articles/{one_article.id}/bookmark")
    assert first.status_code == 200
    assert first.json() == {"article_id": one_article.id, "bookmarked": False}
    second = auth_client.delete(f"/api/articles/{one_article.id}/bookmark")
    assert second.status_code == 200  # 幂等：重复清位不报错不复活
    assert second.json() == {"article_id": one_article.id, "bookmarked": False}
    db_session.refresh(one_article)
    assert one_article.bookmarked is False


def test_unbookmark_not_found_coded_error(auth_client):
    r = auth_client.delete("/api/articles/99999/bookmark")
    assert r.status_code == 404
    assert r.json() == {"code": "ARTICLE_NOT_FOUND", "message": "文章不存在"}


def test_bookmark_unbookmark_roundtrip_with_filter_views(auth_client, one_article):
    """对偶往返：POST 置位→已书签视图含该文章；DELETE 清位→已书签视图不含、
    未书签视图含。"""
    auth_client.post(f"/api/articles/{one_article.id}/bookmark")
    marked = auth_client.get("/api/articles",
                             params={"bookmarked": "true"}).json()["items"]
    assert one_article.id in [row["id"] for row in marked]

    auth_client.delete(f"/api/articles/{one_article.id}/bookmark")
    marked_after = auth_client.get("/api/articles",
                                   params={"bookmarked": "true"}).json()["items"]
    unmarked_after = auth_client.get("/api/articles",
                                     params={"bookmarked": "false"}).json()["items"]
    assert one_article.id not in [row["id"] for row in marked_after]
    assert one_article.id in [row["id"] for row in unmarked_after]


def test_unbookmark_requires_session(api_client, one_article):
    """书签族端点同守卫：未登录 DELETE 落 401。"""
    r = api_client.delete(f"/api/articles/{one_article.id}/bookmark")
    assert r.status_code == 401
