"""认证端点（G1/W1，AC-01.1~01.5）：登录、改密。全仓第一批带 /api 前缀的路径。

错误体契约（技术书 §3 Error schema）：{"code","message"}——经 main.py 的
exception handler 从 HTTPException(detail={"code","message"}) 规范化输出。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import siteconfig
from ..auth import (
    COOKIE_HTTP_ONLY,
    COOKIE_NAME,
    COOKIE_SAMESITE,
    get_valid_session,
    hash_password,
    issue_session,
    verify_password,
)
from ..db import get_session
from ..models import User
from .deps import LoginRateLimiter, get_client_ip

router = APIRouter()

# 进程内限速器（单进程前提 ADR-2，重启清零可接受）；登录限速是 get_client_ip 的第一个消费者
login_limiter = LoginRateLimiter()


def get_current_user(request: Request, db: Session) -> User | None:
    """cookie → sessions 表 → 未过期 → user；否则 None（调用方决定 401 语义）。"""
    session_id = request.cookies.get(COOKIE_NAME)
    sess = get_valid_session(db, session_id)
    if sess is None:
        return None
    return db.get(User, sess.user_id)


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


@router.post("/api/auth/login")
def auth_login(payload: LoginIn, request: Request, db: Session = Depends(get_session)):
    """登录（AC-01.1b/01.2）：argon2id 校验 → Set-Cookie 会话；5 次失败冷却 15 分钟。"""
    client_ip = get_client_ip(request, db)
    if not login_limiter.allow(client_ip):
        raise _error(429, "AUTH_RATE_LIMITED", "登录失败次数过多，请 15 分钟后重试")
    user = db.query(User).filter_by(username=payload.username).one_or_none()
    if user is None or not verify_password(user.password_hash, payload.password):
        login_limiter.record_failure(client_ip)
        raise _error(401, "AUTH_INVALID", "用户名或密码错误")
    login_limiter.record_success(client_ip)
    duration_days = siteconfig.get_config(db, "session_duration_days")
    sess = issue_session(db, user, duration_days=duration_days)
    resp = JSONResponse({"username": user.username})
    # Secure 位暂不加（本里程碑本地 http 形态）；见 app/auth.py COOKIE_* 注释
    resp.set_cookie(COOKIE_NAME, sess.id, httponly=COOKIE_HTTP_ONLY,
                    samesite=COOKIE_SAMESITE, path="/")
    return resp


@router.post("/api/auth/password")
def auth_password(payload: PasswordIn, request: Request, db: Session = Depends(get_session)):
    """改密（AC-01.5）：旧密码校验 → 更新哈希 + must_change_password=false。

    旧会话不强制失效，但旧密码立即可验证失效（旧密码登录落 401）。
    本端点豁免首登改密门禁（must_change_password=true 时唯一放行端点之一）。
    """
    user = get_current_user(request, db)
    if user is None:
        raise _error(401, "AUTH_REQUIRED", "未认证")
    if not verify_password(user.password_hash, payload.old_password):
        raise _error(401, "AUTH_INVALID", "用户名或密码错误")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    db.commit()
    return {"username": user.username, "must_change_password": False}
