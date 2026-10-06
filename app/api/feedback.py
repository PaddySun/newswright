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

from ..authors.memory import record_feedback
from ..db import get_session
from ..models import Article, ArticleReaction
from .auth import get_current_user
from .deps import visitor_hash

# 无会话守卫的独立路由（匿名反馈入口）
router = APIRouter()


class FeedbackIn(BaseModel):
    """请求体刻意不含任何身份字段：访客身份一律服务端提取（防伪造刷量）。"""
    article_id: int
    verdict: str  # like | dislike | comment
    text: str | None = Field(default=None, max_length=500)


@router.post("/feedback")
def feedback(payload: FeedbackIn, request: Request, db: Session = Depends(get_session)):
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
    db.add(ArticleReaction(article_id=article.id, visitor_hash=v_hash,
                           verdict=payload.verdict))
    record_feedback(db, article, verdict=payload.verdict)
    return {"counted": True}
