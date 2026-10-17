"""传输脊随机化指数退避公式契约（transport.http.retry_delay_ms）：TR-3 补面。

背景：无服务端 Retry-After 时退避 = 2**attempt × uniform(0.5, 1.5) 秒——
基值 2 的幂 × 1000 毫秒、抖动因子区间 [0.5, 1.5]。既有测试以真实随机采样
断言区间形态（正确纪律——RNG 型测试断区间与分布、不依赖具体随机序列），
但区间边界的乘数被整体放大 0.1% 的变体在采样下大概率仍落原断言区间内。
本文件把抖动因子钉在区间端点（1.5）作确定性观测：attempt=0 的退避恰为
基值 1000ms × 1.5 = 1500ms——这是公式端点语义，非随机序列依赖。
设计依据见 docs/design-index.md「TR-3」。
"""
import pytest

from app.transport import http as transport_http
from app.transport.errors import ProviderError


def test_backoff_formula_upper_endpoint_at_jitter_ceiling(monkeypatch):
    """抖动因子钉上端点 1.5 时的确定性输出：attempt=0 退避恰为 1500ms
    （基值 2^0 × 1000ms × 1.5——公式端点保真，乘数不得整体漂移）。"""
    err = ProviderError("net down")
    monkeypatch.setattr(transport_http.random, "uniform", lambda a, b: b)
    assert transport_http.retry_delay_ms(err, 0) == 1500
