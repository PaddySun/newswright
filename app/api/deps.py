"""请求侧依赖（G1/W1）：客户端身份提取与会话守卫。

ADR-5⑤ 单一实现纪律：get_client_ip 是请求侧真实 IP 的唯一提取口——登录限速
（本里程碑）与 D7 匿名反馈兜底哈希（未来）必须共用本函数，禁两处口径漂移。
CDN/WAF 拓扑下 request.client.host 是回源 IP（共享，会造成全员误锁），
由 site_config.client_ip_header 配置提取头（如 CF-Connecting-IP）。
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import siteconfig
from ..auth import get_valid_session
from ..db import get_session
from ..models import User


def get_client_ip(request: Request, db: Session | None = None) -> str:
    """请求侧真实客户端 IP（ADR-5⑤ 提取链）：配置头优先，空 = 直连地址。"""
    if db is not None:
        header_name = siteconfig.get_config(db, "client_ip_header") or ""
        if header_name:
            value = request.headers.get(str(header_name))
            if value and value.strip():
                return value.strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class LoginRateLimiter:
    """登录限速（AC-01.2）：连续 5 次失败后第 6 次起 429，冷却 15 分钟。

    进程内字典实现：单进程前提（ADR-2）下不持久化，重启清零可接受（G1 汇报注明）。
    now 可注入以便测试（等价验证冷却，不真等 15 分钟）。
    """

    MAX_FAILURES = 5
    COOLDOWN_MINUTES = 15

    def __init__(self, now=None):
        from datetime import datetime, timezone

        self._store: dict[str, dict] = {}
        self.now = now or (lambda: datetime.now(timezone.utc))

    def allow(self, key: str) -> bool:
        """是否放行本次尝试：冷却期内一律拒绝（第 6 次起 429，含正确密码）。"""
        rec = self._store.get(key)
        if rec is None:
            return True
        locked_until = rec.get("locked_until")
        if locked_until is not None:
            if self.now() < locked_until:
                return False
            self._store.pop(key, None)  # 冷却结束，计数清零
        return True

    def record_failure(self, key: str) -> None:
        from datetime import timedelta

        rec = self._store.setdefault(key, {"fails": 0, "locked_until": None})
        rec["fails"] += 1
        if rec["fails"] >= self.MAX_FAILURES:
            # 第 5 次失败即起锁：第 6 次尝试（无论密码对错）落 429，冷却 15 分钟
            rec["locked_until"] = self.now() + timedelta(minutes=self.COOLDOWN_MINUTES)

    def record_success(self, key: str) -> None:
        """成功登录清零该身份计数（AC-01.2）。"""
        self._store.pop(key, None)


def require_session(request: Request, db: Session = Depends(get_session)) -> User:
    """会话守卫（AC-01.3/01.4）：cookie → sessions 表 → 未过期 → user；否则 401 AUTH_REQUIRED。

    首登改密门禁（AC-01.1）：must_change_password=true 时一切 API（除 /api/auth/login、
    /api/auth/password 两个豁免端点）返回 403 PASSWORD_CHANGE_REQUIRED。
    注：PASSWORD_CHANGE_REQUIRED 在产品书 AC-01.1 有、技术书 §5 错误码表漏列——
    按 AC 执行，文档缺口已登记 G1 汇报遗留项。
    """
    from .auth import get_current_user

    user = get_current_user(request, db)
    if user is None:
        raise HTTPException(status_code=401,
                            detail={"code": "AUTH_REQUIRED", "message": "未认证"})
    if user.must_change_password:
        raise HTTPException(status_code=403,
                            detail={"code": "PASSWORD_CHANGE_REQUIRED",
                                    "message": "首次登录需先修改密码"})
    return user
