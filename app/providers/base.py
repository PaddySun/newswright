"""LLM provider 抽象 + 计量/重试/usage_log 包装。

纪律（选型草稿 §3.2.3）：
- 所有 LLM 调用统一经此层，每次调用落一条 usage_log（调用点/模型/token/延迟/成败/归属）。
- 网络失败重试最多 2 次（退避经传输脊协商：Retry-After 优先、随机化指数退避），
  耗尽抛 RetryExhausted（继承 ProviderError）由上层进 FAILED 终态。
- 日志与报错绝不携带 Key。

传输横切面（错误分类学/_scrub/计量/HTTP 出口/重试协商）已上提至 app/transport/
（传输脊中立化批）；本模块保留 LLM 域语义（_call 模板方法、strict JSON 解析、
OpenAI usage 计量映射），并 re-export 兼容名（既有 import 面零改动）。
设计依据见 docs/design-index.md「TR-1」「TR-3」「TR-4」「TR-5」「ADR-8」。
"""
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx
from sqlalchemy.orm import Session

from ..transport.errors import (
    REASON_ERROR_NOT_RETRYABLE,
    REASON_MAX_RETRIES_EXCEEDED,
    ProviderError,
    RetryExhausted,
)
from ..transport.http import (
    RETRYABLE_STATUS,
    FATAL_STATUS_MESSAGE,
    _scrub,
    post_json,
    retry_delay_ms,
)
from ..transport.metering import record_usage

__all__ = [
    "FATAL_STATUS_MESSAGE",
    "HTTPProvider",
    "JSONParseError",
    "LLMProvider",
    "ProviderError",
    "RETRYABLE_STATUS",
    "RetryExhausted",
    "_scrub",
    "parse_strict_json",
    "record_usage",
]

log = logging.getLogger("newswright.providers")

# finish_reason 官方语义：length=截断（max_tokens/上下文）、content_filter=被过滤
# （不可重试）、insufficient_system_resource/aborted=服务端中断（可重试）、stop/tool_calls 正常
RETRYABLE_FINISH_REASONS = {"insufficient_system_resource", "aborted"}
FATAL_FINISH_REASONS = {"content_filter"}


class JSONParseError(Exception):
    """LLM 返回内容无法解析为合法 JSON / 字段缺失。"""


def _error_is_retryable(e: BaseException) -> bool:
    """传输脊 typed 错误按结构化字段判定；httpx 网络异常一律可重试；
    朴素异常按类属性兜底（兼容既有鸭子属性形态）。"""
    if isinstance(e, httpx.HTTPError):
        return True
    return bool(getattr(e, "retryable", False))


