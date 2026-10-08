"""SEO 三件测试：sitemap / robots / feed（AC-16.3/16.4 + AC-02.3）。

三模式断言：sitemap 模式 C 含公开文章与公开页 URL、模式 B 无文章详情、
模式 A 404；robots 模式 A 拒抓、B/C 放行并指向 sitemap；feed 默认 404、
开启后 feedgen 生成有效 RSS 且仅摘要深度（正文全文不进 Feed）。
设计依据见 docs/design-index.md「AC-16.3」「AC-16.4」「AC-02.3」「D8」。
"""
import xml.etree.ElementTree as ET

import pytest

from app import siteconfig
from app.models import Article, Author


def _set(db, key, value):
    siteconfig.set_config(db, key, value)
    db.commit()


def _public_article(db, *, name="SEO 作者", public=True):
    author = Author(name=name, model="m", public_visible=True)
    db.add(author)
    db.flush()
    article = Article(author_id=author.id, title="SEO 文章",
                      body="首句摘要。" + "正文" * 200,
                      citations=[], public=public)
    db.add(article)
    db.commit()
    return author, article


@pytest.fixture()
def public_article(db_session):
    return _public_article(db_session)


def test_sitemap_mode_c_contains_articles_and_pages(api_client, db_session, public_article):
    """模式 C：sitemap 含公开首页 + 作者页 + 全部公开文章 URL。"""
    _set(db_session, "public_mode", "C")
    _set(db_session, "public_base_url", "https://example.com")
    r = api_client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "xml" in r.headers["content-type"]
    root = ET.fromstring(r.text)
    locs = [node.text for node in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert "https://example.com/public" in locs
    assert f"https://example.com/public/author/{public_article[0].id}" in locs
    assert f"https://example.com/public/article/{public_article[1].id}" in locs


def test_sitemap_mode_b_has_no_article_detail(api_client, db_session, public_article):
    """模式 B：sitemap 仅公开页 URL，不含文章详情（任务书 W1 SEO 三件口径）。"""
    _set(db_session, "public_mode", "B")
    r = api_client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "public/article/" not in r.text
    assert "<loc>/public</loc>" in r.text or "public</loc>" in r.text


def test_sitemap_mode_a_is_compliance_404(api_client, db_session):
    _set(db_session, "public_mode", "A")
    assert api_client.get("/sitemap.xml").status_code == 404


def test_robots_allows_and_points_sitemap_when_public(api_client, db_session):
    """模式 B/C：robots 放行并指向 sitemap（AC-16.3）。"""
    for mode in ("B", "C"):
        _set(db_session, "public_mode", mode)
        r = api_client.get("/robots.txt")
        assert r.status_code == 200
        assert "Allow: /" in r.text
        assert "Sitemap: " in r.text and "/sitemap.xml" in r.text


def test_feed_default_off_returns_404(api_client, db_session, public_article):
    """出厂配置：/feed.xml 落 404（AC-16.4）。"""
    _set(db_session, "public_mode", "C")
    assert api_client.get("/feed.xml").status_code == 404


def test_feed_enabled_mode_c_valid_rss_summary_depth_only(api_client, db_session,
                                                          public_article):
    """开启后：模式 C 生成有效 RSS XML；条目仅摘要深度（正文长尾不进 Feed）。"""
    _set(db_session, "public_mode", "C")
    _set(db_session, "feed_enabled", True)
    r = api_client.get("/feed.xml")
    assert r.status_code == 200
    assert "rss" in r.headers["content-type"]
    root = ET.fromstring(r.text)
    items = root.findall(".//item")
    assert len(items) == 1
    assert items[0].findtext("title") == "SEO 文章"
    description = items[0].findtext("description") or ""
    assert "首句摘要" in description
    assert "正文正文正文" not in description  # 全文不进 Feed（仅摘要深度）


def test_feed_mode_a_stays_404_even_when_enabled(api_client, db_session):
    """模式 A：Feed 开关开启仍 404——模式 A 一切公开路由不可达。"""
    _set(db_session, "public_mode", "A")
    _set(db_session, "feed_enabled", True)
    assert api_client.get("/feed.xml").status_code == 404


def test_feed_mode_b_lists_items_with_original_links(api_client, db_session):
    """模式 B：Feed 条目=降深条目（原文链接直出，无站内详情页）。"""
    from app.models import Direction, Item, ScoreResult, Source

    direction = Direction(name="Feed方向", prompt="p")
    db_session.add(direction)
    db_session.flush()
    source = Source(direction_id=direction.id,
                    url="https://example.com/f")
    db_session.add(source)
    db_session.flush()
    item = Item(source_id=source.id, guid="gf", url="https://example.com/feed-item",
                title="Feed条目", content_text="Feed 首句。", fetch_status="FETCHED",
                direction_id=direction.id)
    db_session.add(item)
    db_session.flush()
    db_session.add(ScoreResult(item_id=item.id, direction_id=direction.id,
                               model="m", relevance_score=88, status="OK", passed=True))
    db_session.commit()
    _set(db_session, "public_mode", "B")
    _set(db_session, "public_directions", [direction.id])
    _set(db_session, "feed_enabled", True)
    r = api_client.get("/feed.xml")
    assert r.status_code == 200
    assert "Feed条目" in r.text
    assert "https://example.com/feed-item" in r.text
