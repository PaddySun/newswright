"""来源失效三级判别测试：hard_failed / suspect / 暂态不标失效，304/skipDays 豁免。

判据（三级判别表）：连续 ≥3 轮 404/403/410 → hard_failed 停抓不重试；连续 ≥3 轮
HTTP 200 但内容空/条目归零（含 200+非 XML 挑战页走空轮侧计数）→ suspect 每 4 轮
一次低频探测；网络/其他错误仅退避计数不标失效；304/非空轮即清零；源声明的
skipDays 期间空轮不计入（豁免写进判据本体）。通知触发不在本批（后续里程碑）。
设计依据见 docs/design-index.md「DT-1」「AC-04.2」「AC-04.3」「AC-04.4」。
"""
import types
from datetime import datetime, timezone

import httpx
import pytest

import app.ingest.rss as rss_mod
from app.ingest.rss import fetch_source
from app.models import Direction, PipelineTask, Source
from app.pipeline.runner import _update_source_health, enqueue_fetch_round


class FakeResp:
    def __init__(self, content=b"", status_code=200, headers=None, with_response=False):
        self.content = content
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})
        self._with_response = with_response

    def raise_for_status(self):
        if self.status_code >= 400:
            # with_response=True 模拟真实 httpx（异常携带响应对象，状态码可判别）
            response = types.SimpleNamespace(status_code=self.status_code) if self._with_response else None
            raise httpx.HTTPStatusError(f"Client error '{self.status_code}'",
                                        request=None, response=response)  # type: ignore


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


def _patch(monkeypatch, responses):
    FakeClient.responses = list(responses)
    monkeypatch.setattr("app.ingest.http.httpx.Client", FakeClient)


_EMPTY_FEED = ("""<?xml version="1.0"?>
<rss version="2.0"><channel><title>empty</title></channel></rss>""").encode()

_HTML_CHALLENGE = b"<html><body>challenge page</body></html>"

_OK_FEED = ("""<?xml version="1.0"?>
<rss version="2.0"><channel><title>t</title>
  <item><guid>https://ex.com/ok-1</guid><link>https://ex.com/ok-1</link>
  <title>OK</title><description>正文足够长以通过规则初筛的内容。</description></item>
</channel></rss>""").encode()


@pytest.fixture()
def rss_source(db_session):
    d = Direction(name="失效判别方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://feeds.example/fail.xml", type="rss")
    db_session.add(src)
    db_session.commit()
    return src


def test_hard_fail_after_three_403_rounds(db_session, rss_source, monkeypatch):
    """连续 3 轮 403 → hard_failed：failure_level 落定、last_error 含状态码、
    failure_since 记录进入时刻。"""
    _patch(monkeypatch, [FakeResp(status_code=403, with_response=True) for _ in range(3)])
    src = rss_source
    for _ in range(3):
        stats = fetch_source(db_session, src)
        _update_source_health(db_session, src, stats)
    src = db_session.merge(src)
    assert src.failure_level == "hard_failed"
    assert src.hard_failures == 3
    assert src.last_error is not None and "403" in src.last_error
    assert src.failure_since is not None


def test_hard_failed_source_never_fetched_again(db_session, rss_source, monkeypatch):
    """hard_failed 源此后采集调度跳过（不再重试，无探测放行）。"""
    src = rss_source
    src.failure_level = "hard_failed"
    db_session.commit()
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    assert rt is not None
    fetch_tasks = [t for t in db_session.query(PipelineTask).filter_by(kind="fetch").all()
                   if (t.payload or {}).get("round_task_id") == rt.id]
    assert fetch_tasks == []
    entry = next(e for e in rt.payload["skipped_backoff"] if e["source_id"] == src.id)
    assert entry["reason"] == "hard_failed"


def test_suspect_after_three_empty_rounds_and_probe(db_session, rss_source, monkeypatch):
    """连续 3 轮 200 但内容空 → suspect；此后调度低频探测（每 4 轮一次）；
    探测轮非空 → 恢复 none 且计数清零。"""
    _patch(monkeypatch, [FakeResp(_EMPTY_FEED) for _ in range(3)])
    src = rss_source
    for _ in range(3):
        _update_source_health(db_session, src, fetch_source(db_session, src))
    src = db_session.merge(src)
    assert src.failure_level == "suspect" and src.empty_rounds == 3

    # 探测节奏：第 1 轮放行探测（skips=0 → 探测窗口），随后 3 轮跳过，第 5 轮再放行
    rounds: list[str | None] = []
    for _ in range(5):
        for t in db_session.query(PipelineTask).all():
            t.status = "DONE"
        db_session.commit()
        rt = enqueue_fetch_round(db_session, triggered_by="test")
        entries = [e for e in rt.payload["skipped_backoff"] if e["source_id"] == src.id]
        fetch_tasks = [t for t in db_session.query(PipelineTask).filter_by(kind="fetch").all()
                       if (t.payload or {}).get("round_task_id") == rt.id]
        rounds.append("probe" if fetch_tasks else (entries[0]["reason"] if entries else "fetched"))
    assert rounds == ["probe", "suspect_probe", "suspect_probe", "suspect_probe", "probe"]

    # 探测轮非空 → 恢复
    _patch(monkeypatch, [FakeResp(_OK_FEED)])
    _update_source_health(db_session, src, fetch_source(db_session, src))
    src = db_session.merge(src)
    assert src.failure_level == "none" and src.empty_rounds == 0
    assert src.failure_since is None


