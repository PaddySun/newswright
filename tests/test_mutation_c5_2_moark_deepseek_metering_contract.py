"""厂商 provider 计量与配置契约（moark_jev / deepseek / moark_chat）：补面。

四面（C4 后 LLM 域厂商条款）：
- Jev 决策协议的 model 回显口径：服务端响应回显实况优先、请求名兜底
  （计量空洞治理——usage 落账以回显为准）；
- Jev usage 兜底不虚增：服务端未回显计量字段时按 0 兜底（账本不得虚增）；
- DeepSeek 模型绑定：显式 model 构造与 reasoner 档思考模型路由
  （tier_request 钩子的模型名半边）；
- moark chat 构造的配置转发：鉴权凭据来自 config 键（配置 + 钩子声明面）。
设计依据见 docs/design-index.md「LR-6」「LR-1」「LR-5」「ADR-8」。
"""
import pytest

import app.config as config
from app.providers.deepseek import DeepSeekProvider
from app.providers.moark_chat import MoarkChatProvider
from app.providers.moark_jev import MoarkJevProvider

_QUESTIONS = {
    "q1": {"type": "choice", "criteria": {"good": "好", "bad": "差"},
           "instructions": "按内容质量判断"},
}
_ANSWERS = {"q1": {"choice": "good", "confidence": 0.9,
                   "probabilities": {"good": 0.9, "bad": 0.1}}}


class _FakeDB:
    def add(self, obj):
        pass

    def commit(self):
        pass


def _jev_with_body(body, captured: list):
    """构造桩 provider：_post 捕获 payload 并返回固定响应体。"""
    provider = MoarkJevProvider(_FakeDB())  # type: ignore[arg-type]

    def _post(payload):
        captured.append(dict(payload))
        return body, {"prompt_tokens": 1, "completion_tokens": 1,
                      "billing_units": 0}

    provider._post = _post  # type: ignore[method-assign]
    return provider


def test_jev_decide_model_echoes_server_response():
    """model 回显实况优先：服务端 body["model"] 存在时返回回显值。"""
    captured: list = []
    provider = _jev_with_body(
        {"answers": _ANSWERS, "usage": {}, "model": "echo-9b"}, captured)
    result = provider.decide(state="s", questions=_QUESTIONS)
    assert result["model"] == "echo-9b"


def test_jev_decide_model_falls_back_to_request_name():
    """model 请求名兜底：服务端无回显时返回请求使用的模型名（不留空）。"""
    captured: list = []
    provider = _jev_with_body({"answers": _ANSWERS, "usage": {}}, captured)
    result = provider.decide(state="s", questions=_QUESTIONS)
    assert result["model"] == provider.default_model
    assert result["model"]  # 非空


def test_jev_decide_usage_defaults_zero_not_inflated():
    """usage 兜底不虚增：服务端无计量回显时 billing_units 兜 0（账本
    不得虚增——未计量列按 0 记）。"""
    captured: list = []
    provider = _jev_with_body({"answers": _ANSWERS, "usage": {}}, captured)
    result = provider.decide(state="s", questions=_QUESTIONS)
    assert result["usage"]["billing_units"] == 0


def test_deepseek_explicit_model_binds_as_default():
    """DeepSeek 显式 model 构造：实例缺省模型为该绑定值
    （variant 按模型出变体——模型绑定经构造透传）。"""
    probe = DeepSeekProvider(_FakeDB(), model="deepseek-v4-pro")  # type: ignore[arg-type]
    assert probe._default_model() == "deepseek-v4-pro"


def test_deepseek_reasoner_tier_uses_thinking_model(monkeypatch):
    """reasoner 档思考模型路由：tier_request 在 reasoner 档把模型切换为
    DEEPSEEK_THINKING_MODEL（思考档模型语义——模型键不得漂移）。"""
    monkeypatch.setattr(config, "DEEPSEEK_TIER_MODE", "thinking_params")
    probe = DeepSeekProvider(_FakeDB())  # type: ignore[arg-type]
    payload = probe.tier_request({"model": "chat-form"}, model_tier="reasoner")
    assert payload["model"] == config.DEEPSEEK_THINKING_MODEL
    assert payload["thinking"] == {"type": "enabled"}


def test_moark_chat_forwards_config_api_key(db_session):
    """moark chat 配置转发：鉴权头来自 config.MOARK_API_KEY
    （具体厂商退化为「配置 + 档位钩子」——配置键正确进鉴权头）。"""
    probe = MoarkChatProvider(db_session)
    assert probe._headers["Authorization"] == f"Bearer {config.MOARK_API_KEY}"
