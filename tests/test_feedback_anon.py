"""匿名反馈测试（产品书 US-13，设计依据见 docs/design-index.md「AC-13.1」
「AC-13.2」「AC-13.3」）：双访客计数与 already_counted 幂等、匿名评论 403
（错误体精确断言）、登录评论行为、反馈回流记忆保持；请求体不收身份字段。
"""
import pytest

from app.api.deps import VISITOR_COOKIE_NAME
from app.models import Article, ArticleReaction, Author, MemoryEntry


@pytest.fixture()
def article(db_session):
    author = Author(name="反馈作者", model="m")
    db_session.add(author)
    db_session.commit()
    a = Article(author_id=author.id, title="被反馈文章", body="b", citations=[])
    db_session.add(a)
    db_session.commit()
    return a


def _client_as(api_client, visitor_id: str | None):
    """以指定匿名身份复用 client（cookie 主链）。"""
    api_client.cookies.clear()
    if visitor_id:
        api_client.cookies.set(VISITOR_COOKIE_NAME, visitor_id)
    return api_client


def test_anonymous_like_dedup_and_second_visitor_counts(api_client, db_session, article):
    """AC-13.1 全景：C1 首赞计数 1；同 cookie 再赞 already_counted（仍 1 行）；
    C2 点赞后计数 2。"""
    c1 = _client_as(api_client, "C1")
    r1 = c1.post("/feedback", json={"article_id": article.id, "verdict": "like"})
    assert r1.status_code == 200 and r1.json() == {"counted": True}

    r2 = c1.post("/feedback", json={"article_id": article.id, "verdict": "like"})
    assert r2.status_code == 200
    assert r2.json() == {"counted": False, "reason": "already_counted"}
    assert db_session.query(ArticleReaction).filter_by(article_id=article.id).count() == 1

    c2 = _client_as(api_client, "C2")
    r3 = c2.post("/feedback", json={"article_id": article.id, "verdict": "like"})
    assert r3.status_code == 200 and r3.json() == {"counted": True}
    assert db_session.query(ArticleReaction).filter_by(article_id=article.id).count() == 2


def test_anonymous_dislike_dedup_same_chain(api_client, db_session, article):
    """dislike 同链去重（改判 like 也不再计数——访客对文章至多一行）。"""
    c = _client_as(api_client, "C9")
    c.post("/feedback", json={"article_id": article.id, "verdict": "dislike"})
    r = c.post("/feedback", json={"article_id": article.id, "verdict": "like"})
    assert r.json() == {"counted": False, "reason": "already_counted"}


def test_anonymous_comment_rejected_exact_body(api_client, article):
    """AC-13.2：匿名提交 comment → 403，错误体精确断言。"""
    r = api_client.post("/feedback", json={
        "article_id": article.id, "verdict": "comment", "text": "写得好"})
    assert r.status_code == 403
    assert r.json() == {"code": "AUTH_REQUIRED_COMMENT",
                        "message": "文字评价需登录后提交"}


def test_logged_in_comment_flows_to_memory(auth_client, db_session, article):
    """登录评论：回流记忆含评语原文（AC-13.3 既有闭环保持）。"""
    r = auth_client.post("/feedback", json={
        "article_id": article.id, "verdict": "comment", "text": "标题太标题党"})
    assert r.status_code == 200 and r.json() == {"counted": True}
    entries = (db_session.query(MemoryEntry)
               .filter_by(author_id=article.author_id, module="feedback").all())
    assert any("标题太标题党" in e.content for e in entries)


def test_like_flows_to_memory_once(api_client, db_session, article):
    """点赞首计回流记忆；重复点赞（already_counted）不再重复写记忆。"""
    c = _client_as(api_client, "C10")
    c.post("/feedback", json={"article_id": article.id, "verdict": "dislike"})
    c.post("/feedback", json={"article_id": article.id, "verdict": "dislike"})
    entries = (db_session.query(MemoryEntry)
               .filter_by(author_id=article.author_id, module="feedback").all())
    assert len([e for e in entries if "点了踩" in e.content]) == 1


def test_feedback_article_not_found(api_client):
    r = api_client.post("/feedback", json={"article_id": 99999, "verdict": "like"})
    assert r.status_code == 404


def test_feedback_invalid_verdict(api_client, article):
    r = api_client.post("/feedback", json={"article_id": article.id, "verdict": "meh"})
    assert r.status_code == 422
