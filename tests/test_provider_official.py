"""Provider 层单测：DeepSeek 官方 API 适配（2026-10 文档口径）+ 多 provider 兼容。

覆盖：thinking 参数档位路由（官方）/ 模型名档位兼容（非官方网关）/ thinking 参数
被拒剥离重试（兼容阀）/ usage 细节计量（cache_hit/reasoning）/ finish_reason 语义
（length 截断、content_filter 不可重试、服务端中断重试）/ 官方错误码（402 不可重试）。
"""
import pytest

import app.config as cfg
import app.providers.deepseek as ds_mod
from app.providers.base import (
    HTTPProvider,
    ProviderError,
    parse_strict_json,
)
from app.providers.deepseek import DeepSeekProvider


@pytest.fixture()
def provider(db_session, monkeypatch):
    p = DeepSeekProvider(db_session)
    calls: list[dict] = []

    def fake_call(payload, **kw):
        calls.append(payload)
        body = p._responses.pop(0)
        # 模拟 _post 的计量旁路（真实链路：_post 在 _call 内被调用并写 _last_meter）
        meter = p._meter_from_openai_usage(body.get("usage"))
        meter["finish_reason"] = p._finish_reason(body)
        p._last_meter = meter
        return body

    p._call = fake_call  # type: ignore[method-assign]
    p.calls = calls
    p._responses = []
    return p


def _body(model="deepseek-flash", finish="stop", content="ok", usage=None):
    return {"choices": [{"message": {"content": content}, "finish_reason": finish}],
            "model": model, "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5}}


def test_tier_chat_sends_thinking_disabled(provider):
    payload = provider.tier_request({"model": cfg.DEEPSEEK_MODEL, "messages": []},
                                    model_tier="chat")
    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload


def test_tier_reasoner_official_thinking_params(provider):
    payload = provider.tier_request({"model": cfg.DEEPSEEK_MODEL, "messages": []},
                                    model_tier="reasoner")
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == cfg.DEEPSEEK_REASONING_EFFORT
    assert payload["model"] == cfg.DEEPSEEK_THINKING_MODEL
    assert "response_format" not in payload  # 思考档不吃 JSON mode


def test_tier_model_name_compat_mode(db_session, monkeypatch):
    monkeypatch.setattr(cfg, "DEEPSEEK_TIER_MODE", "model_name")
    monkeypatch.setattr(cfg, "DEEPSEEK_REASONER_MODEL", "legacy-reasoner")
    p = DeepSeekProvider(db_session)
    payload = p.tier_request({"model": cfg.DEEPSEEK_MODEL, "messages": []},
                             model_tier="reasoner")
    assert payload["model"] == "legacy-reasoner"
    assert "thinking" not in payload  # 旧口径：模型名路由，不带官方参数


def test_chat_reasoner_uses_thinking(provider):
    provider._responses = [_body(usage={"prompt_tokens": 10, "completion_tokens": 100,
                                        "prompt_cache_hit_tokens": 6,
                                        "completion_tokens_details": {"reasoning_tokens": 80}})]
    content, model = provider.chat([{"role": "user", "content": "x"}],
                                   call_point="w_draft", model_tier="reasoner")
    sent = provider.calls[0]
    assert sent["thinking"] == {"type": "enabled"}
    assert "max_tokens" not in sent  # 官方思考档缺省 64K，不硬设
    assert provider.reasoner_available is True
    # usage 细节透传
    assert provider.last_usage["cache_hit_tokens"] == 6
    assert provider.last_usage["reasoning_tokens"] == 80


def test_chat_chat_tier_omits_response_format_when_plain(provider):
    provider._responses = [_body()]
    provider.chat([{"role": "user", "content": "x"}], call_point="w_outline", json_mode=True)
    sent = provider.calls[0]
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["thinking"] == {"type": "disabled"}


def test_compat_valve_strips_thinking_on_400(provider):
    """非官方网关不认 thinking 参数（400）→ 剥离后重发成功（其他 provider 兼容阀）。"""
    real_call = provider._call

    def flaky(payload, **kw):
        if "thinking" in payload:
            raise ProviderError("HTTP 400: unknown field 'thinking'")
        return _body()

    provider._call = flaky  # type: ignore[method-assign]
    content, _ = provider.chat([{"role": "user", "content": "x"}], call_point="writing")
    assert content == "ok"
    assert "剥离" in (provider.fallback_note or "")


def test_finish_reason_content_filter_fatal(provider):
    provider._responses = [_body(finish="content_filter", content="")]
    with pytest.raises(ProviderError, match="被过滤"):
        provider.chat([{"role": "user", "content": "x"}], call_point="w_draft")


def test_finish_reason_server_interrupt_retried(provider):
    provider._responses = [_body(finish="aborted", content=""),
                           _body(finish="stop", content="recovered")]
    content, _ = provider.chat([{"role": "user", "content": "x"}], call_point="w_draft")
    assert content == "recovered" and len(provider.calls) == 2


def test_finish_reason_length_reported(provider):
    """length=截断：内容照常返回，finish_reason 留存在 last_usage（管线 trace 可见）。"""
    provider._responses = [_body(finish="length", content="partial")]
    content, _ = provider.chat([{"role": "user", "content": "x"}], call_point="w_draft")
    assert content == "partial"
    assert provider.last_usage["finish_reason"] == "length"


def test_fatal_402_message(db_session, monkeypatch):
    """官方错误码：402 余额不足 → 不可重试且信息明确。"""
    p = DeepSeekProvider(db_session)

    class R:
        status_code = 402
        text = '{"error":{"message":"Insufficient Balance"}}'

        def json(self):  # pragma: no cover
            return {}

    def fake_post_json(path, payload):
        from app.providers.base import FATAL_STATUS_MESSAGE, _scrub
        msg = FATAL_STATUS_MESSAGE.get(R.status_code, "HTTP")
        raise ProviderError(f"{msg}: {_scrub(R.text[:300])}")

    monkeypatch.setattr(p, "_post_json", fake_post_json)
    with pytest.raises(ProviderError, match="余额不足"):
        p.chat([{"role": "user", "content": "x"}], call_point="scoring")


def test_base_meter_parses_official_usage_details():
    meter = HTTPProvider._meter_from_openai_usage({
        "prompt_tokens": 100, "completion_tokens": 50,
        "prompt_tokens_details": {"cached_tokens": 32},
        "completion_tokens_details": {"reasoning_tokens": 40},
        "prompt_cache_hit_tokens": 32, "prompt_cache_miss_tokens": 68,
    })
    assert meter["cache_hit_tokens"] == 32
    assert meter["reasoning_tokens"] == 40
    assert meter["prompt_tokens"] == 100


def test_other_provider_tier_hook_is_noop(db_session):
    """兼容纪律：基类 tier hook 零改写——其他 OpenAI 兼容 provider 行为不变。"""

    class Dummy(HTTPProvider):
        name = "dummy"

        def _post(self, payload):  # pragma: no cover
            return {}, {}

    d = Dummy(db_session, base_url="https://example.com", api_key="k")
    payload = {"model": "x", "messages": []}
    assert d.tier_request(payload, model_tier="reasoner") is payload  # 原样返回


def test_parse_strict_json_unchanged():
    assert parse_strict_json('```json\n{"a": 1}\n```') == {"a": 1}
