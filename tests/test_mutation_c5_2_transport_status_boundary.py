"""传输脊非 2xx 分账边界契约（transport.http）：TR-2 状态域边界的补面。

背景（外部服务治理批后的传输脊条款）：非 2xx 全入错——3xx 全域（含下边界
300）=可重试 TransportError 且携带服务端 Retry-After 解析值；只有 2xx 区间
[200, 300) 可作为成功响应返回。既有测试已覆盖 302/304/429/5xx/4xx 主干，
本文件补齐三面：①3xx 下边界 300（分域判定含 300 本身）；②成功区间上边界
（300/301 不得作为 2xx 放行——POST 与 GET 两面同规）；③3xx 分支同样挂载
Retry-After 解析值（退避协商的服务端值优先前提是错误对象先携带它）。
设计依据见 docs/design-index.md「TR-2」「TR-4」。
"""
import httpx
import pytest

from app.transport import http as transport_http
from app.transport.errors import SemanticError, TransportError

_AUTH = {"Authorization": "Bearer k-test", "Content-Type": "application/json"}
_URL = "https://api.example.com/v1/chat/completions"


def _factory_with(handler, constructions: list):
    def factory(**kwargs):
        constructions.append(1)
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    return factory


def test_non_2xx_classifier_covers_redirect_lower_boundary_300():
    """分类单点：300（3xx 下边界）按可重试 TransportError 入错——
    分域判定含 300 本身（300 ≤ status < 400），不得落入致命 4xx 语义域。"""
    resp = httpx.Response(300, headers={"location": "https://alt.example/x"})
    err = transport_http._non_2xx_error(resp)
    assert isinstance(err, TransportError)
    assert err.retryable is True
    assert err.status == 300
    assert err.location == "https://alt.example/x"


def test_post_json_300_is_error_not_success():
    """POST 面成功判定区间 [200, 300)：300 不作为成功响应放行
    （网关 300 类响应按可重试传输错误入错，杜绝「成功空响应」形态）。"""

    def handler(request):
        return httpx.Response(300, headers={"location": "https://alt.example/x"})

    with pytest.raises(TransportError):
        transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0,
                                 client_factory=_factory_with(handler, []))


def test_post_json_301_is_error_not_success():
    """POST 面 301 同规：非 2xx 全入错（成功区间不含 301）。"""

    def handler(request):
        return httpx.Response(301, headers={"location": "https://alt.example/x"})

    with pytest.raises(TransportError):
        transport_http.post_json(_URL, {}, headers=_AUTH, timeout=5.0,
                                 client_factory=_factory_with(handler, []))


def test_get_json_300_is_error_not_success():
    """GET 面成功判定区间 [200, 300)：300 不放行（与 POST 面同规，
    「非 2xx 入错」以重定向终态为准——终态 300 即入错）。"""

    def handler(request):
        return httpx.Response(300, headers={"location": "https://alt.example/x"})

    with pytest.raises(TransportError):
        transport_http.get_json(_URL, timeout=5.0,
                                client_factory=_factory_with(handler, []))


def test_get_json_301_is_error_not_success():
    """GET 面 301 同规：非 2xx 全入错。"""

    def handler(request):
        return httpx.Response(301, headers={"location": "https://alt.example/x"})

    with pytest.raises(TransportError):
        transport_http.get_json(_URL, timeout=5.0,
                                client_factory=_factory_with(handler, []))


def test_non_2xx_redirect_branch_mounts_retry_after_value():
    """3xx 分支同样挂载 Retry-After 解析值：服务端在重定向响应上给出的
    退避指示不丢失（退避协商「服务端值优先」以错误对象携带该值为前提）。"""
    resp = httpx.Response(
        302,
        headers={"location": "https://mkt.example/promo", "retry-after": "10"},
        text="moved",
    )
    err = transport_http._non_2xx_error(resp)
    assert isinstance(err, TransportError)
    assert err.retry_after == 10.0
