"""BE-7/TR-2+PG：供应商级致命 4xx 分类、冷却接线与边沿通知。

覆盖（任务书 §五必含用例逐项）：
- 401/402/403 → VendorFatalError（供应商级致命）；400/422 仍 SemanticError
  （请求级致命）；429/5xx 只重试不冷却（偶发错误自动熔断无意义）；
- _error_is_retryable 继承面零变（VendorFatalError 不可重试）；
- _call 402 → 冷却标记且键=(name, None)：标记后 resolve_chat 跳过该候选落
  次位（键匹配回归——按 payload 模型名标记即键不匹配静默失效，防线钉死）；
- 边沿通知：首次进入冷却发一次 provider_switched；冷却期内第二次 402 不重发；
- config 三缺省钉面（moark / [moark, deepseek] / TTL 1800）；
- 单候选形态：标记在但 resolve 照常返回（A4 短路亲证）；
- 冷却期满自然回主源（无自动恢复探测，TTL 到期即回）。

时间纪律：TTL 断言区间；通知触发器打桩记录（触发器本体测试见
test_llm_error_rate_trigger.py）；resolve 进程态（实例缓存+冷却表）每用例复位。
出网零真发：base.post_json 打桩但经 _non_2xx_error 真分类——分类面即生产路径。
"""
import time

import httpx
import pytest

import app.config as cfg
from app.providers import base as providers_base
from app.providers.deepseek import DeepSeekProvider
from app.providers.resolve import cooldown_remaining, resolve_chat
from app.transport import http as transport_http
from app.transport.errors import (
    RetryExhausted,
    SemanticError,
    TransportError,
    VendorFatalError,
)


@pytest.fixture(autouse=True)
def clean_resolve():
    """选源层进程级状态（实例缓存+冷却表）的测试隔离位（BE-2 判例）。"""
    from app.providers import resolve as resolve_mod

    resolve_mod._reset_for_tests()
    yield resolve_mod
    resolve_mod._reset_for_tests()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """重试退避零等待（429 耗尽用例走两次 sleep）。"""
    monkeypatch.setattr(time, "sleep", lambda s: None)


def _raise_status(status: int, text: str = '{"error":{"message":"boom"}}'):
    """经生产分类单点 _non_2xx_error 构造指定状态的入错 post_json 桩。"""

    def _fake_post_json(url, payload, *, headers, timeout, db=None, client_factory=None):
        resp = httpx.Response(status, text=text)
        raise transport_http._non_2xx_error(resp)

    return _fake_post_json


# ---------- AC-1：TR-2 细分（分类面） ----------


@pytest.mark.parametrize("status", [401, 402, 403])
def test_vendor_fatal_status_classified(status):
    """供应商级致命 4xx（401 鉴权/402 余额/403 封禁）→ VendorFatalError，
    且仍属 SemanticError 子类（既有 except 面零改），status 字段保留。"""
    err = transport_http._non_2xx_error(
        httpx.Response(status, text="nope"))
    assert isinstance(err, VendorFatalError)
    assert isinstance(err, SemanticError)
    assert err.status == status


@pytest.mark.parametrize("status", [400, 422])
def test_request_level_4xx_still_semantic(status):
    """请求级致命（400 参数/422 校验）→ 照旧 SemanticError，不触发供应商
    冷却切换语义（重试与切换皆无益，维持快速失败）。"""
    err = transport_http._non_2xx_error(
        httpx.Response(status, text="nope"))
    assert type(err) is SemanticError
    assert not isinstance(err, VendorFatalError)
    assert err.status == status


def test_vendor_fatal_not_retryable_inheritance_unchanged():
    """_error_is_retryable 继承面零变：VendorFatalError 走 SemanticError 的
    不可重试语义；429/5xx 传输类照旧可重试。"""
    from app.providers.base import _error_is_retryable

    assert _error_is_retryable(VendorFatalError("HTTP 402", status=402)) is False
    assert _error_is_retryable(SemanticError("HTTP 400", status=400)) is False
    assert _error_is_retryable(
        TransportError("HTTP 429", retryable=True, status=429)) is True


# ---------- AC-3：候选链与 TTL 缺省钉面 ----------


def test_config_defaults_pinned():
    """D1 缺省钉面：LLM_PROVIDER=moark、LLM_CANDIDATES=[moark, deepseek]
    （真冗余双账户）、冷却 TTL=1800（30 分钟）；env 可覆写零变。"""
    assert cfg.LLM_PROVIDER == "moark"
    assert cfg.LLM_CANDIDATES == ["moark", "deepseek"]
    assert cfg.LLM_PROVIDER_COOLDOWN_SECONDS == 1800


def test_default_chain_first_candidate_is_moark(db_session):
    """缺省候选链：resolve_chat 取次位前的首位 moark。"""
    assert resolve_chat(db_session).name == "moark"


# ---------- AC-2：_call 冷却接线（键匹配+边沿通知） ----------


