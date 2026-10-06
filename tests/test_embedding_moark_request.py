"""moark 向量生成适配器请求契约：真实 httpx 请求路径（MockTransport 捕获）。

现有 M18 测试对 _embed_request 全部打桩替身（FakeEmbedProvider 直覆方法），
真实请求构造/响应解析路径零覆盖——本文件走真实现补协议契约断言：
- 请求体协议字段（model/input/encoding_format="float"/dimensions 透传与省略）；
- OpenAI 兼容请求头（Authorization: Bearer <key> 与 Content-Type: application/json
  键名与值形态即条款）；
- 显式超时（技术书 §4.2：任意有限值）；
- 429/5xx 标记 retryable 并以 EmbeddingError 终态（ADR-8 重试纪律）；
- 响应 data[].embedding 按 index 还原输入顺序（协议允许乱序返回）、空/非法向量
  拒绝（EV1 静默拆批防护）、usage.prompt_tokens 计量经 base 层落 usage_log
  （AC-08.1/ADR-3；item_count 由 base 层 len(inputs) 承载）。
设计依据见 docs/design-index.md「ADR-3」「ADR-8」「AC-08.1」。
"""
import json
import math

import httpx
import pytest

import app.embedding.base as embed_base
from app.embedding.base import EmbeddingError
from app.embedding.moark import MoarkEmbeddingProvider
from app.models import UsageLog


class _Captured:
    def __init__(self):
        self.client_kwargs: dict | None = None
        self.request: httpx.Request | None = None


_REAL_CLIENT = httpx.Client  # 模块导入时绑定：二次 patch 时不叠桩


def _patch_client(monkeypatch, handler, captured: _Captured):
    """把适配器内的 httpx.Client 换成走 MockTransport 的真 Client，并捕获
    构造 kwargs（timeout 面）与最终请求（body/headers 面）。"""
    def wrapped(request):
        captured.request = request
        return handler(request)

    def factory(**kwargs):
        captured.client_kwargs = dict(kwargs)
        return _REAL_CLIENT(transport=httpx.MockTransport(wrapped), **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)


def _make_provider(db_session) -> MoarkEmbeddingProvider:
    return MoarkEmbeddingProvider(
        db_session, base_url="https://embed.test", api_key="sk-test-key",
        model="test-embed-model",
    )


def _ok_response_body() -> dict:
    return {
        "data": [
            {"index": 1, "embedding": [0.2, 0.2]},
            {"index": 0, "embedding": [0.1, 0.1]},
        ],
        "usage": {"prompt_tokens": 42},
    }


def test_request_payload_protocol_fields(db_session, monkeypatch):
    """请求体按协议字段名与钉值构造：model/input/encoding_format="float"，
    dimensions 非 None 时透传。"""
    captured = _Captured()
    _patch_client(
        monkeypatch,
        lambda request: httpx.Response(200, json=_ok_response_body()),
        captured,
    )
    p = _make_provider(db_session)
    p._embed_request(["a", "b"], dimensions=8)
    body = json.loads(captured.request.read())
    assert body["model"] == "test-embed-model"
    assert body["input"] == ["a", "b"]
    assert body["encoding_format"] == "float"
    assert body["dimensions"] == 8
    assert captured.request.url == "https://embed.test/v1/embeddings"


def test_dimensions_omitted_when_none(db_session, monkeypatch):
    """dimensions=None 时不携带该键（留空用模型默认维度）。"""
    captured = _Captured()
    _patch_client(
        monkeypatch,
        lambda request: httpx.Response(200, json=_ok_response_body()),
        captured,
    )
    p = _make_provider(db_session)
    p._embed_request(["a"], None)
    body = json.loads(captured.request.read())
    assert "dimensions" not in body


