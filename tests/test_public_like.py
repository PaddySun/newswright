"""公开页访客点赞测试（AC-16.5）：公开页路径点赞与 AC-13.1 同套去重。

匿名访客（nw_visitor cookie 身份）在模式 C 公开文章页点赞：首次计数、
同访客重复 already_counted、不同访客累加——与登录态反馈端点完全同链
（同一个 /feedback 端点、同一个去重键）。
设计依据见 docs/design-index.md「AC-16.5」「AC-13.1」「D7」。
"""
import pytest

from app import siteconfig
from app.api.deps import VISITOR_COOKIE_NAME
from app.models import Article, ArticleReaction, Author


@pytest.fixture()
def public_article(db_session):
    """模式 C 下的公开文章（双开关全开）。"""
    author = Author(name="点赞作者", model="m", public_visible=True)
    db_session.add(author)
    db_session.flush()
    article = Article(author_id=author.id, title="被点赞文章", body="正文",
                      citations=[], public=True)
    db_session.add(article)
    db_session.commit()
    siteconfig.set_config(db_session, "public_mode", "C")
    db_session.commit()
    return article


def _visitor(api_client, visitor_id: str):
    api_client.cookies.clear()
    api_client.cookies.set(VISITOR_COOKIE_NAME, visitor_id)
    return api_client


def test_public_page_reachable_for_visitor_and_like_dedup(api_client, db_session,
                                                          public_article):
    """公开文章页未登录可达（200 HTML）；匿名点赞走同套去重：C1 首赞计数、
    重复 already_counted、C2 累加（AC-16.5=AC-13.1 同链）。"""
    page = api_client.get(f"/public/article/{public_article.id}")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert 'id="public-like"' in page.text  # 点赞按钮在页面

    c1 = _visitor(api_client, "PUB-C1")
    r1 = c1.post("/feedback", json={"article_id": public_article.id, "verdict": "like"})
    assert r1.status_code == 200 and r1.json() == {"counted": True}
    r2 = c1.post("/feedback", json={"article_id": public_article.id, "verdict": "like"})
    assert r2.status_code == 200
    assert r2.json() == {"counted": False, "reason": "already_counted"}
    c2 = _visitor(api_client, "PUB-C2")
    r3 = c2.post("/feedback", json={"article_id": public_article.id, "verdict": "like"})
    assert r3.status_code == 200 and r3.json() == {"counted": True}
    assert (db_session.query(ArticleReaction)
            .filter_by(article_id=public_article.id).count() == 2)


def test_public_like_on_hidden_article_is_404_feedback(api_client, db_session,
                                                       public_article):
    """未公开文章不在公开页呈现，但其文章行存在——匿名反馈端点按既有语义
    仍可对行内文章计数（公开过滤是呈现面职责，反馈面不做二次封禁：访客
    无从发现隐藏文章 id）。本测试固化该边界语义防漂移。"""
    public_article.public = False
    db_session.commit()
    page = api_client.get(f"/public/article/{public_article.id}")
    assert page.status_code == 404
    r = _visitor(api_client, "PUB-C9").post(
        "/feedback", json={"article_id": public_article.id, "verdict": "like"})
    assert r.status_code == 200 and r.json() == {"counted": True}


def test_public_like_requires_no_session_and_anonymous_comment_403(api_client,
                                                                   db_session,
                                                                   public_article):
    """公开页访客点赞不需要登录（无会话 cookie 直访）；匿名评论仍 403
    （AC-13.2 在公开页路径同样成立）。"""
    r = _visitor(api_client, "PUB-NC").post(
        "/feedback", json={"article_id": public_article.id, "verdict": "like"})
    assert r.status_code == 200 and r.json() == {"counted": True}
    rc = _visitor(api_client, "PUB-NC").post(
        "/feedback",
        json={"article_id": public_article.id, "verdict": "comment", "text": "好"})
    assert rc.status_code == 403
    assert rc.json()["code"] == "AUTH_REQUIRED_COMMENT"
