"""公开页 SSR 路由（模式 A/B/C）+ SEO 三件 + 登录页。

无会话守卫（与 auth/feedback 同形态的独立 router）——公开面的可达性由公开
模式键（site_config.public_mode）而非鉴权控制：
- 模式 A（默认，合规期）：一切公开路由落 404 合规页（自定义 HTML，不泄露
  API 结构）；robots 全站拒抓（AC-02.1/02.2/02.3）；
- 模式 B：降深列表——条目仅标题/原文首句摘要/原文链接三字段，不含站内正文
  与 AI 生成内容（AC-16.1）；
- 模式 C：公开文章卡片流 + 文章页（Markdown 白名单渲染）+ 作者公开页，
  AI 生成内容带"AI <作者名> 生成"标识（AC-16.2）。

数据面过滤（F2 呈现列接线）：模式 C 公开文章 = article.public 且
author.public_visible 双开关同时为真；作者公开页仅放行 public_visible 作者。
设计依据见 docs/design-index.md「AC-16.1」「AC-16.2」「AC-16.3」「AC-16.4」
「AC-16.5」「AC-02.1」「ADR-7」。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .. import siteconfig
from ..db import get_session
from ..models import Article, Author, Item, ScoreResult
from .public_render import first_sentence, render_markdown_whitelist

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# 静态资源版本锚（进程启动时刻）：页面静态引用带 ?v=<版本>，配合响应头
# immutable 段（P2-4）——同版本内容不变可永久缓存，重启换版本即全量失效
STATIC_VERSION = str(int(__import__("time").time()))

# 模式 B 降深列表与 Feed 的条目上限（一次渲染的合理窗口，全量由分页/翻页演进）
PUBLIC_LIST_LIMIT = 50

# 公开模式合法值（非法配置一律回退 A——暴露面取最紧侧）
_VALID_MODES = ("A", "B", "C")


def public_mode(db: Session) -> str:
    """读公开模式键并归一：非 A/B/C 值回退 A（合规期兜底）。"""
    value = siteconfig.get_config(db, "public_mode")
    mode = str(value).strip().upper() if value is not None else "A"
    return mode if mode in _VALID_MODES else "A"


def _public_direction_ids(db: Session) -> list[int]:
    """公开方向 id 列表（JSON 列，容错归一为 int 列表）。"""
    value = siteconfig.get_config(db, "public_directions") or []
    if not isinstance(value, list):
        return []
    return [int(v) for v in value if isinstance(v, (int, float))]


def _base_url(db: Session) -> str:
    """sitemap/feed 绝对 URL 前缀（末尾斜杠归一去除；空=仅路径形态）。"""
    value = str(siteconfig.get_config(db, "public_base_url") or "").strip()
    return value.rstrip("/")


def _render(request: Request, template_name: str, context: dict, status_code: int = 200):
    """模板渲染统一出口（状态码透传——404 合规页复用同一路径）。

    static_version 进全部模板上下文：静态引用带版本 query，配合响应头
    immutable 段（P2-4）——版本随进程启动变化，部署即全量缓存失效。
    """
    context = {"static_version": STATIC_VERSION, **context}
    return templates.TemplateResponse(
        request=request, name=template_name, context=context, status_code=status_code
    )


def mode_a_404(request: Request):
    """404 合规页（模式 A 一切公开路由的统一落点，AC-02.1/02.2）。

    自定义 HTML 模板承载（站长可改模板文件内容），无任何 API 结构/站点能力
    泄露——技术书部署矩阵硬条款"模式 A 合规期不得泄露 API 结构"。
    """
    return _render(request, "compliance-404.html.j2", {}, status_code=404)


def _mode_b_entries(db: Session) -> list[dict]:
    """模式 B 降深条目：恰三字段（标题/原文首句/原文链接）。

    数据面 = 公开方向内打分通过（score_result OK + passed）的正常抓取条目，
    按相关分降序。摘要取原文首句（first_sentence，非 AI 生成）；AI 生成内容
    （文章表）在模式 B 零出现。
    """
    direction_ids = _public_direction_ids(db)
    if not direction_ids:
        return []
    rows = (
        db.query(Item, ScoreResult)
        .join(ScoreResult, ScoreResult.item_id == Item.id)
        .filter(
            ScoreResult.status == "OK",
            ScoreResult.passed.is_(True),
            Item.fetch_status == "FETCHED",
            Item.direction_id.in_(direction_ids),
        )
        .order_by(ScoreResult.relevance_score.desc())
        .limit(PUBLIC_LIST_LIMIT)
        .all()
    )
    return [
        {"title": item.title, "summary": first_sentence(item.content_text),
         "url": item.url}
        for item, _ in rows
    ]


def _public_articles(db: Session) -> list[dict]:
    """模式 C 公开文章卡片：article.public 与 author.public_visible 双开关
    同时为真的文章，附作者名与 AI 标识开关位（ai_label 列，F2 呈现层开关）。"""
    rows = (
        db.query(Article, Author)
        .join(Author, Author.id == Article.author_id)
        .filter(Article.public.is_(True), Author.public_visible.is_(True))
        .order_by(Article.id.desc())
        .limit(PUBLIC_LIST_LIMIT)
        .all()
    )
    return [
        {"id": article.id, "title": article.title,
         "summary": first_sentence(article.body),
         "author_name": author.name, "author_id": author.id,
         "ai_label": bool(article.ai_label)}
        for article, author in rows
    ]


def _visible_author(db: Session, author_id: int) -> Author | None:
    """作者公开页数据面：仅放行勾选公开的作者（未勾选=不存在，404 合规页）。"""
    author = db.get(Author, author_id)
    if author is None or not author.public_visible:
        return None
    return author


def _visible_article(db: Session, article_id: int) -> tuple[Article, Author] | None:
    """文章公开页数据面：双开关过滤；未过=404 合规页（不泄露存在性）。"""
    row = (
        db.query(Article, Author)
        .join(Author, Author.id == Article.author_id)
        .filter(Article.id == article_id,
                Article.public.is_(True), Author.public_visible.is_(True))
        .one_or_none()
    )
    return row


def _citations_with_urls(db: Session, article: Article) -> list[dict]:
    """结构化引用补原文链接（脚注区"原文"跳转）：citations 存储形为
    [{item_id, quote}]，原文 URL 在 item 行——SSR 服务端直连取，不依赖 API。"""
    enriched: list[dict] = []
    for citation in article.citations or []:
        if not isinstance(citation, dict):
            continue
        item = db.get(Item, citation.get("item_id")) if citation.get("item_id") else None
        enriched.append({"item_id": citation.get("item_id"),
                         "quote": citation.get("quote", ""),
                         "url": (item.url if item else "") or ""})
    return enriched


def _og_context(title: str, description: str) -> dict:
    """meta/OG 注入位（模式 B/C 页面共用；模式 A 合规页不注入站点信息）。"""
    return {"og_title": title, "og_description": description}


@router.get("/public")
def public_home(request: Request, db: Session = Depends(get_session)):
    """公开首页：模式分发（A=404 合规页 / B=降深列表 / C=文章卡片流）。"""
    mode = public_mode(db)
    if mode == "A":
        return mode_a_404(request)
    if mode == "B":
        entries = _mode_b_entries(db)
        return _render(request, "public-home.html.j2",
                       {"mode": "B", "entries": entries,
                        **_og_context("Newswright 精选", "精选内容列表")})
    articles = _public_articles(db)
    return _render(request, "public-home.html.j2",
                   {"mode": "C", "articles": articles,
                    **_og_context("Newswright 精选", "AI 作者精选文章")})


@router.get("/public/article/{article_id}")
def public_article(article_id: int, request: Request,
                   db: Session = Depends(get_session)):
    """公开文章页（仅模式 C）：白名单渲染正文 + 脚注转原文链接 + AI 标识 +
    访客点赞按钮（POST /feedback，同 AC-13.1 去重链）。"""
    if public_mode(db) != "C":
        return mode_a_404(request)
    row = _visible_article(db, article_id)
    if row is None:
        return mode_a_404(request)
    article, author = row
    body_html = render_markdown_whitelist(article.body,
                                          _citations_with_urls(db, article))
    return _render(request, "public-article.html.j2",
                   {"article": article, "author": author,
                    "body_html": body_html,
                    "ai_label": bool(article.ai_label),
                    **_og_context(article.title, first_sentence(article.body))})


@router.get("/public/author/{author_id}")
def public_author(author_id: int, request: Request,
                  db: Session = Depends(get_session)):
    """作者公开页（仅模式 C）：bio + 该作者公开文章列表（public_visible 过滤）。"""
    if public_mode(db) != "C":
        return mode_a_404(request)
    author = _visible_author(db, author_id)
    if author is None:
        return mode_a_404(request)
    articles = [a for a in _public_articles(db) if a["author_id"] == author.id]
    return _render(request, "public-author.html.j2",
                   {"author": author, "articles": articles,
                    **_og_context(author.name, author.bio or "")})


@router.get("/sitemap.xml")
def sitemap(request: Request, db: Session = Depends(get_session)):
    """sitemap（AC-16.3）：模式 C=公开页 + 全部公开文章 URL；模式 B=仅公开页
    （无文章详情）；模式 A=404 合规页。URL 前缀取 public_base_url（配置时
    为绝对 URL，符合 sitemap 协议期望）。"""
    mode = public_mode(db)
    if mode == "A":
        return mode_a_404(request)
    base = _base_url(db)
    paths = ["/public"]
    if mode == "C":
        cards = _public_articles(db)
        paths += [f"/public/author/{card['author_id']}" for card in cards]
        paths += [f"/public/article/{card['id']}" for card in cards]
    urls = [f"{base}{path}" for path in paths]
    body = templates.get_template("sitemap.xml.j2").render(urls=urls)
    return Response(content=body, media_type="application/xml")


@router.get("/robots.txt")
def robots(request: Request, db: Session = Depends(get_session)):
    """robots（AC-02.3/AC-16.3）：模式 A=全站 Disallow（无 sitemap 行——
    sitemap 在该模式不可达）；模式 B/C=放行并指向 sitemap。"""
    mode = public_mode(db)
    if mode == "A":
        body = "User-agent: *\nDisallow: /\n"
    else:
        base = _base_url(db)
        body = f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n"
    return Response(content=body, media_type="text/plain")


@router.get("/feed.xml")
def feed(request: Request, db: Session = Depends(get_session)):
    """RSS Feed（AC-16.4）：默认关（404 合规页）；开启后 feedgen 生成，默认
    仅摘要深度（description=首句摘要，正文全文不进 Feed）。模式 A 下即使
    开关开启仍 404（模式 A 一切公开路由不可达）。"""
    from feedgen.feed import FeedGenerator

    enabled = bool(siteconfig.get_config(db, "feed_enabled"))
    mode = public_mode(db)
    if not enabled or mode == "A":
        return mode_a_404(request)

    base = _base_url(db)
    fg = FeedGenerator()
    fg.title("Newswright")
    fg.link(href=f"{base}/public" if base else "/public")
    fg.description("Newswright 精选内容")
    fg.language("zh-cn")
    if mode == "B":
        for entry in _mode_b_entries(db):
            fe = fg.add_entry()
            fe.title(entry["title"])
            fe.link(href=entry["url"])
            fe.description(entry["summary"])
    else:
        for card in _public_articles(db):
            fe = fg.add_entry()
            fe.title(card["title"])
            fe.link(href=f"{base}/public/article/{card['id']}"
                    if base else f"/public/article/{card['id']}")
            fe.description(card["summary"])
    return Response(content=fg.rss_str(pretty=True),
                    media_type="application/rss+xml")


@router.get("/login")
def login_page(request: Request):
    """登录页（全模式可达——模式 A 合规期站长仍需登录配置站点）。"""
    return _render(request, "login.html.j2", {})
