"""日切零点精确性测试：今日零点/TTL 零点按时区取整到秒与微秒（D16 日切起点）。

设计依据见 docs/design-index.md「D16」。
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.timeline import local_day_start, local_day_start_after

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_local_day_start_truncates_seconds_and_micros():
    """今日零点 = 本地日零点整（秒/微秒一并归零）。"""
    now = datetime(2026, 10, 6, 16, 30, 45, 123456, tzinfo=timezone.utc)
    assert local_day_start(SHANGHAI, now_utc=now) == \
        datetime(2026, 10, 6, 16, 0, 0, 0, tzinfo=timezone.utc)


def test_local_day_start_after_truncates_seconds_and_micros():
    """TTL 零点 = 第 N 日本地日零点整（秒/微秒一并归零）。"""
    now = datetime(2026, 10, 6, 10, 0, 30, 999999, tzinfo=timezone.utc)
    assert local_day_start_after(SHANGHAI, 7, now_utc=now) == \
        datetime(2026, 10, 12, 16, 0, 0, 0, tzinfo=timezone.utc)
