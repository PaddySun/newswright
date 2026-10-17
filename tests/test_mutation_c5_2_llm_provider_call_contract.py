"""LLM provider 基类调用契约（providers.base）：耗尽终态两态 + 计量账本 + 档位路由。

三面（C4 后基类下沉的治理条款补面）：
- 重试耗尽抛 RetryExhausted 携带 reason 两态：可重试错误耗尽 = max_retries_
  exceeded；不可重试错误 = error_not_retryable（结构化耗尽可归因）；
- 成功调用的 usage_log 账本行 ok=True（账本口径：成功行不得虚记失败/空）；
- model_tier="reasoner" 档位路由：reasoner 档请求经 tier_request 钩子注入
  thinking 参数（DeepSeek 官方思考档）——首探成功路径不得退化为 chat 档。
设计依据见 docs/design-index.md「TR-5」「LR-1」「ADR-8」。
"""
import pytest

from app.models import UsageLog
from app.providers.base import HTTPProvider
from app.transport.errors import SemanticError, TransportError


class _FakeDB:
    """计量落账桩：收集 record_usage 的 add 对象。"""

    def __init__(self):
        self.rows: list = []

    def add(self, obj):
        self.rows.append(obj)

    def commit(self):
        pass


def _provider_raising(db, exc_factory):
    class _Probe(HTTPProvider):
        name = "probe"

        def _post(self, payload):
            raise exc_factory()

    return _Probe(db, base_url="https://api.test", api_key="k")


def test_retry_exhausted_reason_max_retries_on_retryable(monkeypatch):
    """可重试错误（传输类 429）重试耗尽：RetryExhausted.reason ==
    "max_retries_exceeded"（结构化耗尽的第一态）。"""
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    db = _FakeDB()
    probe = _provider_raising(
        db, lambda: TransportError("HTTP 429: slow", status=429, retry_after=0.0))
    from app.transport.errors import RetryExhausted
    with pytest.raises(RetryExhausted) as ei:
        probe._call({"model": "m"}, call_point="ut")
    assert ei.value.reason == "max_retries_exceeded"


def test_retry_exhausted_reason_not_retryable_on_fatal(monkeypatch):
    """不可重试错误（语义类 402 余额）不进重试循环：RetryExhausted.reason ==
    "error_not_retryable"（结构化耗尽的第二态）。"""
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    db = _FakeDB()
    probe = _provider_raising(
        db, lambda: SemanticError("HTTP 402: 余额不足", status=402))
    from app.transport.errors import RetryExhausted
    with pytest.raises(RetryExhausted) as ei:
        probe._call({"model": "m"}, call_point="ut")
    assert ei.value.reason == "error_not_retryable"


def test_successful_call_records_ok_true_in_usage_log(db_session):
    """成功调用的计量账本行 ok=True（成功行不得落空值——账本成败口径）。"""

    class _Ok(HTTPProvider):
        name = "probe"

        def _post(self, payload):
            return {"choices": [{"message": {"content": "hi"}}], "model": "m"}, {
                "prompt_tokens": 1, "completion_tokens": 2, "billing_units": 0,
                "cache_hit_tokens": 0, "reasoning_tokens": 0,
                "finish_reason": "stop", "model": "echo",
            }

    probe = _Ok(db_session, base_url="https://api.test", api_key="k")
    probe._call({"model": "m"}, call_point="ut")
    row = (db_session.query(UsageLog)
           .filter(UsageLog.call_point == "ut").one())
    assert row.ok is True


def test_chat_reasoner_tier_routes_thinking_payload(db_session, monkeypatch):
    """model_tier="reasoner" 首探成功：请求经 tier_request 钩子携带
    DeepSeek 官方思考参数（thinking enabled + 思考档模型）——reasoner 档
    不得退化为 chat 档请求。"""
    from app.providers.deepseek import DeepSeekProvider

    captured: list = []

    class _Probe(DeepSeekProvider):
        def _post(self, payload):
            captured.append(dict(payload))
            return ({"choices": [{"message": {"content": "答案", "role": "assistant"}}],
                     "model": "deepseek-flash",
                     "usage": {}}, {"prompt_tokens": 1, "completion_tokens": 1,
                                    "billing_units": 0, "cache_hit_tokens": 0,
                                    "reasoning_tokens": 0, "finish_reason": "stop"})

    probe = _Probe(db_session)
    monkeypatch.setattr("app.config.DEEPSEEK_TIER_MODE", "thinking_params")
    content, _model = probe.chat(
        [{"role": "user", "content": "想清楚再答"}],
        call_point="ut", model_tier="reasoner")
    assert content == "答案"
    assert captured[0]["thinking"] == {"type": "enabled"}
    assert probe.reasoner_available is True  # 首探成功：档位探测状态记可用
