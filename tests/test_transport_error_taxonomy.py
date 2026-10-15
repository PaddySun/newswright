"""传输层错误分类学测试（transport spine errors）：四分类 + 兼容根 + 结构化耗尽。

背景（外部服务治理批）：全部外部服务出网收敛 app/transport/ 后，错误分类学
在传输层统一定义——传输/语义/契约/解析四类 + 框架自错 + 结构化重试耗尽；
ProviderError 作为兼容根保留（全库既有 except ProviderError 兼容是硬约束）。
设计依据见 docs/design-index.md「TR-1」「TR-5」。
"""
import pytest

from app.transport.errors import (
    REASON_ERROR_NOT_RETRYABLE,
    REASON_MAX_RETRIES_EXCEEDED,
    ContractError,
    FrameworkError,
    ParseError,
    ProviderError,
    RetryExhausted,
    SemanticError,
    TransportError,
)


def test_provider_error_is_legacy_compatibility_root():
    """ProviderError 是全部分类的兼容根：任何传输层错误都被既有
    `except ProviderError` 捕获（消费方零改动的硬约束）。"""
    e = TransportError("net down")
    assert isinstance(e, ProviderError)
    assert isinstance(SemanticError("bad request", status=400), ProviderError)
    assert isinstance(ContractError("schema drift"), ProviderError)
    assert isinstance(ParseError("not json"), ProviderError)
    assert isinstance(FrameworkError("config missing"), ProviderError)
    assert isinstance(
        RetryExhausted("gave up", reason=REASON_MAX_RETRIES_EXCEEDED, errors=[]),
        ProviderError,
    )


def test_transport_error_default_retryable_and_structured_fields():
    """TransportError 缺省可重试，携带 status/location/retry_after 结构化字段
    （retryable 从鸭子属性 hack 升级为构造参数）。"""
    e = TransportError("HTTP 302: moved", status=302, location="https://mkt.example",
                       retry_after=12.0)
    assert e.retryable is True
    assert e.status == 302
    assert e.location == "https://mkt.example"
    assert e.retry_after == 12.0


def test_transport_error_can_be_non_retryable():
    """TransportError 的 retryable 是逐实例判定（构造参数），不是类级常量。"""
    e = TransportError("connection refused", retryable=False)
    assert e.retryable is False


def test_semantic_error_not_retryable_with_status():
    """SemanticError（服务端理解请求但拒绝的 4xx 致命域）：不重试、携带 status。"""
    e = SemanticError("请求体格式错误（400）: boom", status=400)
    assert e.retryable is False
    assert e.status == 400


def test_retry_exhausted_two_reason_states_and_error_chain():
    """RetryExhausted 结构化耗尽：reason 两态（重试上限耗尽 / 错误不可重试）+
    逐次尝试异常链保留（耗尽可归因）。"""
    attempts = [TransportError("HTTP 503: a", status=503),
                TransportError("HTTP 503: b", status=503)]
    e = RetryExhausted("调用失败（重试 2 次后放弃）: b",
                       reason=REASON_MAX_RETRIES_EXCEEDED, errors=attempts)
    assert e.reason == "max_retries_exceeded"
    assert list(e.errors) == attempts
    assert isinstance(e.errors[-1], TransportError)

    fatal = RetryExhausted("调用失败: x", reason=REASON_ERROR_NOT_RETRYABLE,
                           errors=[SemanticError("HTTP 402: 余额不足", status=402)])
    assert fatal.reason == "error_not_retryable"
    assert len(fatal.errors) == 1


def test_retry_exhausted_caught_by_legacy_provider_error_except():
    """耗尽异常必须落进既有 `except ProviderError` 兼容面（消费方不感知新类型）。"""
    e = RetryExhausted("exhausted", reason=REASON_MAX_RETRIES_EXCEEDED, errors=[])
    with pytest.raises(ProviderError):
        raise e


def test_domain_retry_exhausted_classes_keep_domain_typing():
    """域耗尽组合类双类型保持：embedding/search 域的耗尽异常同时是各自域错误
    （既有 except EmbeddingError / except SearchError 兼容）与 RetryExhausted
    （结构化 reason/errors），且仍是 ProviderError 兼容根的实例。"""
    from app.embedding.base import EmbeddingError, EmbeddingRetryExhausted
    from app.search.base import SearchError, SearchRetryExhausted

    ee = EmbeddingRetryExhausted(
        "moark_embed embedding 失败（重试 2 次后放弃）: x",
        reason=REASON_MAX_RETRIES_EXCEEDED, errors=[TransportError("HTTP 500")])
    assert isinstance(ee, EmbeddingError)
    assert isinstance(ee, RetryExhausted)
    assert isinstance(ee, ProviderError)
    assert ee.reason == REASON_MAX_RETRIES_EXCEEDED

    se = SearchRetryExhausted(
        "bocha 搜索失败（重试耗尽）: y",
        reason=REASON_MAX_RETRIES_EXCEEDED, errors=[TransportError("HTTP 429")])
    assert isinstance(se, SearchError)
    assert isinstance(se, RetryExhausted)
    assert isinstance(se, ProviderError)
