"""读者反馈端点（匿名可访问——独立于全局会话守卫的路由，注册形态参照
auth 路由先例：守卫豁免端点放独立 router，不挂在带守卫的公共 router 上）。

契约（技术书 §3 /feedback）：like/dislike 匿名可——去重身份由服务端从
HttpOnly cookie 提取（缺失时 IP+UA 兜底），请求体不携带身份字段（防伪造
刷量）；comment 要求登录态（匿名 403 AUTH_REQUIRED_COMMENT）。
设计依据见 docs/design-index.md「AC-13.1」「AC-13.2」「AC-13.3」「D7」。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import siteconfig
from ..authors.memory import record_feedback
from ..db import get_session
from ..models import Article, ArticleReaction
from ..timeline import local_day_start, site_zone
from .auth import get_current_user
from .deps import FeedbackRateLimiter, get_client_ip, visitor_hash

# 无会话守卫的独立路由（匿名反馈入口）
router = APIRouter()

# 进程内 per-IP 小时频控器（SR-1；单进程前提 ADR-2，重启清零可接受）
feedback_limiter = FeedbackRateLimiter()

DEFAULT_IP_HOURLY_LIMIT = 30
DEFAULT_ARTICLE_DAILY_LIMIT = 100


def _rate_limited() -> HTTPException:
    return HTTPException(429, {"code": "FEEDBACK_RATE_LIMITED",
                               "message": "反馈提交过于频繁，请稍后再试"})


class FeedbackIn(BaseModel):
    """请求体刻意不含任何身份字段：访客身份一律服务端提取（防伪造刷量）。"""
    article_id: int
    verdict: str  # like | dislike | comment
    text: str | None = Field(default=None, max_length=500)


@router.post("/feedback")
def feedback(payload: FeedbackIn, request: Request, db: Session = Depends(get_session)):
    # per-IP 小时频控（SR-1）：cookie 身份可轮换，IP 桶是不可伪造维度——
    # 入口先于一切分支（like/dislike/comment 全部计数，含 404/422 请求）
    ip = get_client_ip(request, db)
    ip_limit = int(siteconfig.get_config(db, "feedback_ip_hourly_limit")
                   or DEFAULT_IP_HOURLY_LIMIT)
    if not feedback_limiter.allow(ip, limit=ip_limit):
        raise _rate_limited()

    article = db.get(Article, payload.article_id)
    if article is None:
        raise HTTPException(404, "article not found")

    if payload.verdict == "comment":
        # 文字评价要求登录态（匿名只可点赞/点踩）；登录用户行为不变（回流记忆）
        user = get_current_user(request, db)
        if user is None:
            raise HTTPException(403, {"code": "AUTH_REQUIRED_COMMENT",
                                      "message": "文字评价需登录后提交"})
        record_feedback(db, article, verdict="comment", comment=payload.text)
        return {"counted": True}

    if payload.verdict not in ("like", "dislike"):
        raise HTTPException(422, "verdict must be like|dislike|comment")

    # 匿名点赞/点踩：唯一约束 (article_id, visitor_hash) 去重——重复调用不再
    # 计数（200 + already_counted）；首次计数同时回流作者记忆（AC-13.3）。
    v_hash = visitor_hash(request, db)
    exists = (db.query(ArticleReaction.id)
              .filter_by(article_id=article.id, visitor_hash=v_hash)
              .one_or_none())
    if exists is not None:
        return {"counted": False, "reason": "already_counted"}
    # per-article 聚合日上限（SR-1）：DB 计数当日行数（站点时区日切，
    # 与预算日同口径）——跨重启诚实、免新增状态；already_counted 幂等不受影响
    daily_limit = int(siteconfig.get_config(db, "feedback_article_daily_limit")
                      or DEFAULT_ARTICLE_DAILY_LIMIT)
    today_count = (db.query(ArticleReaction.id)
                   .filter(ArticleReaction.article_id == article.id,
                           ArticleReaction.created_at
                           >= local_day_start(site_zone(db)))
                   .count())
    if today_count >= daily_limit:
        raise _rate_limited()
    db.add(ArticleReaction(article_id=article.id, visitor_hash=v_hash,
                           verdict=payload.verdict))
    # 先落库再回流：记忆闸丢弃回流时 reaction 照常入库（AC-1.3——不再依赖
    # add_memory 内的 commit 顺带提交）
    db.commit()
    record_feedback(db, article, verdict=payload.verdict)
    return {"counted": True}
