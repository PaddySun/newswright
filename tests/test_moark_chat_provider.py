"""moark chat 提供方（OpenAI 兼容族）：请求形态与计量契约。

覆盖：chat 路径带 /v1 前缀（厂商路径差异）且 payload 携带 model /
经 resolve("moark") 选源可达并完成 chat 与 chat_json 双任务 /
计量 model 以响应回显实况落账（usage_log.model 非空） /
json_mode 兼容阀（response_format 被拒→剥离重发一次） /
基类 tier 钩子对 moark 零改写。全部经 Fake 传输层，零出网。
设计依据见 docs/design-index.md「LR-5」「LR-6」。
"""
import pytest

import app.config as cfg
from app.models import UsageLog
from app.providers.resolve import resolve
from app.transport.errors import SemanticError


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def _chat_body(content="pong", model="deepseek-v4-1-flash-260910"):
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "model": model, "usage": {"prompt_tokens": 7, "completion_tokens": 3}}


@pytest.fixture()
def moark(db_session, monkeypatch):
    """经选源层取 moark 实例并注入 Fake 传输层（记录请求形态）。"""
    p = resolve("moark", db_session)
    recorded: list[tuple[str, dict]] = []

    def fake_post_json(path, payload):
        recorded.append((path, payload))
        return _FakeResp(_chat_body())

    monkeypatch.setattr(p, "_post_json", fake_post_json)
    p.recorded = recorded
    return p


def test_chat_request_uses_v1_prefix_and_carries_model(moark):
    content, model = moark.chat([{"role": "user", "content": "ping"}], call_point="moark_probe")
    assert content == "pong"
    path, payload = moark.recorded[0]
    # 厂商路径差异：moark 属 OpenAI 网关族，chat 路径带 /v1 前缀
    assert path.endswith("/v1/chat/completions")
    assert payload["model"] == cfg.MOARK_CHAT_MODEL
    assert payload["model"] == "DeepSeek-V4-Flash"  # BE-8 实价证伪换名（D1 口述价 SKU）
    assert model == "deepseek-v4-1-flash-260910"  # 返回口径=服务端回显实况


def test_chat_json_roundtrip_via_resolve(moark, monkeypatch):
    """json_mode 全链路：response_format 进请求、strict 解析回 dict。"""
    def json_post(path, payload):
        moark.recorded.append((path, payload))
        return _FakeResp(_chat_body(content='{"ok": true, "n": 4}'))

    monkeypatch.setattr(moark, "_post_json", json_post)
    data, model = moark.chat_json(
        [{"role": "user", "content": "输出 {\"ok\": true, \"n\": 4}"}],
        call_point="moark_json",
    )
    assert data == {"ok": True, "n": 4}
    assert model == "deepseek-v4-1-flash-260910"
    path, payload = moark.recorded[-1]
    assert path.endswith("/v1/chat/completions")
    assert payload["response_format"] == {"type": "json_object"}  # json_mode 语义


def test_usage_log_model_echoes_server_response(db_session, monkeypatch):
    """计量 model 落账口径：以响应回显实况为准（回显与请求名不同也可归因真实模型）。"""
    p = resolve("moark", db_session)
    monkeypatch.setattr(p, "_post_json", lambda path, payload: _FakeResp(_chat_body()))
    p.chat([{"role": "user", "content": "x"}], call_point="moark_meter", ref_type="item", ref_id=9)
    row = db_session.query(UsageLog).filter_by(call_point="moark_meter").one()
    assert row.provider == "moark"
    assert row.model == "deepseek-v4-1-flash-260910"  # 非空且回显实况
    assert row.ok is True and row.prompt_tokens == 7 and row.ref_id == 9


def test_json_mode_compat_valve_strips_response_format(db_session, monkeypatch):
    """json_mode 兼容阀：网关拒 response_format（400）→ 剥离重发一次成功。"""
    p = resolve("moark", db_session)
    recorded: list[dict] = []

    def flaky_post_json(path, payload):
        recorded.append(dict(payload))
        if "response_format" in payload:
            raise SemanticError("HTTP 400: 'response_format' is not supported", status=400)
        return _FakeResp(_chat_body(content='{"ok": true}'))

    monkeypatch.setattr(p, "_post_json", flaky_post_json)
    data, _model = p.chat_json([{"role": "user", "content": "x"}], call_point="moark_valve")
    assert data == {"ok": True}
    assert "response_format" in recorded[0]
    assert "response_format" not in recorded[1]
    assert "剥离" in (p.fallback_note or "")


def test_plain_provider_error_without_status_does_not_trip_valve(db_session, monkeypatch):
    """状态码判定（非字符串嗅探）：无 status 的朴素 ProviderError 不触发兼容阀。"""
    from app.providers.base import ProviderError
    p = resolve("moark", db_session)

    def raising(path, payload):
        raise ProviderError("HTTP 400-ish 文案但无结构化状态码")

    monkeypatch.setattr(p, "_post_json", raising)
    with pytest.raises(ProviderError):
        p.chat([{"role": "user", "content": "x"}], call_point="moark_no_valve", max_retries=0)
    assert p.fallback_note is None


def test_tier_hook_noop_for_moark(moark):
    """基类 tier 钩子默认零改写：moark 不带 thinking 参数（纯模型名档位兼容）。"""
    payload = {"model": cfg.MOARK_CHAT_MODEL, "messages": []}
    assert moark.tier_request(payload, model_tier="reasoner") is payload
    moark.chat([{"role": "user", "content": "x"}], call_point="moark_tier")
    assert "thinking" not in moark.recorded[0][1]


def test_last_usage_observability(moark):
    moark.chat([{"role": "user", "content": "x"}], call_point="moark_obs")
    assert moark.last_usage["prompt_tokens"] == 7
    assert moark.last_usage["finish_reason"] == "stop"
