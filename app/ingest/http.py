"""出网 httpx 客户端工厂——实现已上提至 app/transport/http.py（传输脊中立化批）。

UA 策略（site_config honest/custom）与 proxy 参数位（env HTTPX_PROXY）的
完整说明见 transport/http.py；本模块保留薄 re-export 层维持既有 import 面
（rss/web/search/hot 采集通道零改动）。新增代码禁止从本模块出网——请直接
`from ..transport.http import ...`。
设计依据见 docs/design-index.md「TR-1」「R9」。
"""
from __future__ import annotations

import httpx  # noqa: F401  保留既有打桩面（app.ingest.http.httpx 与全局模块同体）

from ..transport.http import (
    PRODUCT_NAME,
    PROXY_ENV_KEY,
    effective_user_agent,
    honest_user_agent,
    http_client,
    proxy_url,
)

__all__ = [
    "PRODUCT_NAME",
    "PROXY_ENV_KEY",
    "effective_user_agent",
    "honest_user_agent",
    "http_client",
    "proxy_url",
]
