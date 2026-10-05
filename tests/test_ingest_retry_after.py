"""Retry-After 双形态解析测试（parse_retry_after）：HTTP-date 时区保真与 naive 归一。

条款依据：产品书 AC-05.5/B3（响应含 Retry-After——支持 delta-seconds 与 HTTP-date
双形态，解析失败退回 rate_level 对应缺省间隔）；技术书模块表 ingest/rss 硬约束④
（Retry-After 双形态，解析失败退档位缺省间隔）。HTTP-date 是 D13 动态降频
rate_limited_until 的记账输入：带显式时区偏移的日期必须按其绝对时刻计秒，
naive 形态（-0000）必须按 UTC 归一后照常计秒、不得落入解析失败兜底。
设计依据见 docs/design-index.md「AC-05.5」「B3」「D13」。
"""
from datetime import datetime, timezone

from app.ingest.rss import parse_retry_after

_NOW = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)


def test_http_date_with_explicit_offset_keeps_absolute_moment():
    """带显式时区偏移的 HTTP-date：按绝对时刻计秒（+0200 的 12:00 即 UTC 10:00）。"""
    seconds = parse_retry_after("Wed, 21 Oct 2026 12:00:00 +0200", now=_NOW)
    assert seconds == 3600.0


def test_naive_http_date_normalized_and_counted():
    """-0000 形态的 naive HTTP-date：按 UTC 归一后照常计秒，不落入解析失败兜底。"""
    seconds = parse_retry_after("Wed, 21 Oct 2026 12:00:00 -0000", now=_NOW)
    assert seconds == 10800.0
