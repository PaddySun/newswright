"""通用搜索调用底座（能力④A）：与 LLM provider 层同构的"抽象 + 子类 + 注册"。

扩展纪律：未来接入任何新搜索提供商 = 新增一个 SearchProvider 子类 + registry 注册
（对照：新 LLM 提供商 = 新增 LLMProvider 子类）。

统一结果模型 SearchResult（各provider 的鉴权/端点/字段映射在子类内消化）；
统一超时/重试（网络类失败 ≤2 次指数退避）/报错脱敏（Key 不进日志）。

额度闸不在本层（transport 保持纯净）：调用方经 app.search.quota.check_and_count()
判定后调用，见 pipeline.py。
"""
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger("newswright.search")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    content: str = ""  # 全文/动态摘要，可空（腾讯 lite 版为空）
    published_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)  # 原始条目存档


class SearchError(Exception):
    """搜索调用失败（message 不得含 Key）。"""


def _scrub(text: str) -> str:
    return text.replace("sk-", "sk-***") if text else text


def _parse_dt(value: str | None) -> datetime | None:
    """尽力解析发布时间；失败返回 None（不致命）。"""
    if not value:
        return None
    v = str(value).strip()
    for cand in (v, v.replace("Z", "+00:00"), v + "+08:00" if len(v) == 10 else None):
        if not cand:
            continue
        try:
            dt = datetime.fromisoformat(cand)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class SearchProvider(ABC):
    """同步搜索 provider。子类实现 _search；基类负责重试与脱敏。"""

    name: str = "base"

    @abstractmethod
    def _search(self, query: str, count: int, opts: dict[str, Any]) -> list[SearchResult]:
        """单次真实调用。网络/服务错误抛 SearchError。"""

    def search(self, query: str, count: int = 10, **opts: Any) -> list[SearchResult]:
        """重试包装：网络类失败 ≤2 次（指数退避 1s/2s），耗尽抛 SearchError。"""
        last_err: Exception | None = None
        attempt = 0
        while attempt <= 2:
            try:
                return self._search(query, count, opts)
            except SearchError as e:
                if not getattr(e, "retryable", False):
                    raise
                last_err = e
            except httpx.HTTPError as e:
                last_err = SearchError(f"{type(e).__name__}: {e}")
                last_err.retryable = True  # type: ignore[attr-defined]
            attempt += 1
            if attempt <= 2:
                delay = 2 ** (attempt - 1)
                log.warning("搜索 %s 失败（%.0fs 后重试）: %s", self.name, delay, last_err)
                time.sleep(delay)
        raise SearchError(f"{self.name} 搜索失败（重试耗尽）: {last_err}")


class HTTPSearchProvider(SearchProvider):
    """带鉴权头的 HTTP 搜索 provider 公共部分。"""

    def __init__(self, *, timeout: float = 30.0, db=None) -> None:
        self._timeout = timeout
        self._db = db  # 出网统一出口的 UA 策略读取面（可为 None=honest 无邮箱形态）

    def _post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        from ..ingest.http import http_client

        with http_client(self._db, timeout=self._timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
        if resp.status_code in RETRYABLE_STATUS:
            e = SearchError(f"HTTP {resp.status_code}: {_scrub(resp.text[:300])}")
            e.retryable = True  # type: ignore[attr-defined]
            raise e
        if resp.status_code >= 400:
            raise SearchError(f"HTTP {resp.status_code}: {_scrub(resp.text[:300])}")
        try:
            return resp.json()
        except json.JSONDecodeError as e:
            raise SearchError(f"响应非 JSON: {e}") from e


__all__ = ["SearchProvider", "SearchResult", "SearchError", "HTTPSearchProvider", "_parse_dt"]