class LLMProvider(ABC):
    """同步 provider。子类实现 _post；基类负责重试与计量。"""

    name: str = "base"

    def __init__(self, db: Session) -> None:
        self.db = db

    @abstractmethod
    def _post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """发一次请求，返回 (响应体, 计量信息)。计量信息含
        prompt_tokens / completion_tokens / billing_units，可选
        cache_hit_tokens / reasoning_tokens / finish_reason / item_count。
        抛 httpx/ProviderError。"""

    def tier_request(self, payload: dict[str, Any], *, model_tier: str | None) -> dict[str, Any]:
        """按调用档位改写请求 payload 的 provider 钩子（默认不改写——纯模型名档位，
        任何 OpenAI 兼容 provider 零改动兼容；DeepSeek 覆盖为官方 thinking 参数）。"""
        return payload

    def _call(
        self,
        payload: dict[str, Any],
        *,
        call_point: str,
        ref_type: str | None = None,
        ref_id: int | None = None,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """重试 + 计量包装，返回完整响应体。失败退避经传输脊协商（Retry-After
        优先夹逼 / 随机化指数退避），耗尽抛 RetryExhausted（reason 两态+尝试链）。"""
        attempt = 0
        last_err: Exception | None = None
        attempt_errors: list[Exception] = []
        while attempt <= max_retries:
            t0 = time.monotonic()
            try:
                body, meter = self._post(payload)
                latency_ms = int((time.monotonic() - t0) * 1000)
                record_usage(
                    self.db,
                    provider=self.name,
                    model=payload.get("model", ""),
                    call_point=call_point,
                    prompt_tokens=meter.get("prompt_tokens", 0),
                    completion_tokens=meter.get("completion_tokens", 0),
                    billing_units=meter.get("billing_units", 0),
                    cache_hit_tokens=meter.get("cache_hit_tokens", 0),
                    reasoning_tokens=meter.get("reasoning_tokens", 0),
                    finish_reason=meter.get("finish_reason"),
                    item_count=meter.get("item_count"),
                    latency_ms=latency_ms,
                    ok=True,
                    ref_type=ref_type,
                    ref_id=ref_id,
                )
                return body
            except JSONParseError:
                # 解析失败不是网络问题，不在此层重试（任务书：解析失败由业务层重试一次）
                raise
            except (httpx.HTTPError, ProviderError) as e:
                latency_ms = int((time.monotonic() - t0) * 1000)
                last_err = e
                attempt_errors.append(e)
                retryable = _error_is_retryable(e)
                record_usage(
                    self.db,
                    provider=self.name,
                    model=payload.get("model", ""),
                    call_point=call_point,
                    latency_ms=latency_ms,
                    ok=False,
                    error=f"{type(e).__name__}: {e}",
                    ref_type=ref_type,
                    ref_id=ref_id,
                )
                if not retryable or attempt == max_retries:
                    break
                delay = retry_delay_ms(e, attempt) / 1000.0
                log.warning("provider 调用失败（第 %d 次，%.1fs 后重试）: %s", attempt + 1, delay, e)
                time.sleep(delay)
                attempt += 1
        reason = (REASON_MAX_RETRIES_EXCEEDED if _error_is_retryable(last_err)
                  else REASON_ERROR_NOT_RETRYABLE)
        raise RetryExhausted(
            f"{self.name} 调用失败（重试 {attempt} 次后放弃）: {last_err}",
            reason=reason, errors=attempt_errors,
        )


class HTTPProvider(LLMProvider):
    """带 base_url/api_key 的 HTTP provider 公共部分。

    HTTP 出网经传输脊 post_json（非 2xx 全入错、3xx 可重试带 location、
    客户端进程级复用）；本层只保留 LLM 域鉴权头与响应契约
    （返回原始 httpx.Response，调用方自行 .json()）。"""

    def __init__(self, db: Session, *, base_url: str, api_key: str, timeout: float = 120.0) -> None:
        super().__init__(db)
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._timeout = timeout

    def _post_json(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        return post_json(
            f"{self.base_url}{path}", payload,
            headers=self._headers, timeout=self._timeout, db=self.db,
        )

    @staticmethod
    def _meter_from_openai_usage(usage: dict[str, Any] | None) -> dict[str, int]:
        usage = usage or {}
        return {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "billing_units": 0,
            # 官方 usage 细节（缓存命中 / 思维链 token；其他 provider 缺省为 0）
            "cache_hit_tokens": int(usage.get("prompt_cache_hit_tokens")
                                    or (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
            "reasoning_tokens": int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
        }

    @staticmethod
    def _finish_reason(body: dict[str, Any]) -> str | None:
        try:
            return body["choices"][0].get("finish_reason")
        except (KeyError, IndexError, TypeError):
            return None


def parse_strict_json(text: str) -> dict[str, Any]:
    """从模型返回文本中解析 JSON 对象；失败抛 JSONParseError。

    兼容 ```json 围栏与前后杂文（截取第一个 { 到最后一个 }）。
    """
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        raise JSONParseError(f"响应中未找到 JSON 对象: {t[:200]!r}")
    try:
        data = json.loads(t[start : end + 1])
    except json.JSONDecodeError as e:
        raise JSONParseError(f"JSON 解析失败: {e}: {t[:200]!r}") from e
    if not isinstance(data, dict):
        raise JSONParseError("JSON 顶层不是对象")
    return data
