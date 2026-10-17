"""搜索底座 typed 错误转译契约（search.base）：协商字段随转译保留。

两面（能力域治理条款补面——HTTP 搜索 provider 公共部分的转译层）：
- 传输类错误转译为 SearchError 时 retryable / retry_after 结构化字段随
  转译保留（429 的服务端 Retry-After 不得在转译边界丢失——退避协商
  输入面，重试模板读它决定是否再试与等多久）；
- 语义类错误转译后 retryable=False（致命 4xx 域不重试的判定输入）。
设计依据见 docs/design-index.md「TR-1」「TR-4」。
"""
from app.search.base import HTTPSearchProvider, SearchError
from app.transport.errors import SemanticError, TransportError


def test_transport_error_translates_with_retryable_and_retry_after():
    """传输类错误转译保留协商字段：TransportError(429, Retry-After=30s)
    转译为 SearchError 后 retryable=True 且 retry_after=30.0。"""
    se = HTTPSearchProvider._translate(
        TransportError("HTTP 429: slow down", status=429,
                       retry_after=30.0, retryable=True))
    assert isinstance(se, SearchError)
    assert se.retryable is True
    assert se.retry_after == 30.0


def test_semantic_error_translates_as_not_retryable():
    """语义类错误转译：retryable=False（致命 4xx 域不重试的判定输入
    随转译保留——不得虚记为可重试）。"""
    se = HTTPSearchProvider._translate(
        SemanticError("HTTP 402: 余额不足", status=402))
    assert isinstance(se, SearchError)
    assert se.retryable is False
