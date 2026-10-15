"""LLM provider 注册表与启动校验契约。

覆盖：注册名三家族可达（deepseek/moark/moark_jev）/ 未注册名报错含可用名单 /
chat 域 none 哨兵非法（禁用语义仅嵌入域合法）/ 模型绑定变体工厂 /
启动期 provider 名解析校验（含 create_app 接线与嵌入域 none 豁免）。
设计依据见 docs/design-index.md「LR-1」「LR-4」。
"""
import pytest

import app.config as cfg
from app.models import UsageLog
from app.providers.base import LLMProvider
from app.providers.deepseek import DeepSeekProvider
from app.providers.moark_chat import MoarkChatProvider
from app.transport.errors import FrameworkError


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def _chat_body(content="pong", model="echoed-model"):
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "model": model, "usage": {"prompt_tokens": 3, "completion_tokens": 2}}


def test_available_contains_three_registered_families():
    from app.providers import registry
    names = set(registry.available())
    assert {"deepseek", "moark", "moark_jev"} <= names


def test_get_provider_deepseek_is_chat_capable(db_session):
    from app.providers import registry
    p = registry.get_provider("deepseek", db_session)
    assert isinstance(p, DeepSeekProvider)
    assert callable(p.chat) and callable(p.chat_json)
    assert p.name == "deepseek"


def test_get_provider_unknown_name_lists_available(db_session):
    from app.providers import registry
    with pytest.raises(FrameworkError) as ei:
        registry.get_provider("no-such-llm", db_session)
    assert "deepseek" in str(ei.value) and "moark" in str(ei.value)


def test_chat_domain_rejects_none_sentinel(db_session):
    """none 禁用哨兵仅对可禁用能力（嵌入域）合法；chat 域配置 none 即配置错误。"""
    from app.providers import registry
    with pytest.raises(FrameworkError, match="none"):
        registry.get_provider("none", db_session)


def test_variant_factory_binds_model(db_session, monkeypatch):
    from app.providers import registry
    factory = registry.variant("moark", model="GLM-5.3-Flash")
    bound = factory(db_session)
    assert isinstance(bound, MoarkChatProvider)
    recorded = []
    monkeypatch.setattr(bound, "_post_json",
                        lambda path, payload: (recorded.append((path, payload)), _FakeResp(_chat_body()))[1])
    bound.chat([{"role": "user", "content": "x"}], call_point="variant_probe")
    assert recorded[0][1]["model"] == "GLM-5.3-Flash"


def test_variant_default_model_uses_config(db_session):
    from app.providers import registry
    factory = registry.variant("moark")
    bound = factory(db_session)
    assert bound._default_model() == cfg.MOARK_CHAT_MODEL


# ---------- 启动校验（未注册名拒绝启动，报错含可用名单） ----------


def test_validate_accepts_default_config():
    from app.providers.resolve import validate_provider_config
    validate_provider_config()  # 默认配置（deepseek/moark 双注册）不抛


def test_validate_rejects_unknown_chat_provider(monkeypatch):
    from app.providers.resolve import validate_provider_config
    monkeypatch.setattr(cfg, "LLM_PROVIDER", "bogus-chat")
    with pytest.raises(FrameworkError) as ei:
        validate_provider_config()
    assert "bogus-chat" in str(ei.value) and "deepseek" in str(ei.value)


def test_validate_rejects_chat_none(monkeypatch):
    """chat 域不允许 none：选源层不为 chat 实现禁用路径（嵌入域独有语义）。"""
    from app.providers.resolve import validate_provider_config
    monkeypatch.setattr(cfg, "LLM_PROVIDER", "none")
    with pytest.raises(FrameworkError):
        validate_provider_config()


def test_validate_rejects_unknown_candidate(monkeypatch):
    from app.providers.resolve import validate_provider_config
    monkeypatch.setattr(cfg, "LLM_CANDIDATES", ["deepseek", "ghost"])
    with pytest.raises(FrameworkError, match="ghost"):
        validate_provider_config()


def test_validate_rejects_unknown_embed_provider(monkeypatch):
    from app.providers.resolve import validate_provider_config
    monkeypatch.setattr(cfg, "EMBED_PROVIDER", "bogus-embed")
    with pytest.raises(FrameworkError) as ei:
        validate_provider_config()
    assert "moark" in str(ei.value)


def test_validate_accepts_embed_none(monkeypatch):
    from app.providers.resolve import validate_provider_config
    monkeypatch.setattr(cfg, "EMBED_PROVIDER", "none")
    validate_provider_config()  # 嵌入域 none 合法（禁用回退全量慢速）


def test_create_app_refuses_unknown_provider_at_startup(db_session, monkeypatch):
    """启动接线：create_app 内执行 provider 名解析校验，未注册名拒绝启动。"""
    from app.main import create_app  # 先导入（模块级 create_app 校验默认配置通过）
    monkeypatch.setattr(cfg, "LLM_PROVIDER", "bogus-chat")
    with pytest.raises(FrameworkError, match="bogus-chat"):
        create_app()


def test_base_class_holds_observability_attrs(db_session):
    """观测面护栏：last_usage / fallback_note / reasoner_available 初始化在基类，
    全部 chat 家族实例开箱即得（authors 管线直读直写依赖此契约）。"""
    from app.providers.moark_jev import MoarkJevProvider
    for p in (DeepSeekProvider(db_session), MoarkChatProvider(db_session),
              MoarkJevProvider(db_session)):
        assert isinstance(p, LLMProvider)
        assert p.last_usage == {}
        assert p.fallback_note is None
        assert p.reasoner_available is None


def test_metering_model_falls_back_to_payload_when_no_echo(db_session, monkeypatch):
    """计量 model 口径：响应无回显时按请求 payload 落账（不虚增不落空）。"""
    p = DeepSeekProvider(db_session)
    body = _chat_body(content='{"ok": true}', model="")  # 服务端未回显 model
    monkeypatch.setattr(p, "_post_json", lambda path, payload: _FakeResp(body))
    p.chat_json([{"role": "user", "content": "x"}], call_point="meter_probe",
                model="deepseek-v4-pro")
    row = db_session.query(UsageLog).filter_by(call_point="meter_probe").one()
    assert row.model == "deepseek-v4-pro" and row.ok is True
