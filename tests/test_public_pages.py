"""公开页 SSR 三模式测试（AC-16.1/16.2 + AC-02.1/02.2）。

模式 A：一切公开路由落 404 合规页（自定义 HTML，无 API 结构泄露）；
模式 B：降深列表条目恰三字段（标题/原文首句摘要/原文链接），零站内正文、
零 AI 生成内容；
模式 C：文章卡片流 + 文章页白名单渲染 + 转义 + AI 标识开关联动 + 作者
public_visible 过滤。
设计依据见 docs/design-index.md「AC-16.1」「AC-16.2」「AC-02.1」「AC-02.2」
「ADR-7」。
"""
import pytest

from app import siteconfig
from app.models import Article, Author, Direction, Item, ScoreResult, Source


def _set_mode(db, mode: str, directions: list[int] | None = None) -> None:
    siteconfig.set_config(db, "public_mode", mode)
    if directions is not None:
        siteconfig.set_config(db, "public_directions", directions)
    db.commit()


@pytest.fixture()
def scored_item(db_session):
    """一条打分通过的公开方向条目（模式 B 数据面）。"""
    direction = Direction(name="公开方向", prompt="p")
    db_session.add(direction)
    db_session.flush()
    source = Source(direction_id=direction.id, url="https://example.com/feed",
                    )
    db_session.add(source)
    db_session.flush()
    item = Item(source_id=source.id, guid="g1", url="https://example.com/a1",
                title="公开条目标题",
                content_text="这是原文的第一句话。这是原文的第二句话。",
                fetch_status="FETCHED", direction_id=direction.id)
    db_session.add(item)
    db_session.flush()
    db_session.add(ScoreResult(item_id=item.id, direction_id=direction.id,
                               model="m", relevance_score=90, quality_score=80,
                               status="OK", passed=True))
    db_session.commit()
    return item


def _article(db_session, *, name="公开作者", visible=True, public=True,
             ai_label=True, body="正文第一句。第二句。"):
    author = Author(name=name, model="m", public_visible=visible, bio="作者简介")
    db_session.add(author)
    db_session.flush()
    article = Article(author_id=author.id, title="公开文章标题", body=body,
                      citations=[], public=public, ai_label=ai_label)
    db_session.add(article)
    db_session.commit()
    return author, article


def test_mode_a_all_public_routes_compliance_404(api_client, db_session):
    """模式 A（默认）：公开首页/文章页/作者页/sitemap/feed 全部落 404 合规页；
    根路径同样 404（AC-02.1）。响应体为 HTML 且不泄露 API 路径结构（AC-02.2）。"""
    _set_mode(db_session, "A")
    for path in ("/public", "/public/article/1", "/public/author/1",
                 "/sitemap.xml", "/feed.xml", "/"):
        r = api_client.get(path)
        assert r.status_code == 404, path
        assert "text/html" in r.headers["content-type"], path
        assert "页面不存在" in r.text, path
    # 不泄露 API 结构（部署矩阵硬条款②：合规期不暴露端点面）
    assert "/api/" not in api_client.get("/public").text
    # robots 全站拒抓（AC-02.3）
    robots = api_client.get("/robots.txt")
    assert robots.status_code == 200
    assert "Disallow: /" in robots.text


def test_mode_a_invalid_mode_value_falls_back_to_a(api_client, db_session):
    """非法模式值（如 "X"）回退 A——暴露面取最紧侧（合规期兜底）。"""
    _set_mode(db_session, "X")
    assert api_client.get("/public").status_code == 404


def test_mode_b_exactly_three_fields_no_body_no_ai(api_client, db_session, scored_item):
    """模式 B 降深：条目恰三字段（标题/原文首句/原文链接）；不含站内正文
    第二句、不含任何 AI 生成文章内容（AC-16.1）。"""
    _article(db_session, name="模式B作者")  # AI 文章存在也不得出现
    _set_mode(db_session, "B", directions=[scored_item.direction_id])
    r = api_client.get("/public")
    assert r.status_code == 200
    assert "公开条目标题" in r.text
    assert "这是原文的第一句话。" in r.text  # 首句在
    assert "第二句话" not in r.text  # 站内正文不出现（仅一句话摘要）
    assert "公开文章标题" not in r.text  # AI 文章零出现
    assert 'href="https://example.com/a1"' in r.text  # 原文链接在


