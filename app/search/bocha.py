"""博查 Web Search（api.bocha.cn/v1/web-search，Bing 兼容响应）。

字段映射（官方文档 Web Search API.txt）：
- data.webPages.value[]：name→title、url→url、snippet→snippet、summary→content
  （summary=true 时才有）、datePublished→published_at（UTC+8，官方注明
  dateLastCrawled 实为发布时间且 v2 才修——用 datePublished）。
- freshness 可透传（noLimit/oneDay/.../YYYY-MM-DD..YYYY-MM-DD）。
"""
from __future__ import annotations

from typing import Any

from .. import config
from .base import HTTPSearchProvider, SearchError, SearchResult, _parse_dt

ENDPOINT = "https://api.bocha.cn/v1/web-search"


class BochaSearchProvider(HTTPSearchProvider):
    name = "bocha"

    def __init__(self, *, api_key: str | None = None, timeout: float = 30.0) -> None:
        super().__init__(timeout=timeout)
        self._api_key = api_key or config.BOCHA_API_KEY
        if not self._api_key:
            raise SearchError("bocha provider 缺少 API Key（.env bochaaiAPIKey）")

    def _search(self, query: str, count: int, opts: dict[str, Any]) -> list[SearchResult]:
        payload: dict[str, Any] = {
            "query": query,
            "count": max(1, min(int(count), 50)),
            "summary": bool(opts.get("summary", True)),
            "freshness": opts.get("freshness", "noLimit"),
        }
        body = self._post_json(ENDPOINT, payload, {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        })
        if body.get("code") not in (200, None) or not isinstance(body.get("data"), dict):
            raise SearchError(f"bocha 响应异常: {str(body)[:300]}")
        web_pages = (body.get("data") or {}).get("webPages") or {}
        out: list[SearchResult] = []
        for v in web_pages.get("value") or []:
            out.append(SearchResult(
                title=str(v.get("name") or "").strip(),
                url=str(v.get("url") or "").strip(),
                snippet=str(v.get("snippet") or "").strip(),
                content=str(v.get("summary") or "").strip(),
                published_at=_parse_dt(v.get("datePublished")),
                raw=v,
            ))
        return out
