"""HTTPProvider._post_json 与 DeepSeekProvider.chat_json 的请求/错误契约。

现有 provider 测试对 _post_json 全部打桩（mock 式测试下请求构造不可观察——
C1-1 D-1/D-2 拍板时已言明），本文件走真实 httpx 请求路径（MockTransport 捕获）：
- 请求体透传（协议请求体本体）；
- 429/5xx 抛 ProviderError 且 retryable=True（ADR-8：可重试状态码语义）；
- 400/401/402/422 官方错误码语义映射（给出明确信息——请求体格式错误/认证失败/
  余额不足），全部不可重试；
- chat_json 缺省开启 json_mode（response_format=json_object）且 messages 逐字透传
  （strict JSON 便捷封装契约）。
设计依据见 docs/design-index.md「ADR-8」「R5」。
"""
import json

import httpx
import pytest

from app.providers.base import HTTPProvider, ProviderError
from app.providers.deepseek import DeepSeekProvider

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


class DummyHTTP(HTTPProvider):
    name = "dummy"

    def _post(self, payload):
        return self._post_json("/endpoint", payload), {}


def test_post_json_forwards_request_body(db_session, monkeypatch):
    """请求体按调用方 payload 逐字透传（json= 参数）。"""
    captured = _Captured()
    _patch_client(
        monkeypatch, lambda r: httpx.Response(200, json={"ok": True}), captured)
    p = DummyHTTP(db_session, base_url="https://api.test", api_key="k")
    p._post_json("/endpoint", {"model": "m", "input": ["a"]})
    assert json.loads(captured.request.read()) == {"model": "m", "input": ["a"]}


def test_retryable_status_raises_retryable_provider_error(db_session, monkeypatch):
    """429 抛 ProviderError 且 retryable=True（不崩溃、不误吞）。"""
    captured = _Captured()
    _patch_client(
        monkeypatch, lambda r: httpx.Response(429, text="rate limited"), captured)
    p = DummyHTTP(db_session, base_url="https://api.test", api_key="k")
    with pytest.raises(ProviderError) as ei:
        p._post_json("/endpoint", {"m": 1})
    assert getattr(ei.value, "retryable", False) is True


def test_fatal_status_official_message(db_session, monkeypatch):
    """官方错误码语义映射：400 请求体格式错误 / 401 认证失败 / 402 余额不足，
    全部不可重试且消息携带官方语义提示。"""
    captured = _Captured()
    p = DummyHTTP(db_session, base_url="https://api.test", api_key="k")
    for status, marker in ((400, "请求体格式错误"), (401, "认证失败"),
                           (402, "余额不足")):
        _patch_client(
            monkeypatch,
            lambda r, s=status: httpx.Response(s, text="boom"),
            captured,
        )
        with pytest.raises(ProviderError) as ei:
            p._post_json("/endpoint", {"m": 1})
        assert getattr(ei.value, "retryable", False) is False
        assert marker in str(ei.value)
        assert str(status) in str(ei.value)


_CHAT_OK = {
    "choices": [{"message": {"content": "{\"ok\": true}"},
                 "finish_reason": "stop"}],
    "model": "deepseek-flash",
    "usage": {"prompt_tokens": 5, "completion_tokens": 3},
}


def test_chat_json_defaults_json_mode(db_session, monkeypatch):
    """chat_json 未显式传 json_mode 时缺省开启：请求含
    response_format={"type": "json_object"}（strict JSON 契约）。"""
    captured = _Captured()
    _patch_client(
        monkeypatch, lambda r: httpx.Response(200, json=_CHAT_OK), captured)
    p = DeepSeekProvider(db_session)
    data, model = p.chat_json(
        [{"role": "user", "content": "hi"}], call_point="test")
    assert data == {"ok": True} and model == "deepseek-flash"
    body = json.loads(captured.request.read())
    assert body["response_format"] == {"type": "json_object"}


def test_chat_json_forwards_messages(db_session, monkeypatch):
    """messages 逐字透传给 chat 调用（调用契约）。"""
    captured = _Captured()
    _patch_client(
        monkeypatch, lambda r: httpx.Response(200, json=_CHAT_OK), captured)
    p = DeepSeekProvider(db_session)
    messages = [{"role": "user", "content": "你好"}]
    p.chat_json(messages, call_point="test")
    body = json.loads(captured.request.read())
    assert body["messages"] == messages
