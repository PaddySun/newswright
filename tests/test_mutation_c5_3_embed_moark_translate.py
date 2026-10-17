"""moark 向量适配器转译契约（embedding.moark）：typed 错误转译保留 + 会话透传。

三面（能力域治理条款补面——向量适配器对传输脊 typed 错误的转译层）：
- 传输类错误转译为 EmbeddingError 时，retryable / retry_after 结构化字段
  随转译保留（429 的服务端 Retry-After 不得在转译边界丢失——退避协商输入面）；
- 语义类错误（无 retry_after 属性的 typed 错误）同样完整转译为域错误，
  不得因缺省值丢参在转译层抛 AttributeError 逃逸；
- 出网调用的 db 实参透传（db 是出网 UA 策略读取面——站点 UA 策略随
  调用方会话传递，不得退化为无会话形态）。
设计依据见 docs/design-index.md「TR-1」「TR-4」「TR-6」。
"""
import pytest

import app.embedding.moark as moark_embed
from app.embedding.base import EmbeddingError
from app.transport.errors import SemanticError, TransportError


class _StubResp:
    def __init__(self, body):
        self._body = body
        self.status_code = 200

    def json(self):
        return self._body


class _FakeDB:
    def add(self, obj):
        pass

    def commit(self):
        pass


def _provider():
    return moark_embed.MoarkEmbeddingProvider(
        _FakeDB(), base_url="https://api.test", api_key="k-test", model="m-test")


def test_transport_error_translates_with_retryable_and_retry_after(monkeypatch):
    """传输类错误转译保留协商字段：TransportError(429, Retry-After=30s)
    转译为 EmbeddingError 后 retryable=True 且 retry_after=30.0。"""
    def _raise(url, payload, **kwargs):
        raise TransportError("HTTP 429: slow down", status=429,
                             retry_after=30.0, retryable=True)

    monkeypatch.setattr(moark_embed, "post_json", _raise)
    with pytest.raises(EmbeddingError) as ei:
        _provider()._embed_request(["x"], None)
    assert ei.value.retryable is True
    assert ei.value.retry_after == 30.0


def test_semantic_error_translates_without_attribute_error(monkeypatch):
    """语义类错误（不携带 retry_after 属性的 typed 错误）完整转译为域错误：
    转译层对全部 typed 错误形态闭合，缺属性读取不得抛 AttributeError 逃逸。"""
    def _raise(url, payload, **kwargs):
        raise SemanticError("HTTP 402: 余额不足", status=402)

    monkeypatch.setattr(moark_embed, "post_json", _raise)
    with pytest.raises(EmbeddingError):
        _provider()._embed_request(["x"], None)


def test_post_json_receives_session_db_for_user_agent(db_session, monkeypatch):
    """出网 db 实参透传：适配器出网时把调用方会话传给传输脊（db=生效 UA
    策略读取面——站点 UA 策略随会话传递，出网不得退化为无会话形态）。"""
    captured: dict = {}

    def _capture(url, payload, **kwargs):
        captured.update(kwargs)
        return _StubResp({"data": [{"index": 0, "embedding": [0.1, 0.2]}],
                          "usage": {"prompt_tokens": 3}})

    monkeypatch.setattr(moark_embed, "post_json", _capture)
    provider = moark_embed.MoarkEmbeddingProvider(db_session)
    provider._embed_request(["x"], None)
    assert captured.get("db") is db_session
