"""请求侧依赖：客户端身份提取与会话守卫。

ADR-5⑤ 单一实现纪律：get_client_ip 是请求侧真实 IP 的唯一提取口——登录限速
与匿名访客兜底哈希共用本函数，禁两处口径漂移。CDN/WAF 拓扑下
request.client.host 是回源 IP（共享，会造成全员误锁），由 site_config.
client_ip_header 配置提取头（如 CF-Connecting-IP）。
"""
from __future__ import annotations

import hashlib

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import siteconfig
from ..auth import get_valid_session
from ..db import get_session
from ..models import User

VISITOR_COOKIE_NAME = "nw_visitor"


def get_client_ip(request: Request, db: Session | None = None) -> str:
    """请求侧真实客户端 IP（ADR-5⑤ 提取链）：配置头优先，空 = 直连地址。

    ⚠ 反代警告（SR-4）：配置 client_ip_header 后该头的值可被客户端随意
    伪造（直连请求也能携带），从而绕过一切按 IP 的限速/频控（登录限速、反馈
    IP 桶）。仅当服务真实部署在可信反代/CDN 之后（该头由反代覆写、客户端
    无法注入）才可配置本键；直连暴露形态下配置等于放弃 IP 维度闸门。
    """
    if db is not None:
        header_name = siteconfig.get_config(db, "client_ip_header") or ""
        if header_name:
            value = request.headers.get(str(header_name))
            if value and value.strip():
                return value.strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def visitor_hash(request: Request, db: Session | None = None) -> str:
    """匿名访客去重身份（主备双链）：

    主链=服务端签发的 HttpOnly cookie id（nw_visitor）；备链=cookie 缺失时
    sha256(client_ip + UA)。只用 IP 不行：NAT/公司出口下所有访客共享同源 IP，
    只按 IP 去重会把全体访客误并为一个身份（一人点赞=全员不能再点赞）；
    拼 UA 后同 IP 的不同浏览器/客户端仍可区分。IP 提取复用 get_client_ip
    单一实现（与登录限速同口径）。返回值带链路前缀（cookie:/anon:）防两条
    链的值空间意外相撞。"""
    cookie = request.cookies.get(VISITOR_COOKIE_NAME)
    if cookie and cookie.strip():
        return f"cookie:{cookie.strip()}"
    ip = get_client_ip(request, db)
    ua = request.headers.get("user-agent", "")
    digest = hashlib.sha256(f"{ip}\n{ua}".encode("utf-8")).hexdigest()
    return f"anon:{digest}"


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


class FeedbackRateLimiter:
    """反馈入口 per-IP 小时频控（SR-1）：窗口 1 小时上限 N（site_config
    feedback_ip_hourly_limit 注入，缺省 30）——固定窗计数，超窗翻新。

    与 LoginRateLimiter 同址同前提（进程内字典、单进程 ADR-2、重启清零可接受），
    但语义不同：这里是**窗口速率**（不限连续失败、不冷却），防匿名刷量——
    visitor_hash 的 cookie 主链可被客户端随意轮换（换 cookie 即新身份），IP 桶
    是 cookie 之外不可伪造的闸门维度。now 可注入以便测试（等价验证窗口翻新，
    不真等 1 小时）。"""

    def __init__(self, now=None):
        from datetime import datetime, timezone

        self._store: dict[str, int] = {}
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _window_key(self, key: str) -> str:
        hour = self.now().strftime("%Y%m%d%H")
        return f"ip:{key}:{hour}"

    def allow(self, key: str, *, limit: int) -> bool:
        """本次请求是否放行：窗口内未达上限则计数 +1 放行；已达上限拒绝。"""
        window = self._window_key(key)
        count = self._store.get(window, 0)
        if count >= limit:
            return False
        self._store[window] = count + 1
        return True


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
