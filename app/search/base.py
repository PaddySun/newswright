"""通用搜索调用底座（能力④A）：与 LLM provider 层同构的"抽象 + 子类 + 注册"。

扩展纪律：未来接入任何新搜索提供商 = 新增一个 SearchProvider 子类 + registry 注册
（对照：新 LLM 提供商 = 新增 LLMProvider 子类）。

统一结果模型 SearchResult（各provider 的鉴权/端点/字段映射在子类内消化）；
统一超时/重试（网络类失败 ≤2 次，退避经传输脊协商：Retry-After 优先/随机化
指数退避）/报错脱敏（Key 不进日志）。HTTP 出网与状态分类走传输脊
app/transport/（此前 UA 策略借道 ingest 工厂与 RETRYABLE_STATUS/_scrub 复制份
已随传输脊中立化批收敛）。耗尽抛 SearchRetryExhausted（域类型兼容 +
RetryExhausted 结构化 reason/errors）。

额度闸不在本层（transport 保持纯净）：调用方经 app.transport.quota.check_and_count()
判定后调用，见 pipeline.py（search/quota.py 保留薄 re-export）。
设计依据见 docs/design-index.md「TR-1」「TR-3」「TR-4」「TR-5」。
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

from ..transport.errors import (
    REASON_ERROR_NOT_RETRYABLE,
    REASON_MAX_RETRIES_EXCEEDED,
    ProviderError,
    RetryExhausted,
)
from ..transport.http import post_json, retry_delay_ms

log = logging.getLogger("newswright.search")


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


class SearchRetryExhausted(RetryExhausted, SearchError):
    """搜索重试终态：保持 SearchError 域类型兼容（既有 except 面零改动），
    同时携带 RetryExhausted 结构化 reason/errors（传输脊耗尽归因）。"""


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
        """重试包装：网络类失败 ≤2 次（退避经传输脊协商），耗尽抛
        SearchRetryExhausted。"""
        last_err: Exception | None = None
        attempt = 0
        attempt_errors: list[Exception] = []
        while attempt <= 2:
            try:
                return self._search(query, count, opts)
            except SearchError as e:
                if not getattr(e, "retryable", False):
                    raise
                last_err = e
                attempt_errors.append(e)
            except httpx.HTTPError as e:
                last_err = SearchError(f"{type(e).__name__}: {e}")
                last_err.retryable = True  # type: ignore[attr-defined]
                attempt_errors.append(last_err)
            attempt += 1
            if attempt <= 2:
                delay = retry_delay_ms(last_err, attempt - 1) / 1000.0
                log.warning("搜索 %s 失败（%.1fs 后重试）: %s", self.name, delay, last_err)
                time.sleep(delay)
        reason = (REASON_MAX_RETRIES_EXCEEDED if getattr(last_err, "retryable", False)
                  else REASON_ERROR_NOT_RETRYABLE)
        raise SearchRetryExhausted(
            f"{self.name} 搜索失败（重试耗尽）: {last_err}",
            reason=reason, errors=attempt_errors,
        )


class HTTPSearchProvider(SearchProvider):
    """带鉴权头的 HTTP 搜索 provider 公共部分。

    出网经传输脊 post_json（非 2xx 全入错、客户端池复用、UA 策略随站点
    配置）；传输脊 typed 错误转译为 SearchError（retryable/retry_after
    结构化字段随转译保留）。"""

    def __init__(self, *, timeout: float = 30.0, db=None) -> None:
        self._timeout = timeout
        self._db = db  # 出网 UA 策略读取面（可为 None=honest 无邮箱形态）

    def _post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        try:
            resp = post_json(url, payload, headers=headers,
                             timeout=self._timeout, db=self._db)
        except ProviderError as e:
            raise self._translate(e) from e
        try:
            return resp.json()
        except json.JSONDecodeError as e:
            raise SearchError(f"响应非 JSON: {e}") from e

    @staticmethod
    def _translate(e: ProviderError) -> SearchError:
        """传输脊 typed 错误 → SearchError（消息沿用传输脊格式，retryable/
        retry_after 结构化字段转发——本域错误类型保持独立，分类学收敛属后续批）。"""
        se = SearchError(str(e))
        se.retryable = getattr(e, "retryable", False)  # type: ignore[attr-defined]
        ra = getattr(e, "retry_after", None)
        if ra is not None:
            se.retry_after = ra  # type: ignore[attr-defined]
        return se


__all__ = ["SearchProvider", "SearchResult", "SearchError", "SearchRetryExhausted",
           "HTTPSearchProvider", "_parse_dt"]
