"""向量生成域重试终态契约（embedding.base）：耗尽归因两态 + 尝试链 + 退避协商。

四面（能力域治理条款补面——向量生成基类的重试模板方法）：
- 可重试错误耗尽抛 EmbeddingRetryExhausted 且 reason=max_retries_exceeded
  （结构化耗尽可归因：可重试错误的终态不得误记为不可重试）；
- 不可重试错误耗尽 reason=error_not_retryable（两态的另一态，不得虚记耗尽）；
- 耗尽异常携带逐次尝试 errors 链——每元素为该次尝试的真实异常实例
  （链元素 None 化即归因链断裂）；
- 重试间退避经传输脊协商：服务端 Retry-After 值优先采纳（429 类错误的
  sleep 时长=服务端值，不得退化为随机指数退避）。
设计依据见 docs/design-index.md「TR-3」「TR-4」「TR-5」。
"""
import httpx
import pytest

from app.embedding.base import (
    EmbeddingError,
    EmbeddingProvider,
    EmbeddingRetryExhausted,
)
from app.transport.errors import (
    REASON_ERROR_NOT_RETRYABLE,
    REASON_MAX_RETRIES_EXCEEDED,
)


class _FakeDB:
    """计量落账桩：收集 record_usage 的 add 对象。"""

    def __init__(self):
        self.rows: list = []

    def add(self, obj):
        self.rows.append(obj)

    def commit(self):
        pass


def _domain_error(msg: str, *, retryable: bool, retry_after: float | None = None):
    """构造带重试协商字段的域错误（生产形态：转译层鸭子挂载）。"""
    e = EmbeddingError(msg)
    e.retryable = retryable  # type: ignore[attr-defined]
    if retry_after is not None:
        e.retry_after = retry_after  # type: ignore[attr-defined]
    return e


def _provider_raising(exc_factory):
    class _Probe(EmbeddingProvider):
        name = "probe"

        @property
        def model_name(self) -> str:
            return "probe-model"

        def _embed_request(self, inputs, dimensions):
            raise exc_factory()

    return _Probe(_FakeDB())


def test_retryable_exhaustion_reason_is_max_retries(monkeypatch):
    """可重试错误耗尽：reason=max_retries_exceeded（域错误类型保持
    EmbeddingError 兼容根，同时携带结构化两态——可重试终态不得误记）。"""
    monkeypatch.setattr("app.embedding.base.time.sleep", lambda _s: None)
    provider = _provider_raising(lambda: _domain_error("boom", retryable=True))
    with pytest.raises(EmbeddingRetryExhausted) as ei:
        provider.embed(["x"])
    assert ei.value.reason == REASON_MAX_RETRIES_EXCEEDED
    assert isinstance(ei.value, EmbeddingError)


def test_non_retryable_exhaustion_reason_is_not_retryable(monkeypatch):
    """不可重试错误耗尽：reason=error_not_retryable——两态的另一态，
    不得虚记为重试上限耗尽。"""
    monkeypatch.setattr("app.embedding.base.time.sleep", lambda _s: None)
    provider = _provider_raising(lambda: _domain_error("fatal", retryable=False))
    with pytest.raises(EmbeddingRetryExhausted) as ei:
        provider.embed(["x"])
    assert ei.value.reason == REASON_ERROR_NOT_RETRYABLE


def test_httpx_network_error_exhaustion_reason_is_max_retries(monkeypatch):
    """httpx 原生网络错误（连接失败类）按可重试耗尽归因：网络传输错误
    恒走 max_retries_exceeded 态（判定含 httpx 异常域，不要求 retryable 属性）。"""
    monkeypatch.setattr("app.embedding.base.time.sleep", lambda _s: None)
    provider = _provider_raising(lambda: httpx.ConnectError("conn reset"))
    with pytest.raises(EmbeddingRetryExhausted) as ei:
        provider.embed(["x"])
    assert ei.value.reason == REASON_MAX_RETRIES_EXCEEDED


def test_exhaustion_errors_chain_lists_every_attempt(monkeypatch):
    """耗尽异常的 errors 链=逐次尝试的真实异常（首次+重试共 3 次）——
    链元素必须是异常实例，None 化即归因链断裂。"""
    monkeypatch.setattr("app.embedding.base.time.sleep", lambda _s: None)
    provider = _provider_raising(lambda: _domain_error("boom", retryable=True))
    with pytest.raises(EmbeddingRetryExhausted) as ei:
        provider.embed(["x"])
    assert len(ei.value.errors) == 3
    assert all(isinstance(e, Exception) for e in ei.value.errors)


def test_retry_backoff_sleeps_server_retry_after_seconds(monkeypatch):
    """退避协商：服务端 Retry-After 值优先——429 类可重试错误的重试间
    sleep 时长=服务端值（秒量级采纳，区分度=对随机指数退避的 [0.5,1.5]×2^n
    基线；协商输入丢失即退化为该基线）。"""
    sleeps: list[float] = []
    monkeypatch.setattr("app.embedding.base.time.sleep",
                        lambda s: sleeps.append(s))
    provider = _provider_raising(
        lambda: _domain_error("HTTP 429", retryable=True, retry_after=7.0))
    with pytest.raises(EmbeddingRetryExhausted):
        provider.embed(["x"])
    assert sleeps, "重试间必须有退避 sleep"
    assert sleeps[0] == pytest.approx(7.0, rel=0.02)
