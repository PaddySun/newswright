"""认证底层（G1/W1，ADR-4）：argon2id 密码哈希、会话签发/校验、启动引导。

ADR-4 为什么是服务端 Session + HttpOnly Cookie 而非 JWT：会话可即时吊销
（封禁/改密即生效，morningdeck JWT-in-localStorage 反面教训）、无签名密钥管理、
单机单进程（ADR-2）下无水平扩展诉求。
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy.orm import Session

from . import config
from .models import User, UserSession

log = logging.getLogger("newswright.auth")

# D2/Q2 拍板：argon2id。参数用库默认（安全档），单管理员低频登录可承受。
_hasher = PasswordHasher()

COOKIE_NAME = "nw_session"
# Secure 位本里程碑不加（本地 http 部署形态）；上 HTTPS 拓扑（技术书 §1.3 P1/P2）时
# 应置 True：Set-Cookie 属性位 HttpOnly; Path=/; SameSite=Lax; Secure
COOKIE_HTTP_ONLY = True
COOKIE_SAMESITE = "lax"

SESSION_DURATION_DAYS_DEFAULT = 7  # 与 siteconfig.DEFAULTS 同值（AC-01.4）


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(password_hash: str, plain: str) -> bool:
    try:
        return _hasher.verify(password_hash, plain)
    except VerifyMismatchError:
        return False
    except Exception:  # noqa: BLE001  哈希格式损坏等一律按校验失败
        return False


def issue_session(db: Session, user: User, *, duration_days: float) -> UserSession:
    """签发新会话（id ≥128bit 随机）。保持期限由 site_config 注入（AC-01.4）。"""
    sess = UserSession(
        id=secrets.token_urlsafe(32),
        user_id=user.id,
        expires_at=_now() + timedelta(days=float(duration_days)),
    )
    db.add(sess)
    db.commit()
    return sess


def get_valid_session(db: Session, session_id: str | None) -> UserSession | None:
    """cookie id → 未过期会话；过期/不存在返回 None（调用方落 401 AUTH_REQUIRED）。"""
    if not session_id:
        return None
    sess = db.get(UserSession, session_id)
    if sess is None:
        return None
    exp = sess.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp <= _now():
        return None
    return sess


def _now():
    return datetime.now(timezone.utc)


def bootstrap_admin(db: Session) -> None:
    """启动引导（AC-01.1/D18）：users 表为空时创建 admin（must_change_password=true）。

    密码来自环境变量 NEWSWRIGHT_ADMIN_PASSWORD（config.py 缺失即 SystemExit）；
    已有用户不覆盖。初始密码不进 git/文档/日志。
    """
    if db.query(User.id).first() is not None:
        return
    user = User(
        username="admin",
        password_hash=hash_password(config.NEWSWRIGHT_ADMIN_PASSWORD),
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    log.info("已创建初始管理员 admin（首登需改密）")
