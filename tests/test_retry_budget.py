"""进程级 retry budget 测试（BE-4/AC-3）：滑窗计数（第 51 次/分 False、
caller 隔离、滑窗过期恢复、site_config 可配）+ 三消费点（llm/search/hot）
耗尽后快速失败用例（零真 sleep）。

阈值语义注记：打分轮 200 条全失败×重试 2=400 次 spend 会熔断——这正是
预算目的（故障期快速失败到 FAILED 下轮续跑，防锤）。
设计依据见 docs/design-index.md「TG-3」（BE-4 增补）。
"""
import time as _time

import pytest

import app.transport.retry_budget as retry_budget
from app.siteconfig import DEFAULTS, set_config
from app.transport.errors import (
    REASON_ERROR_NOT_RETRYABLE,
    REASON_MAX_RETRIES_EXCEEDED,
    RetryExhausted,
    TransportError,
)
from app.transport.retry_budget import RETRY_BUDGET_WINDOW_S, spend


@pytest.fixture(autouse=True)
def _reset_budget_window():
    """进程级预算窗复位判例（每测试文件 fixture 复位）。"""
    retry_budget._reset_for_tests()
    yield
    retry_budget._reset_for_tests()


# ---------- 滑窗计数核心语义 ----------


def test_spend_51st_per_minute_false():
    """同 caller 一分钟窗口：前 50 次 True、第 51 次 False。"""
    assert all(spend("llm") for _ in range(50)) is True
    assert spend("llm") is False


def test_callers_isolated():
    """caller 名隔离：llm 熔断不影响 search/hot 各自的预算。"""
    for _ in range(50):
        spend("llm")
    assert spend("llm") is False
    assert spend("search") is True
    assert spend("hot") is True


def test_sliding_window_recovery():
    """滑窗过期恢复：窗口滑出后预算恢复（注入时钟零真等待）。"""
    t = 1000.0

    def now() -> float:
        return t

    assert all(spend("hot", _now=now) for _ in range(50))
    assert spend("hot", _now=now) is False
    t += RETRY_BUDGET_WINDOW_S + 1.0
    assert spend("hot", _now=now) is True


def test_threshold_configurable_via_site_config(db_session):
    """阈值 site_config 可配：retry_budget_per_minute=2 → 第 3 次 False。"""
    set_config(db_session, "retry_budget_per_minute", 2)
    assert spend("llm", db=db_session) is True
    assert spend("llm", db=db_session) is True
    assert spend("llm", db=db_session) is False


def test_bad_threshold_value_falls_back(db_session):
    """非法阈值回退缺省 50（warn 不炸）。"""
    set_config(db_session, "retry_budget_per_minute", "many")
    assert all(spend("llm", db=db_session) for _ in range(50)) is True
    assert spend("llm", db=db_session) is False


def test_default_registered_in_defaults():
    assert DEFAULTS["retry_budget_per_minute"] == 50
    assert RETRY_BUDGET_WINDOW_S == 60


def test_stub_db_without_orm_face_falls_back():
    """桩 db（既有测试 _FakeDB 无 ORM 面）不炸：读配置失败回退代码缺省。"""

    class _FakeDB:
        pass

    assert spend("llm", db=_FakeDB()) is True


# ---------- 消费点①：providers/_call（llm） ----------


class _FakeDB:
    def __init__(self):
        self.rows = []

    def add(self, obj):
        self.rows.append(obj)

    def commit(self):
        pass


def _llm_probe(db, exc_factory):
    from app.providers.base import HTTPProvider

    class _Probe(HTTPProvider):
        name = "probe"

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.posts = 0

        def _post(self, payload):
            self.posts += 1
            raise exc_factory()

    return _Probe(db, base_url="https://api.test", api_key="k")


def test_llm_consumer_budget_exhausted_fails_fast(monkeypatch):
    """耗尽后：决定重试前 spend False → 不再重试——reason=不可重试终态、
    仅 1 次尝试、零 sleep（快速失败）。"""
    sleeps = []
    monkeypatch.setattr(_time, "sleep", lambda s: sleeps.append(s))
    for _ in range(50):
        spend("llm")
    assert spend("llm") is False
    db = _FakeDB()
    probe = _llm_probe(db, lambda: TransportError("HTTP 429: slow", status=429,
                                                  retry_after=0.0))
    with pytest.raises(RetryExhausted) as ei:
        probe._call({"model": "m"}, call_point="ut")
    assert ei.value.reason == REASON_ERROR_NOT_RETRYABLE
    assert probe.posts == 1
    assert sleeps == []


def test_llm_consumer_fresh_budget_retries_as_before(monkeypatch):
    """预算未耗尽时重试行为零变（既有契约不回退：3 次尝试、耗尽 reason 仍为
    max_retries_exceeded——预算只是新增的快速失败闸）。"""
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    db = _FakeDB()
    probe = _llm_probe(db, lambda: TransportError("HTTP 429: slow", status=429,
                                                  retry_after=0.0))
    with pytest.raises(RetryExhausted) as ei:
        probe._call({"model": "m"}, call_point="ut")
    assert ei.value.reason == REASON_MAX_RETRIES_EXCEEDED
    assert probe.posts == 3  # 首次 + 重试 ≤2


# ---------- 消费点②：search/base（search） ----------


def test_search_consumer_budget_exhausted_fails_fast(monkeypatch):
    """耗尽后：search 走非 retryable 分支——SearchRetryExhausted 结构化耗尽
    （reason=error_not_retryable）、仅 1 次真实调用、零 sleep。"""
    from app.search.base import SearchError, SearchProvider, SearchRetryExhausted

    sleeps = []
    monkeypatch.setattr(_time, "sleep", lambda s: sleeps.append(s))
    for _ in range(50):
        spend("search")
    assert spend("search") is False

    class _Probe(SearchProvider):
        name = "probe"

        def __init__(self):
            self.calls = 0

        def _search(self, query, count, opts):
            self.calls += 1
            err = SearchError("HTTP 500: boom")
            err.retryable = True  # type: ignore[attr-defined]
            raise err

    probe = _Probe()
    with pytest.raises(SearchRetryExhausted) as ei:
        probe.search("q")
    assert ei.value.reason == REASON_ERROR_NOT_RETRYABLE
    assert probe.calls == 1
    assert sleeps == []


# ---------- 消费点③：hot/service（hot） ----------


def test_hot_consumer_budget_exhausted_breaks_to_next_candidate(db_session, monkeypatch):
    """耗尽后：hot 走 break 换候选——默认单候选下 get_json 仅 1 次（不重试）、
    终态 RetryExhausted、零 sleep。"""
    import app.hot.service as hot_service

    sleeps = []
    monkeypatch.setattr(_time, "sleep", lambda s: sleeps.append(s))
    calls = []

    def fake_get_json(url, **kw):
        calls.append(url)
        raise TransportError("HTTP 503: down", retryable=True, status=503)

    monkeypatch.setattr(hot_service, "get_json", fake_get_json)
    for _ in range(50):
        spend("hot")
    assert spend("hot") is False

    with pytest.raises(RetryExhausted) as ei:
        hot_service.fetch_platform("weibo", db=db_session)
    assert calls and len(calls) == 1  # 单候选首败即放弃（不重试）
    assert sleeps == []
    # 候选循环语义保持：换候选而非换终态口径（reason 仍按错误可重试性归因）
    assert ei.value.reason == REASON_MAX_RETRIES_EXCEEDED
