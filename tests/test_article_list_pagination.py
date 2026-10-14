"""文章列表分页信封测试（GET /api/articles 增 limit/offset + 四字段增补
——UI2 W0a，服务 P2 文章列表页）。

覆盖口径：信封结构 {items,total,limit,offset}；total=同过滤条件计数（不含
limit/offset，author 过滤后口径）；limit 上限 200 钳制（信封回实际值）；offset
越界=空 items 但 total 不变；负 offset 落既有 400 VALIDATION_ERROR 归一；
每条增补 author_name/created_at/citation_violated/ai_label 在位。
分页语义=limit+offset（站长拍板，docs/design-index.md「UI2 拍板③」）。
"""
import pytest

from app.models import Article, Author


@pytest.fixture()
def author_with_five_articles(db_session):
    author = Author(name="列表作者", model="m")
    db_session.add(author)
    db_session.commit()
    for i in range(5):
        db_session.add(Article(author_id=author.id, title=f"文章{i}", body="b",
                               citations=[{"item_id": 1, "quote": "q"}],
                               citation_violated=(i == 0)))
    db_session.commit()
    return author


def test_article_list_envelope_shape_and_default_paging(auth_client,
                                                        author_with_five_articles):
    r = auth_client.get("/api/articles")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "limit", "offset"}
    assert body["total"] == 5
    assert body["limit"] == 50 and body["offset"] == 0
    assert len(body["items"]) == 5


def test_article_list_items_carry_enriched_fields(auth_client,
                                                  author_with_five_articles):
    body = auth_client.get("/api/articles").json()
    for row in body["items"]:
        # 既有五字段
        for field in ("id", "author_id", "title", "status", "citations",
                      "bookmarked"):
            assert field in row
        assert row["citations"] == 1  # 列表口径维持引用计数
        # 本批增补四字段
        assert row["author_name"] == "列表作者"
        assert row["created_at"] is not None  # ORM 写入默认成文时刻
        assert row["citation_violated"] in (True, False)
        assert row["ai_label"] is True
    violated = [row for row in body["items"] if row["citation_violated"]]
    assert len(violated) == 1


def test_article_list_total_respects_author_filter(auth_client, db_session):
    a1 = Author(name="过滤作者一", model="m")
    a2 = Author(name="过滤作者二", model="m")
    db_session.add_all([a1, a2])
    db_session.commit()
    for _ in range(3):
        db_session.add(Article(author_id=a1.id, title="t", body="b", citations=[]))
    for _ in range(2):
        db_session.add(Article(author_id=a2.id, title="t", body="b", citations=[]))
    db_session.commit()
    body = auth_client.get("/api/articles",
                           params={"author_id": a1.id}).json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    assert all(row["author_id"] == a1.id for row in body["items"])


def test_article_list_limit_clamped_to_two_hundred(auth_client,
                                                   author_with_five_articles):
    body = auth_client.get("/api/articles", params={"limit": 999}).json()
    assert body["limit"] == 200  # 信封回钳制后的实际值


def test_article_list_offset_slice_and_beyond_end(auth_client,
                                                  author_with_five_articles):
    page = auth_client.get("/api/articles", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 5
    assert len(page["items"]) == 2  # id 降序第 3、4 条
    ids = [row["id"] for row in page["items"]]
    all_ids = [row["id"] for row in
               auth_client.get("/api/articles").json()["items"]]
    assert ids == all_ids[2:4]

    beyond = auth_client.get("/api/articles", params={"offset": 100}).json()
    assert beyond["items"] == []
    assert beyond["total"] == 5  # 越界不改 total 口径


def test_article_list_negative_offset_rejected_by_handler(auth_client):
    """负 offset 经参数校验落既有 400 VALIDATION_ERROR 归一（非 422）。"""
    r = auth_client.get("/api/articles", params={"offset": -1})
    assert r.status_code == 400
    assert r.json()["code"] == "VALIDATION_ERROR"
