"""skipDays 豁免信号测试：源声明休息日命中当日时暴露 skip_day 判据信号。

条款依据：产品书 DT-1/AC-04.3（源声明 skipDays 期间不计入连续空轮计数——豁免
写进判据本体，任何一轮非空即清零）；技术书模块表 ingest/rss 行（skipDays 读取并
暴露为 suspect 判据豁免信号）。feed 声明的星期名归一小写后与当日星期对位，
七个星期日逐日钉面：任一星期名失真都会使当日空轮被误计入 suspect 判据。
设计依据见 docs/design-index.md「DT-1」「AC-04.3」。
"""
from datetime import datetime, timedelta, timezone

import pytest

import app.ingest.rss as rss_mod
from app.ingest.rss import fetch_source
from app.models import Direction, Source

_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_BASE = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)  # 星期一，逐日 +i 覆盖一周


def _freeze_clock(monkeypatch, moment: datetime) -> None:
    """冻结 ingest.rss 的时钟：now() 恒返回给定时刻（星期判定确定性）。"""

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment

    monkeypatch.setattr(rss_mod, "datetime", _Frozen)


@pytest.mark.parametrize("day_offset", range(7))
def test_skip_day_flag_true_on_declared_rest_day(db_session, monkeypatch, day_offset):
    """feed 声明当日为休息日 → stats.extra['skip_day'] 置真（suspect 判据豁免信号）。"""
    moment = _BASE + timedelta(days=day_offset)
    day_name = _NAMES[moment.weekday()]
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
        f"<skipdays><day>{day_name.upper()}</day></skipdays>"
        "<item><guid>https://ex.com/1</guid><link>https://ex.com/1</link>"
        "<title>条目</title><description>正文足够长以通过规则初筛的占位内容，"
        "长度需要超过规则初筛的最小字数要求才能被正常采集入库。</description></item>"
        "</channel></rss>"
    ).encode("utf-8")

    d = Direction(name=f"跳休方向{day_offset}", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url=f"https://feeds.example/skip-{day_offset}.xml",
                 type="rss")
    db_session.add(src)
    db_session.commit()

    _freeze_clock(monkeypatch, moment)

    class FakeResp:
        content = feed
        status_code = 200
        headers = rss_mod.httpx.Headers({"Content-Type": "application/rss+xml"})

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            return FakeResp()

    monkeypatch.setattr("app.ingest.http.httpx.Client", FakeClient)

    stats = fetch_source(db_session, db_session.merge(src))
    assert stats.extra.get("skip_day") is True