def test_mode_c_article_card_stream_with_ai_label_switch(api_client, db_session):
    """模式 C 首页：双开关（article.public + author.public_visible）过滤；
    AI 标识随 article.ai_label 开关联动（AC-16.2）。"""
    visible_author, visible_article = _article(db_session, name="展示作者")
    hidden_author, hidden_article = _article(db_session, name="隐藏作者", visible=False)
    _article(db_session, name="无标识作者", ai_label=False)
    _set_mode(db_session, "C")
    html = api_client.get("/public").text
    assert "公开文章标题" in html
    assert "AI 展示作者 生成" in html  # AI 标识默认开
    assert "AI 无标识作者 生成" not in html  # ai_label 关闭 → 无标注
    # 未勾选公开的作者：文章与其人都不出现
    assert "隐藏作者" not in html
    # 未公开的文章不出现（article.public=False）
    hidden_article.public = False
    db_session.commit()
    another, another_article = _article(db_session, name="另一作者", public=False)
    html2 = api_client.get("/public").text
    assert "另一作者" not in html2


def test_mode_c_article_page_whitelist_render_and_escape(api_client, db_session):
    """模式 C 文章页：白名单渲染（标题/强调/链接/脚注转链接）+ HTML 转义
    （script 标签失去语义）+ AI 标识。"""
    author, article = _article(
        db_session, name="渲染作者",
        body="# 标题一\n\n**加粗** 与 [链接](https://example.com/x)。\n\n"
             "<script>alert(1)</script>\n\n正文引用[^1]。\n\n[^1]: 引文内容\n")
    db_session.add(article)
    db_session.commit()
    _set_mode(db_session, "C")
    r = api_client.get(f"/public/article/{article.id}")
    assert r.status_code == 200
    html = r.text
    assert "<h1>标题一</h1>" in html
    assert "<strong>加粗</strong>" in html
    assert '<a href="https://example.com/x"' in html
    # 转义双层：script 标签文本化，不构成活动标记
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    # 脚注转链接：引用位锚点 + 文末引用区
    assert 'href="#fn-1"' in html
    assert 'id="fn-1"' in html


def test_mode_c_article_hidden_or_wrong_mode_compliance_404(api_client, db_session):
    """模式 C 下未公开文章/未公开作者落 404 合规页（不泄露存在性）；
    模式 B 下文章页路由同样 404（文章详情仅模式 C）。"""
    hidden_author, hidden_article = _article(db_session, name="隐文作者", public=False)
    _set_mode(db_session, "C")
    assert api_client.get(f"/public/article/{hidden_article.id}").status_code == 404
    _set_mode(db_session, "B")
    visible_author, visible_article = _article(db_session, name="显文作者")
    assert api_client.get(f"/public/article/{visible_article.id}").status_code == 404


def test_mode_c_author_page_public_visible_filter(api_client, db_session):
    """作者公开页：public_visible 作者可达（bio+其公开文章）；未勾选作者 404。"""
    visible_author, _ = _article(db_session, name="主页作者", body="主页作者文章首句。尾句。")
    hidden_author, _ = _article(db_session, name="隐主页作者", visible=False)
    _set_mode(db_session, "C")
    r = api_client.get(f"/public/author/{visible_author.id}")
    assert r.status_code == 200
    assert "主页作者" in r.text and "作者简介" in r.text
    assert api_client.get(f"/public/author/{hidden_author.id}").status_code == 404


def test_login_page_reachable_in_all_modes(api_client, db_session):
    """登录页全模式可达（模式 A 合规期站长仍需登录配置站点）。"""
    for mode in ("A", "B", "C"):
        _set_mode(db_session, mode)
        r = api_client.get("/login")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
