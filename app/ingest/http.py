"""出网 httpx 客户端工厂（全部采集通道的统一出口）。

礼貌性策略：UA 一律取 site_config 策略键——默认 honest（诚实 UA：产品名 +
联系邮箱位，可被源站识别与联系；httpx 默认 UA 是 WAF 指纹拦截的头号特征），
可切 custom（管理员自配 UA 串）。proxy 为参数位：env HTTPX_PROXY 注入即启用，
不配置行为不变（为代理隧道与未来的原文抽取衔接留钩子，本批不做实际配置）。

设计依据见 docs/design-index.md「R9」（采集公共纪律：UA 策略 + proxy 参数位）。
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from sqlalchemy.orm import Session

from ..siteconfig import get_config

PRODUCT_NAME = "newswright"
PROXY_ENV_KEY = "HTTPX_PROXY"


def honest_user_agent(contact_email: str | None) -> str:
    """诚实 UA 模板：产品名 + 联系邮箱位（未配邮箱则只有产品标识）。"""
    base = f"Mozilla/5.0 (compatible; {PRODUCT_NAME}/1.0; +https://localhost)"
    if contact_email and str(contact_email).strip():
        return f"{base[:-1]}; contact: {str(contact_email).strip()})"
    return base


def effective_user_agent(db: Session | None = None) -> str:
    """实际出网 UA（读 site_config 策略键）：honest=诚实模板；custom=自配串
    （空串回退 honest——空 UA 是更强的拦截指纹）。db 为空时按 honest 无邮箱形态。"""
    if db is None:
        return honest_user_agent(None)
    strategy = str(get_config(db, "ua_strategy") or "honest")
    if strategy == "custom":
        custom = str(get_config(db, "ua_custom") or "").strip()
        return custom or honest_user_agent(get_config(db, "contact_email"))
    return honest_user_agent(get_config(db, "contact_email"))


def proxy_url() -> str | None:
    """proxy 参数位：env HTTPX_PROXY 注入（未配置返回 None——不配置行为不变）。"""
    value = os.environ.get(PROXY_ENV_KEY, "").strip()
    return value or None


def http_client(db: Session | None = None, *, timeout: float = 60.0,
                follow_redirects: bool = True, **kwargs: Any) -> httpx.Client:
    """统一出网客户端：默认 UA 按策略键解析 + proxy 参数位；其余构造参数透传
    （timeout/follow_redirects/max_redirects 等）。请求级 headers 与本客户端
    默认 headers 按 httpx 语义合并（请求级覆盖同名头）。"""
    client_kwargs: dict[str, Any] = {
        "timeout": timeout,
        "follow_redirects": follow_redirects,
        "headers": {"User-Agent": effective_user_agent(db)},
        **kwargs,
    }
    proxy = proxy_url()
    if proxy:
        client_kwargs["proxy"] = proxy
    return httpx.Client(**client_kwargs)
