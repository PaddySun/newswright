"""热榜聚合取用与终态账契约（hot.service）：状态码优先 + 候选位 + 重试上限 + 终态归因。

六面（热榜治理条款补面——聚合取用的出网治理路径）：
- 落账状态 HTTP 码优先：带 status 的错误取 HTTP 码；RetryExhausted 取
  末次尝试链的状态码；无码才退化为错误类别名；
- 终态账 latency_ms=整次取用真实耗时（含重试）——不得虚记 0 或巨值；
- 响应非 dict JSON（契约违例形态）走 ContractError 域：换候选、全败抛
  RetryExhausted——不得以 AttributeError 逃逸错误处理面；
- 首候选不可重试失败后按序取次候选（候选位语义），不提前放弃；
- 域级重试 ≤2 次（首次+2 重试=每候选至多 3 次尝试）；
- 可重试传输错误全候选耗尽时 reason=max_retries_exceeded（终态归因两态）。
设计依据见 docs/design-index.md「HR-2」「HR-3」「TR-5」。
"""
import time as _time

import pytest

import app.hot.service as hot
from app.models import HotCallLog
from app.transport.errors import (
    REASON_MAX_RETRIES_EXCEEDED,
    RetryExhausted,
    SemanticError,
    TransportError,
)


class _StubResp:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body


def test_ledger_status_prefers_http_status_code():
    """落账状态取末次尝试链的状态码（生产调用面形态：fetch_platform 终态
    恒传 RetryExhausted）：链末错误带码取码；链末无码退化为终态对象自身
    类别名。"""
    with_code = RetryExhausted(
        "x", reason=REASON_MAX_RETRIES_EXCEEDED,
        errors=[TransportError("HTTP 503", status=503),
                TransportError("HTTP 429", status=429)])
    assert hot._ledger_status(with_code) == "429"
    codeless = RetryExhausted(
        "x", reason=REASON_MAX_RETRIES_EXCEEDED,
        errors=[SemanticError("无码语义错")])
    assert hot._ledger_status(codeless) == "RetryExhausted"


def test_success_ledger_records_real_latency(db_session, monkeypatch):
    """成功取用一行终态账：latency_ms=整次取用真实耗时（含桩内延时），
    ok=True、status=HTTP 码、provider=聚合器 origin。"""
    def _slow_get_json(url, **kwargs):
        _time.sleep(0.05)  # 真实耗时锚：终态账的 latency 必须量到它
        return _StubResp({"items": [{"title": "t", "url": "u", "extra": {}}]})

    monkeypatch.setattr(hot, "get_json", _slow_get_json)
    kept = hot.fetch_platform("weibo", db=db_session)
    assert len(kept) == 1
    row = db_session.query(HotCallLog).one()
    assert row.ok is True
    assert row.status == "200"
    assert 5 <= row.latency_ms <= 10_000


def test_non_dict_json_body_raises_contract_exhaustion(monkeypatch):
    """响应为非 dict JSON（契约违例形态）：走 ContractError 域——换候选、
    全败抛 RetryExhausted 终态；不得以 AttributeError 逃逸错误处理面。"""
    monkeypatch.setattr(hot, "get_json", lambda url, **kw: _StubResp([1, 2]))
    with pytest.raises(RetryExhausted):
        hot.fetch_platform("weibo", db=None)


def test_unretryable_failure_falls_through_to_next_candidate(monkeypatch):
    """首候选不可重试失败：按序取次候选（候选位语义）——次候选成功则
    返回其条目，不提前放弃整轮取用。"""
    import app.config as cfg

    def _flaky(url, **kw):
        if "first" in url:
            raise TransportError("HTTP 403 forbidden", retryable=False, status=403)
        return _StubResp({"items": [{"title": "ok", "url": "u", "extra": {}}]})

    monkeypatch.setattr(cfg, "HOT_AGG_CANDIDATES",
                        ["https://first.example", "https://second.example"])
    monkeypatch.setattr(hot, "get_json", _flaky)
    kept = hot.fetch_platform("weibo", db=None)
    assert [it["title"] for it in kept] == ["ok"]


def test_transport_retry_attempts_capped_at_two_per_candidate(monkeypatch):
    """域级重试 ≤2 次：可重试传输错误下每候选至多 3 次尝试（首次+2 重试）、
    退避恰 2 次（每次重试前恰一次 sleep，耗尽后不再退避）；全候选耗尽抛
    RetryExhausted 且 reason=max_retries_exceeded（可重试终态不得误记为
    不可重试）。"""
    calls: list[str] = []

    def _always_503(url, **kw):
        calls.append(url)
        raise TransportError("HTTP 503", status=503, retryable=True)

    class _FakeTime:
        sleeps = 0
        monotonic = staticmethod(_time.monotonic)

        def sleep(self, _s):
            self.sleeps += 1

    fake_time = _FakeTime()
    monkeypatch.setattr(hot, "time", fake_time)
    monkeypatch.setattr(hot, "get_json", _always_503)
    with pytest.raises(RetryExhausted) as ei:
        hot.fetch_platform("weibo", db=None)
    assert len(calls) == 3
    assert fake_time.sleeps == 2
    assert ei.value.reason == REASON_MAX_RETRIES_EXCEEDED
