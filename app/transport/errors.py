"""传输层错误分类学：四分类 + 框架自错 + 结构化重试耗尽 + 兼容根。

分类语义（自包含）：
- TransportError：传输类错误（网络中断/网关 5xx/限流 429/意外重定向 3xx）——
  是否可重试逐实例判定，携带 status / location / retry_after 结构化字段；
- SemanticError：服务端理解请求但拒绝（400/401/402/422 等致命 4xx）——不重试；
- ContractError：响应结构与服务协议不符（适配器与服务端契约漂移）；
- ParseError：响应内容解析失败（承载 strict→repair→retry 解析链的传输层锚点）；
- FrameworkError：本方/框架自身错误（构造缺参、配置缺失）——不触发跨源切换；
- RetryExhausted：重试终态结构化异常——reason 两态（重试上限耗尽/错误不可
  重试）+ 逐次尝试异常链（耗尽可归因）。

ProviderError 保留为兼容根（迁移前 providers.base.ProviderError 的原位）：
全库既有 `except ProviderError` 捕获面零改动是硬约束。
设计依据见 docs/design-index.md「TR-1」「TR-5」。
"""
from __future__ import annotations

REASON_MAX_RETRIES_EXCEEDED = "max_retries_exceeded"
REASON_ERROR_NOT_RETRYABLE = "error_not_retryable"


class ProviderError(Exception):
    """兼容根：外部服务调用失败的既有统一异常面（message 不得含 Key）。"""

    retryable = False


class TransportError(ProviderError):
    """传输类错误。retryable 逐实例判定；status/location/retry_after 为
    结构化字段（取代此前的 `e.retryable = True  # type: ignore` 鸭子属性 hack）。"""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        status: int | None = None,
        location: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        self.location = location
        self.retry_after = retry_after


class SemanticError(ProviderError):
    """语义类错误：服务端理解请求但拒绝（致命 4xx 域）——重试只会烧日志。"""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ContractError(ProviderError):
    """契约类错误：响应结构与服务协议不符（适配器或服务端契约漂移）。"""


class ParseError(ProviderError):
    """解析类错误：响应内容无法按预期格式解析。"""


class FrameworkError(ProviderError):
    """框架自错：本方构造/配置错误——与外部服务状态无关，不触发跨源切换。"""


class RetryExhausted(ProviderError):
    """重试终态结构化：reason ∈ {max_retries_exceeded, error_not_retryable}
    + errors=逐次尝试异常链。继承 ProviderError——既有 except 面零改动。"""

    def __init__(self, message: str, *, reason: str, errors: list[Exception]) -> None:
        super().__init__(message)
        self.reason = reason
        self.errors = list(errors)