def test_transient_error_not_marked_failed(db_session, rss_source, monkeypatch):
    """网络/其他错误 1-2 轮：failure_level 保持 none，仅退避计数；成功后清零。"""
    src = rss_source
    _patch(monkeypatch, [FakeResp(status_code=500) for _ in range(2)])
    for _ in range(2):
        _update_source_health(db_session, src, fetch_source(db_session, src))
    src = db_session.merge(src)
    assert src.failure_level == "none"
    assert src.backoff_failures == 2

    _patch(monkeypatch, [FakeResp(_OK_FEED)])
    _update_source_health(db_session, src, fetch_source(db_session, src))
    src = db_session.merge(src)
    assert src.backoff_failures == 0 and src.failure_level == "none"


def test_304_round_clears_empty_counter(db_session, rss_source, monkeypatch):
    """304 轮不计空轮且清零既有计数（豁免即清零：源活着，管线活着）。"""
    src = rss_source
    _patch(monkeypatch, [FakeResp(_EMPTY_FEED) for _ in range(2)])
    for _ in range(2):
        _update_source_health(db_session, src, fetch_source(db_session, src))
    src = db_session.merge(src)
    assert src.empty_rounds == 2

    _patch(monkeypatch, [FakeResp(b"", status_code=304)])
    _update_source_health(db_session, src, fetch_source(db_session, src))
    src = db_session.merge(src)
    assert src.empty_rounds == 0 and src.failure_level == "none"


def test_skip_days_exempt_empty_rounds(db_session, rss_source, monkeypatch):
    """源声明 skipDays 且当日命中：空轮不计入连续空轮计数（防周末假警报）。"""
    weekday = ("monday", "tuesday", "wednesday", "thursday", "friday",
               "saturday", "sunday")[datetime.now(timezone.utc).weekday()]
    feed = (f"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>t</title>
      <skipDays><day>{weekday.capitalize()}</day></skipDays>
    </channel></rss>""").encode()
    src = rss_source
    _patch(monkeypatch, [FakeResp(feed) for _ in range(4)])
    for _ in range(4):
        stats = fetch_source(db_session, src)
        assert stats.extra.get("skip_day") is True  # 当日确在声明的休息日内
        _update_source_health(db_session, src, stats)
    src = db_session.merge(src)
    assert src.empty_rounds == 0
    assert src.failure_level == "none"


def test_non_xml_challenge_counts_as_empty_round(db_session, rss_source, monkeypatch):
    """200+非 XML 挑战页：走失败列且按空轮侧计数（3 轮 → suspect，不标 hard）。"""
    src = rss_source
    _patch(monkeypatch, [FakeResp(_HTML_CHALLENGE) for _ in range(3)])
    for _ in range(3):
        stats = fetch_source(db_session, src)
        assert stats.error and stats.error.startswith("non_xml_response")
        _update_source_health(db_session, src, stats)
    src = db_session.merge(src)
    assert src.failure_level == "suspect"
    assert src.hard_failures == 0


def test_transient_round_keeps_last_error_text(db_session, rss_source):
    """暂态错误轮记录最近错误文本（截断 2000）：网络/5xx 类错误发生时
    last_error 保留本轮错误信息供运维排障展示，不清空；后续暂态错误覆盖更新。
    设计依据见 docs/design-index.md「AC-04.4」（v1.8 补句：暂态轮保留最近错误文本）。
    """
    from app.pipeline.runner import _error_stats
    src = rss_source
    _update_source_health(db_session, src, _error_stats("RemoteProtocolError: server closed"))
    src = db_session.merge(src)
    assert src.last_error == "RemoteProtocolError: server closed"
    assert src.failure_level == "none"  # 暂态不标失效（主行为，既有测试另钉）

    _update_source_health(db_session, src, _error_stats("ConnectTimeout: dial fail"))
    src = db_session.merge(src)
    assert src.last_error == "ConnectTimeout: dial fail"
