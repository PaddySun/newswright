"""rerank/search provider 构造装配契约：端点 URL、鉴权头与显式超时。

装配语义三条（构造的 provider 即可发出正确请求）：
- base_url 去尾斜杠后拼接端点路径（最终请求 URL 唯一，兼容配置尾斜杠有无）；
- OpenAI 兼容请求头 Authorization: Bearer <key>（moark 家族鉴权装配走 config 兜底）；
- httpx.Client 以显式有限超时构造（任意有限值满足；None 即无限等待失守）。
设计依据见 docs/design-index.md「ADR-8（D-A/D-B 补条款）」「§4.2」。
"""
import math

import httpx

import app.config as config
from app.rerank.base import HTTPRankProvider, RankCandidate
from app.rerank.moark_reranker import MoarkRerankerProvider
from app.search.bocha import BochaSearchProvider

_REAL_CLIENT = httpx.Client  # 模块导入时绑定：二次 patch 时不叠桩


class _Captured:
    def __init__(self):
        self.client_kwargs: dict | None = None
        self.request: httpx.Request | None = None


def _patch_client(monkeypatch, handler, captured: _Captured):
    def wrapped(request):
        captured.request = request
        return handler(request)

    def factory(**kwargs):
        captured.client_kwargs = dict(kwargs)
        return _REAL_CLIENT(transport=httpx.MockTransport(wrapped), **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)


_RANK_OK = {
    "results": [{"index": 0, "document": {"text": "t"},
                 "relevance_score": 0.9}],
    "usage": {"promptTokens": 10, "totalTokens": 20},
}


def test_construction_uses_config_endpoint_and_key(db_session, monkeypatch):
    """缺省构造走 config 装配：请求 URL=config 端点、Bearer=config key。"""
    captured = _Captured()
    _patch_client(
        monkeypatch, lambda r: httpx.Response(200, json=_RANK_OK), captured)
    p = MoarkRerankerProvider(db_session)
    out = p.rank("方向", [RankCandidate(id=1, text="候选")])
    assert len(out) == 1 and out[0].score == 90.0
    assert str(captured.request.url) == f"{config.MOARK_BASE_URL.rstrip('/')}/v1/rerank"
    assert captured.request.headers.get("Authorization") == \
        f"Bearer {config.MOARK_API_KEY}"


def test_trailing_slash_base_url_normalized(db_session, monkeypatch):
    """显式 base_url 带尾斜杠：拼接端点后 URL 唯一（无双斜杠）。"""
    captured = _Captured()
    _patch_client(
        monkeypatch, lambda r: httpx.Response(200, json=_RANK_OK), captured)
    p = MoarkRerankerProvider(db_session, base_url="https://rank.test/")
    p.rank("方向", [RankCandidate(id=1, text="候选")])
    assert str(captured.request.url) == "https://rank.test/v1/rerank"


def test_rank_client_timeout_finite(db_session, monkeypatch):
    """httpx.Client 以显式有限超时构造（§4.2）。"""
    captured = _Captured()
    _patch_client(
        monkeypatch, lambda r: httpx.Response(200, json=_RANK_OK), captured)
    p = MoarkRerankerProvider(db_session)
    p.rank("方向", [RankCandidate(id=1, text="候选")])
    t = captured.client_kwargs["timeout"]
    assert isinstance(t, (int, float)) and t > 0 and math.isfinite(t)


def test_rank_provider_base_url_trailing_slash_normalized(db_session):
    """HTTPRankProvider 装配：base_url 去尾斜杠（子类拼接域的装配前提）。"""
    d = HTTPRankProvider(db_session, base_url="https://y.test/", api_key="k", model="m")
    assert d._base_url == "https://y.test"


def test_search_client_timeout_finite(db_session, monkeypatch):
    """搜索 provider 的 httpx.Client 以显式有限超时构造（bocha 构造路径）。"""
    captured = _Captured()
    _patch_client(
        monkeypatch,
        lambda r: httpx.Response(200, json={"code": 200,
                                            "data": {"webPages": {"value": []}}}),
        captured,
    )
    p = BochaSearchProvider(api_key="k")
    assert p._search("查询", 5, {}) == []
    t = captured.client_kwargs["timeout"]
    assert isinstance(t, (int, float)) and t > 0 and math.isfinite(t)
