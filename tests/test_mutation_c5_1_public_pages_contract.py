"""公开页 SSR 数据面与页面契约测试（C5-1 变异分诊批：app/api/public 面）。

覆盖口径（设计依据见 docs/design-index.md「AC-16.1」「AC-16.2」「AC-16.3」
「AC-02.1」「ADR-7」）：
- 模式 B 降深列表数据面：公开方向内 OK+passed+FETCHED 条目、按相关分降序
  （失败打分行/未过阈条目/非正常抓取/跨方向条目不进列表）；
- 模式 C 文章页：路由到请求的文章本体（双开关数据面，不串文章）；
- 页面契约：OG 标题/摘要 meta 注入（SEO 面向搜索引擎优化——规范的
  标题/摘要 meta）、静态资源版本锚引用（?v=<版本>，配合响应头 immutable）；
- sitemap URL 前缀：配置 base 时末尾斜杠归一（不产双斜杠），未配置时
  仅路径形态。
"""
import re

import pytest

from app import siteconfig
from app.models import Article, Author, Direction, Item, ScoreResult, Source


def _set_mode(db, mode: str, directions: list[int] | None = None,
              base_url: str | None = None):
    siteconfig.set_config(db, "public_mode", mode)
    if directions is not None:
        siteconfig.set_config(db, "public_directions", directions)
    if base_url is not None:
        siteconfig.set_config(db, "public_base_url", base_url)
    db.commit()


def _direction_with_item(db, name, guid, *, direction=None, status="OK",
                         passed=True, fetch_status="FETCHED", score=90):
    d = direction or Direction(name=name, prompt="p")
    db.add(d)
    db.flush()
    src = Source(direction_id=d.id, url=f"https://example.com/{guid}")
    db.add(src)
    db.flush()
    it = Item(source_id=src.id, guid=guid, url=f"https://example.com/{guid}",
              title=f"条目{guid}", content_text=f"条目{guid}的首句。",
              fetch_status=fetch_status, direction_id=d.id)
    db.add(it)
    db.flush()
    db.add(ScoreResult(item_id=it.id, direction_id=d.id, model="m",
                       relevance_score=score, quality_score=80,
                       status=status, passed=passed))
    db.commit()
    return d, it


def _article(db, *, name, visible=True, public=True, title="文章标题"):
    author = Author(name=name, model="m", public_visible=visible)
    db.add(author)
    db.flush()
    a = Article(author_id=author.id, title=title, body="正文首句。次句。",
                citations=[], public=public, ai_label=True)
    db.add(a)
    db.commit()
    return author, a


def test_mode_b_list_data_scope_and_rank_order(api_client, db_session):
    """模式 B 数据面四过滤 + 降序：仅公开方向内 OK+passed+FETCHED 条目进
    列表（AC-16.1 数据面口径）；同列表内按相关分降序呈现。"""
    db = db_session
    d_pub, _ = _direction_with_item(db, "公开方向", "low", score=50)   # 先建低分
    _, top = _direction_with_item(db, "公开方向", "top", direction=d_pub,
                                  score=90)                            # 后建高分
    _direction_with_item(db, "公开方向", "failedscore", direction=d_pub,
                         status="FAILED")
    _direction_with_item(db, "公开方向", "unpassed", direction=d_pub,
                         passed=False)
    _direction_with_item(db, "公开方向", "duprow", direction=d_pub,
                         fetch_status="DUP")
    _direction_with_item(db, "别的方向", "otherdir")
    _set_mode(db, "B", directions=[d_pub.id])
    html = api_client.get("/public").text
    assert "条目top" in html and "条目low" in html
    assert "条目failedscore" not in html  # 失败打分行不进
    assert "条目unpassed" not in html     # 未过阈不进
    assert "条目duprow" not in html       # 非正常抓取不进
    assert "条目otherdir" not in html     # 非公开方向不进
    # 相关分降序（高分条目创建序在后——区分自然序与分数序）
    assert html.index("条目top") < html.index("条目low")


def test_mode_c_article_page_routes_to_requested_article(api_client, db_session):
    """文章页路由到请求的文章本体：两篇公开文章并存时按 article_id 取对应
    篇（不串文章——路径参数是数据面主键口径）。"""
    db = db_session
    _, first = _article(db, name="作者甲", title="第一篇标题")
    _, second = _article(db, name="作者乙", title="第二篇标题")
    _set_mode(db, "C")
    r = api_client.get(f"/public/article/{second.id}")
    assert r.status_code == 200
    assert "第二篇标题" in r.text
    assert "第一篇标题" not in r.text
    assert "作者乙" in r.text  # 文章页呈现作者名（AC-16.2 作者呈现面）


def test_mode_c_article_page_author_not_visible_404(api_client, db_session):
    """文章公开但作者未勾选公开：文章页 404 合规页（双开关同真才放行，
    不泄露存在性——AC-16.2 作者可见性口径）。"""
    db = db_session
    _, hidden = _article(db, name="隐作者", visible=False)
    _set_mode(db, "C")
    assert api_client.get(f"/public/article/{hidden.id}").status_code == 404


def test_public_home_carries_og_title_and_description_meta(api_client, db_session):
    """模式 C 公开首页注入 OG 标题与摘要 meta（SEO 页面级：规范的
  标题/摘要 meta——面向搜索引擎的页面契约，模式 A 除外）。"""
    _set_mode(db_session, "C")
    html = api_client.get("/public").text
    assert '<meta property="og:title"' in html
    assert '<meta property="og:description"' in html


def test_public_pages_reference_static_assets_with_version_anchor(
        api_client, db_session):
    """公开页静态引用带版本锚（?v=<版本>，配合响应头 immutable 段——
    同版本内容不变可永久缓存，版本随进程启动变化即全量失效）。"""
    _set_mode(db_session, "C")
    r = api_client.get("/login")  # 全模式可达的 HTML 页
    assert r.status_code == 200
    assert re.search(r"\?v=\d+", r.text)


def test_sitemap_base_url_trailing_slash_normalized(api_client, db_session):
    """sitemap URL 前缀末尾斜杠归一：base 配置带尾斜杠时不产生双斜杠 URL。"""
    db = db_session
    d_pub, _ = _direction_with_item(db, "站点地图方向", "sm")
    _set_mode(db, "B", directions=[d_pub.id],
              base_url="https://example.org/")
    body = api_client.get("/sitemap.xml").text
    assert "https://example.org/public" in body
    assert "example.org//public" not in body


def test_sitemap_base_url_absent_renders_relative_paths(api_client, db_session):
    """未配置 base 时 sitemap 仅路径形态（URL 形态 as-implemented：空前缀
    直接拼接路径，不注入占位值）。"""
    db = db_session
    d_pub, _ = _direction_with_item(db, "相对路径方向", "rel")
    _set_mode(db, "B", directions=[d_pub.id])
    body = api_client.get("/sitemap.xml").text
    assert "<loc>/public</loc>" in body
    assert "XXXX" not in body