def test_call_402_marks_cooldown_and_resolve_falls_to_second(
        db_session, monkeypatch):
    """_call 402 → 冷却标记生效且键=(name, None)：resolve_chat 跳过该候选
    落次位（键匹配回归——D1 真实形态：主源 moark 402 落备源 deepseek）。
    按 payload 模型名标记的形态在此断言下会静默失效。"""
    from app.providers.moark_chat import MoarkChatProvider

    monkeypatch.setattr(providers_base, "post_json", _raise_status(402))
    p = MoarkChatProvider(db_session)  # name="moark"（候选链首位）
    with pytest.raises(RetryExhausted):
        p._call({"model": "deepseek-v4.1-flash"}, call_point="ut")

    # 键=(name, None)：选源层查询键形态（不带 model）
    assert cooldown_remaining("moark") > 0
    # payload 模型名键未被标记（若按 payload 模型名标记即键不匹配）
    assert cooldown_remaining("moark", model="deepseek-v4.1-flash") == 0.0
    # 标记生效：resolve_chat 跳过首位 moark 落备源 deepseek
    assert resolve_chat(db_session).name == "deepseek"


def test_call_402_edge_notification_fires_once(db_session, monkeypatch):
    """边沿触发：首次进入冷却发一次 provider_switched；冷却期内第二次 402
    不重发（打分轮逐条失败不灌爆通知）。"""
    calls: list[dict] = []

    def recorder(db, *, name, status, ttl_seconds):
        calls.append({"name": name, "status": status, "ttl_seconds": ttl_seconds})

    monkeypatch.setattr("app.notify.triggers.notify_provider_switched", recorder)
    monkeypatch.setattr(providers_base, "post_json", _raise_status(402))
    p = DeepSeekProvider(db_session)
    with pytest.raises(RetryExhausted):
        p._call({"model": "m"}, call_point="ut")
    with pytest.raises(RetryExhausted):
        p._call({"model": "m"}, call_point="ut")

    assert len(calls) == 1
    assert calls[0]["name"] == "deepseek"
    assert calls[0]["status"] == 402
    assert calls[0]["ttl_seconds"] == cfg.LLM_PROVIDER_COOLDOWN_SECONDS


def test_call_401_and_403_also_mark_cooldown(db_session, monkeypatch):
    """供应商级致命全谱（401/403）同样进入冷却（换供应商有意义的错误族）。"""
    for status in (401, 403):
        from app.providers import resolve as resolve_mod
        resolve_mod._reset_for_tests()
        monkeypatch.setattr(providers_base, "post_json", _raise_status(status))
        p = DeepSeekProvider(db_session)
        with pytest.raises(RetryExhausted):
            p._call({"model": "m"}, call_point="ut")
        assert cooldown_remaining("deepseek") > 0, status


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_errors_do_not_mark_cooldown(db_session, monkeypatch, status):
    """429/5xx 只重试不冷却（偶发错误自动熔断无意义）：耗尽后冷却表零标记。"""
    monkeypatch.setattr(providers_base, "post_json", _raise_status(status))
    p = DeepSeekProvider(db_session)
    with pytest.raises(RetryExhausted) as ei:
        p._call({"model": "m"}, call_point="ut")
    assert ei.value.reason == "max_retries_exceeded"
    assert cooldown_remaining("deepseek") == 0.0


def test_single_candidate_mark_present_but_resolve_returns(db_session, monkeypatch):
    """单候选形态：冷却标记无切换效果但无害（resolve_chat 短路冷却判定，
    照常返回该候选——A4 亲证语义）。"""
    monkeypatch.setattr(cfg, "LLM_CANDIDATES", ["deepseek"])
    monkeypatch.setattr(providers_base, "post_json", _raise_status(402))
    p = DeepSeekProvider(db_session)
    with pytest.raises(RetryExhausted):
        p._call({"model": "m"}, call_point="ut")
    assert cooldown_remaining("deepseek") > 0  # 标记在
    assert resolve_chat(db_session).name == "deepseek"  # 但无切换效果


def test_cooldown_expiry_restores_primary(db_session, monkeypatch):
    """冷却期满自然回主源（不做自动恢复探测——到期即回，下次 402 重标）。"""
    from app.providers import resolve as resolve_mod
    from app.providers.moark_chat import MoarkChatProvider

    monkeypatch.setattr(providers_base, "post_json", _raise_status(402))
    p = MoarkChatProvider(db_session)
    with pytest.raises(RetryExhausted):
        p._call({"model": "m"}, call_point="ut")
    assert resolve_chat(db_session).name == "deepseek"
    # 快进冷却到期（直接改冷却表时间戳，零真等待）
    resolve_mod._cooldown_until[("moark", None)] = time.monotonic() - 0.001
    assert resolve_chat(db_session).name == "moark"


def test_ttl_zero_config_marks_noop_and_never_notifies(db_session, monkeypatch):
    """TTL 显式 0（不启用哨兵）时 mark 为 no-op：冷却未发生则边沿通知不发
    （「首次进入冷却」语义——防 TTL=0 形态下逐失败发通知）。"""
    monkeypatch.setattr(cfg, "LLM_PROVIDER_COOLDOWN_SECONDS", 0)
    calls: list[dict] = []
    monkeypatch.setattr("app.notify.triggers.notify_provider_switched",
                        lambda db, **kw: calls.append(kw))
    monkeypatch.setattr(providers_base, "post_json", _raise_status(402))
    p = DeepSeekProvider(db_session)
    with pytest.raises(RetryExhausted):
        p._call({"model": "m"}, call_point="ut")
        p._call({"model": "m"}, call_point="ut")
    assert cooldown_remaining("deepseek") == 0.0
    assert calls == []