def test_request_headers_bearer_and_content_type(db_session, monkeypatch):
    """OpenAI 兼容请求头两枚：Authorization: Bearer <key> 与
    Content-Type: application/json（键名与值形态即条款）。"""
    captured = _Captured()
    _patch_client(
        monkeypatch,
        lambda request: httpx.Response(200, json=_ok_response_body()),
        captured,
    )
    p = _make_provider(db_session)
    p._embed_request(["a"], None)
    headers = captured.request.headers
    assert headers.get("Authorization") == "Bearer sk-test-key"
    assert headers.get("Content-Type") == "application/json"


def test_client_timeout_explicit_finite(db_session, monkeypatch):
    """httpx.Client 以显式有限超时构造（§4.2：None 即无限等待失守）。"""
    captured = _Captured()
    _patch_client(
        monkeypatch,
        lambda request: httpx.Response(200, json=_ok_response_body()),
        captured,
    )
    p = _make_provider(db_session)
    p._embed_request(["a"], None)
    t = captured.client_kwargs["timeout"]
    assert isinstance(t, (int, float)) and t > 0 and math.isfinite(t)


def test_valid_response_returns_aligned_vectors(db_session, monkeypatch):
    """乱序响应按 index 还原输入顺序（协议允许乱序返回）；向量逐条抽取、
    非法/空向量拒绝、畸形 data 以 EmbeddingError 终态而非裸崩溃。"""
    captured = _Captured()
    _patch_client(
        monkeypatch,
        lambda request: httpx.Response(200, json=_ok_response_body()),
        captured,
    )
    p = _make_provider(db_session)
    vectors, meter = p._embed_request(["a", "b"], None)
    assert vectors == [[0.1, 0.1], [0.2, 0.2]]
    assert meter["prompt_tokens"] == 42

    # 畸形 data（非数组）与非法/空向量：EmbeddingError 终态（错误契约）
    for bad_body in (
        {"data": "oops", "usage": {}},
        {"data": [{"index": 0, "embedding": None}], "usage": {}},
        {"data": [{"index": 0, "embedding": []}], "usage": {}},
    ):
        _patch_client(
            monkeypatch,
            lambda request, b=bad_body: httpx.Response(200, json=b),
            captured,
        )
        with pytest.raises(EmbeddingError):
            p._embed_request(["a"], None)


def test_usage_metered_to_usage_log(db_session, monkeypatch):
    """usage.prompt_tokens 计量经 base 层落 usage_log（成功行）；item_count 由
    base 层按批条数承载。"""
    captured = _Captured()
    _patch_client(
        monkeypatch,
        lambda request: httpx.Response(200, json=_ok_response_body()),
        captured,
    )
    p = _make_provider(db_session)
    vecs = p.embed(["a", "b"], batch_size=32)
    assert len(vecs) == 2
    rows = db_session.query(UsageLog).filter_by(provider="moark_embed").all()
    assert len(rows) == 1
    assert rows[0].prompt_tokens == 42
    assert rows[0].item_count == 2
    assert rows[0].call_point == "embed"


def test_retryable_status_marks_retryable_and_raises_embedding_error(
        db_session, monkeypatch):
    """429 响应抛 EmbeddingError 且 retryable=True；经 base 层重试后成功
    （ADR-8：429/5xx 可重试，指数退避）。"""
    captured = _Captured()
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] <= 2:  # 直接调用一次 + embed 首发各造一次 429
            return httpx.Response(429, text="too many requests")
        return httpx.Response(200, json=_ok_response_body())

    _patch_client(monkeypatch, handler, captured)
    p = _make_provider(db_session)

    with pytest.raises(EmbeddingError) as ei:
        p._embed_request(["a"], None)
    assert getattr(ei.value, "retryable", False) is True

    monkeypatch.setattr(embed_base.time, "sleep", lambda s: None)
    vecs = p.embed(["a", "b"])
    assert len(vecs) == 2
    rows = db_session.query(UsageLog).filter_by(provider="moark_embed").all()
    assert sorted(r.ok for r in rows) == [False, True]
