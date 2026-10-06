"""429/Retry-After 动态降频测试：间隔倍增、双形态解析、两轮正常恢复、不计退避。

条款：遇 429 或响应含 Retry-After（delta-seconds 与 HTTP-date 双形态，解析失败退
档位缺省间隔）→ 间隔倍增 15→30→60（上限 240 分钟）并记录 rate_limited_until；
期间轮次跳过该源（reason=rate_limited，不计失败退避）；连续 2 轮正常后逐级恢复。
设计依据见 docs/design-index.md「AC-05.5」「D13」「B3」。
"""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

import app.ingest.rss as rss_mod
from app.ingest.rss import fetch_source, parse_retry_after
from app.models import Direction, PipelineTask, Source
from app.pipeline.runner import _update_source_health, enqueue_fetch_round
from app.pipeline.skip_policy import rate_limit_minutes


class FakeResp:
    def __init__(self, content=b"", status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"Client error '{self.status_code}'",
                                        request=None, response=None)  # type: ignore


class FakeClient:
    responses: list[FakeResp] = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None):
        return type(self).responses.pop(0)


_OK_FEED = ("""<?xml version="1.0"?>
<rss version="2.0"><channel><title>t</title>
  <item><guid>https://ex.com/rl-1</guid><link>https://ex.com/rl-1</link>
  <title>OK</title><description>正文足够长以通过规则初筛的内容。</description></item>
</channel></rss>""").encode()


@pytest.fixture()
def rss_source(db_session):
    d = Direction(name="降频方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://feeds.example/rl.xml", type="rss")
    db_session.add(src)
    db_session.commit()
    return src


def _run_round(db_session, monkeypatch, responses):
    FakeClient.responses = list(responses)
    monkeypatch.setattr("app.ingest.http.httpx.Client", FakeClient)
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    if rt is None:
        return None
    from app.pipeline.runner import process_fetch_round

    return process_fetch_round(db_session, rt)


def test_429_doubles_interval_and_not_counted_as_backoff(db_session, rss_source, monkeypatch):
    """429 → 档位 1、until=30 分钟（15×2）；任务不算失败、不计失败退避。"""
    src = rss_source
    before = datetime.now(timezone.utc)
    _run_round(db_session, monkeypatch, [FakeResp(status_code=429)])
    src = db_session.merge(src)
    assert src.rate_level == 1
    assert src.rate_limited_until is not None
    until = src.rate_limited_until if src.rate_limited_until.tzinfo else src.rate_limited_until.replace(tzinfo=timezone.utc)
    assert until - before <= timedelta(minutes=rate_limit_minutes(1) + 1)
    assert src.backoff_failures == 0  # 限流不计失败退避
    task = db_session.query(PipelineTask).filter_by(kind="fetch").order_by(PipelineTask.id.desc()).first()
    assert task.status == "DONE" and task.last_error is None


def test_rate_limited_rounds_skipped(db_session, rss_source, monkeypatch):
    """until 期内的轮次跳过该源（reason=rate_limited），不发起网络请求。"""
    src = rss_source
    src.rate_level = 1
    src.rate_limited_until = datetime.now(timezone.utc) + timedelta(minutes=30)
    db_session.commit()
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    fetch_tasks = [t for t in db_session.query(PipelineTask).filter_by(kind="fetch").all()
                   if (t.payload or {}).get("round_task_id") == rt.id]
    assert fetch_tasks == []
    entry = next(e for e in rt.payload["skipped_backoff"] if e["source_id"] == src.id)
    assert entry["reason"] == "rate_limited"


def test_retry_after_delta_seconds(db_session, rss_source, monkeypatch):
    """Retry-After delta-seconds 形态：until = now + 秒数。"""
    before = datetime.now(timezone.utc)
    _run_round(db_session, monkeypatch, [FakeResp(status_code=429, headers={"Retry-After": "120"})])
    src = db_session.merge(rss_source)
    until = src.rate_limited_until if src.rate_limited_until.tzinfo else src.rate_limited_until.replace(tzinfo=timezone.utc)
    assert timedelta(minutes=1) <= until - before <= timedelta(minutes=3)


def test_retry_after_http_date(db_session, rss_source, monkeypatch):
    """Retry-After HTTP-date 形态：until = 该日期时刻。"""
    target = datetime.now(timezone.utc) + timedelta(minutes=5)
    _run_round(db_session, monkeypatch, [FakeResp(
        status_code=429, headers={"Retry-After": format_datetime(target, usegmt=True)})])
    src = db_session.merge(rss_source)
    until = src.rate_limited_until if src.rate_limited_until.tzinfo else src.rate_limited_until.replace(tzinfo=timezone.utc)
    assert abs((until - target).total_seconds()) < 5


def test_retry_after_unparseable_falls_back_to_ladder(db_session, rss_source, monkeypatch):
    """Retry-After 解析失败 → 退档位缺省间隔（30 分钟）。"""
    before = datetime.now(timezone.utc)
    _run_round(db_session, monkeypatch, [FakeResp(status_code=429, headers={"Retry-After": "soon"})])
    src = db_session.merge(rss_source)
    until = src.rate_limited_until if src.rate_limited_until.tzinfo else src.rate_limited_until.replace(tzinfo=timezone.utc)
    assert until - before <= timedelta(minutes=rate_limit_minutes(1) + 1)
    assert src.rate_limited_until is not None


def test_recovery_two_normal_rounds_per_level(db_session, rss_source, monkeypatch):
    """逐级恢复：降频期满后每 2 轮正常降 1 档；0 档解除 until。"""
    src = rss_source
    src.rate_level = 1
    src.rate_limited_until = datetime.now(timezone.utc) - timedelta(minutes=1)  # 已期满
    db_session.commit()

    _run_round(db_session, monkeypatch, [FakeResp(_OK_FEED)])
    src = db_session.merge(src)
    assert src.rate_ok_rounds == 1 and src.rate_level == 1  # 第 1 轮正常：尚不降档

    _run_round(db_session, monkeypatch, [FakeResp(_OK_FEED)])
    src = db_session.merge(src)
    assert src.rate_level == 0 and src.rate_limited_until is None  # 连续 2 轮 → 解除


def test_parse_retry_after_forms():
    """双形态解析纯逻辑：秒数/HTTP-date/垃圾值/空值。"""
    now = datetime.now(timezone.utc)
    assert parse_retry_after("120", now=now) == 120.0
    future = now + timedelta(minutes=5)
    assert abs(parse_retry_after(format_datetime(future, usegmt=True), now=now) - 300) < 5
    assert parse_retry_after("soon", now=now) is None
    assert parse_retry_after("", now=now) is None
    assert parse_retry_after(None, now=now) is None


def test_rate_limit_ladder_cap():
    """阶梯封顶：档位再高也不超过 240 分钟。"""
    assert [rate_limit_minutes(0), rate_limit_minutes(1), rate_limit_minutes(2),
            rate_limit_minutes(3), rate_limit_minutes(8)] == [15, 30, 60, 120, 240]
