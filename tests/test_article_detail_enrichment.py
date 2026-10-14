"""文章详情富化测试（GET /api/articles/{article_id} 呈现面增补——UI2 W0a，
服务 P3 文章详情页）。

覆盖口径：富化全字段（author_name/created_at/bookmarked/citation_violated/
ai_label/reactions 计数）；viewer_reacted 三态（无行=null / like 行=like /
仅 comment 形态行=null——comment 不计入反应位）；citations 富化（k=1-based
引用序号 + 原文 url + item_title；item 已不存在时 url/item_title=null 而
k/quote 保留）；404 coded ARTICLE_NOT_FOUND。
引用序号取法依据写入侧形态：citations 落库按脚注键（正文出现顺序的 1-based
连续序号）排序、键本身不落库（app/authors/pipeline.py 脚注装配），故 k=列表
位置 1-based——与公开页渲染器同口径（app/api/public_render.py）。
"""
import pytest

from app.models import Article, ArticleReaction, Author, Item


def _seed_article(db, *, citations=None, extra=None):
    author = Author(name="详情作者", model="m")
    db.add(author)
    db.commit()
    item_a = Item(source_id=_seed_source(db), guid="g-ca",
                  url="https://example.com/source-a", title="被引条目A",
                  content_text="正文A")
    db.add(item_a)
    db.commit()
    article = Article(author_id=author.id, title="富化文章", body="正文",
                      citations=(citations if citations is not None
                                 else [{"item_id": item_a.id, "quote": "引文A"}]),
                      citation_violated=False, ai_label=True)
    if extra:
        for key, value in extra.items():
            setattr(article, key, value)
    db.add(article)
    db.commit()
    return author, article, item_a


def _seed_source(db):
    from app.models import Direction, Source

    d = Direction(name=f"详情方向{db.query(Direction).count() + 1}", prompt="p")
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url="https://example.com/feed")
    db.add(src)
    db.commit()
    return src.id


def test_article_detail_full_enriched_fields(auth_client, db_session):
    author, article, item_a = _seed_article(db_session)
    db_session.add_all([
        ArticleReaction(article_id=article.id, visitor_hash="cookie:v1",
                        verdict="like"),
        ArticleReaction(article_id=article.id, visitor_hash="cookie:v2",
                        verdict="like"),
        ArticleReaction(article_id=article.id, visitor_hash="cookie:v3",
                        verdict="dislike"),
    ])
    db_session.commit()
    r = auth_client.get(f"/api/articles/{article.id}")
    assert r.status_code == 200
    body = r.json()
    # 既有字段不动
    for field in ("id", "author_id", "title", "body", "status"):
        assert field in body
    # 增补字段
    assert body["author_name"] == "详情作者"
    assert body["created_at"] is not None
    assert body["bookmarked"] is False
    assert body["citation_violated"] is False
    assert body["ai_label"] is True
    assert body["reactions"] == {"likes": 2, "dislikes": 1}


def test_article_detail_citations_enriched_with_k_url_title(auth_client,
                                                            db_session):
    _, article, item_a = _seed_article(db_session)
    body = auth_client.get(f"/api/articles/{article.id}").json()
    assert body["citations"] == [
        {"k": 1, "item_id": item_a.id, "quote": "引文A",
         "url": "https://example.com/source-a", "item_title": "被引条目A"},
    ]


def test_article_detail_citation_item_missing_keeps_k_and_quote(auth_client,
                                                                db_session):
    """引用指向的 item 已不存在（清理后）：k/quote 保留，url/item_title 为
    null——引用卡仍可呈现序号与 AI 原句，跳转降级归前端。"""
    _, article, _ = _seed_article(
        db_session, citations=[{"item_id": 99999, "quote": "已清理条目的引文"}])
    body = auth_client.get(f"/api/articles/{article.id}").json()
    assert body["citations"] == [
        {"k": 1, "item_id": 99999, "quote": "已清理条目的引文",
         "url": None, "item_title": None},
    ]


def test_article_detail_viewer_reacted_null_without_row(auth_client, db_session):
    _, article, _ = _seed_article(db_session)
    body = auth_client.get(f"/api/articles/{article.id}").json()
    assert body["viewer_reacted"] is None


def test_article_detail_viewer_reacted_like_via_feedback_chain(auth_client,
                                                               db_session):
    """当前访客经 /feedback 点赞后详情可见自己的反应位（visitor_hash 主备链
    同一取法——cookie 主、IP+UA 兜底）。"""
    _, article, _ = _seed_article(db_session)
    r = auth_client.post("/feedback", json={"article_id": article.id,
                                            "verdict": "like"})
    assert r.status_code == 200, r.text
    body = auth_client.get(f"/api/articles/{article.id}").json()
    assert body["viewer_reacted"] == "like"
    assert body["reactions"]["likes"] == 1


def test_article_detail_viewer_reacted_comment_only_row_is_null(auth_client,
                                                                db_session):
    """仅 comment 形态行不计入反应位（comment 不占 like/dislike 二位）——
    防御分支：现实写入路径不产 comment 行，此处直插行验证读取侧口径。"""
    _, article, _ = _seed_article(db_session)
    db_session.add(ArticleReaction(article_id=article.id,
                                   visitor_hash="cookie:commenter",
                                   verdict="comment"))
    db_session.commit()
    body = auth_client.get(f"/api/articles/{article.id}",
                           cookies={"nw_visitor": "commenter"}).json()
    assert body["viewer_reacted"] is None
    assert body["reactions"] == {"likes": 0, "dislikes": 0}


def test_article_detail_not_found_coded_error(auth_client):
    r = auth_client.get("/api/articles/99999")
    assert r.status_code == 404
    assert r.json() == {"code": "ARTICLE_NOT_FOUND", "message": "文章不存在"}
