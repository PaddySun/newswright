"""aware-UTC 时钟契约测试（D16 双层口径，2026-10-08 拍板条款）。

覆盖口径（设计依据见 docs/design-index.md「D16」）：后端时间取值与输出一律
aware-UTC——naive 本地时钟（datetime.now(None)）与时区标签漂移
（astimezone(None)）均为缺陷；timezone 键职责=日切口径与用户侧呈现。

断言形态：宿主无法模拟时区切换（Windows 无 tzset）——按条款本体直接断言
「时钟取值必须显式传 timezone.utc」：模块 datetime 打桩记录 now() 的 tz 实参
（行为保真），取值点若落 naive 本地时钟即违约。窗口消费点（24h 观测窗）的
cutoff 同源同判。

网络纪律：纯 DB+打桩，零出网；生产代码零改动。
"""
from datetime import datetime, timedelta, timezone

import pytest

import app.api.routes as routes_mod
import app.timeline as timeline_mod
from app.models import Direction, Item, PipelineTask, ScoreResult, Source
from app.timeline import local_date_key, local_day_start, local_day_start_after
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


class _UTCProbeDatetime(datetime):
    """记录 now(tz) 实参、行为保真的 datetime 桩。"""

    calls = []

    @classmethod
    def now(cls, tz=None):
        _UTCProbeDatetime.calls.append(tz)
        return datetime.now(tz)


class _AstimezoneProbeDatetime(_UTCProbeDatetime):
    """记录 astimezone 实参、now 取值继承 _UTCProbeDatetime 的 datetime 桩（保真转发）。"""

    astimezone_args = []

    def astimezone(self, tz=None):
        _AstimezoneProbeDatetime.astimezone_args.append(tz)
        return super().astimezone(tz)


def test_local_date_key_now_is_aware_utc(monkeypatch):
    """日期键的默认时钟取 aware-UTC（D16：naive 本地时钟为缺陷）。"""
    _UTCProbeDatetime.calls = []
    monkeypatch.setattr(timeline_mod, "datetime", _UTCProbeDatetime)
    local_date_key(SHANGHAI)
    assert _UTCProbeDatetime.calls, "日期键必须产生时钟取值"
    assert all(tz is timezone.utc for tz in _UTCProbeDatetime.calls), \
        "D16：后端时间取值一律 aware-UTC（now(None) naive 本地时钟为缺陷）"


def test_local_day_start_now_is_aware_utc(monkeypatch):
    """日切零点的默认时钟取 aware-UTC。"""
    _UTCProbeDatetime.calls = []
    monkeypatch.setattr(timeline_mod, "datetime", _UTCProbeDatetime)
    local_day_start(SHANGHAI)
    assert _UTCProbeDatetime.calls
    assert all(tz is timezone.utc for tz in _UTCProbeDatetime.calls)


def test_local_day_start_output_label_is_utc(monkeypatch):
    """日切零点输出的时区标签显式为 UTC（D16：标签漂移为缺陷）。

    astimezone(None) 随宿主本地时区贴标签——本机（UTC+8）给 +08 偏移对象、
    UTC 宿主给 timedelta(0) 偏移对象，均非 datetime.timezone.utc 单例——
    tzinfo is timezone.utc 断言在任意宿主上均能区分两种形态。"""
    monkeypatch.setattr(timeline_mod, "datetime", _UTCProbeDatetime)
    result = local_day_start(SHANGHAI)
    assert result.tzinfo is timezone.utc, \
        "D16：输出时刻的时区标签必须显式为 UTC（astimezone(None) 随宿主漂移）"


def test_local_day_start_after_now_and_label_are_utc(monkeypatch):
    """TTL 零点：默认时钟取值 aware-UTC、输出时区标签显式为 UTC。"""
    _UTCProbeDatetime.calls = []
    monkeypatch.setattr(timeline_mod, "datetime", _UTCProbeDatetime)
    result = local_day_start_after(SHANGHAI, 7)
    assert all(tz is timezone.utc for tz in _UTCProbeDatetime.calls), \
        "D16：默认时钟取值 aware-UTC"
    assert result.tzinfo is timezone.utc, \
        "D16：输出时刻的时区标签必须显式为 UTC"


def _seed_failed_score_task(db, *, hours_ago=1):
    t = PipelineTask(kind="score", status="FAILED", payload={},
                     updated_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago))
    db.add(t)
    db.commit()
    return t


def test_unscored_entries_window_clock_is_aware_utc(db_session, monkeypatch):
    """未评分条目 24h 窗的 cutoff 时钟取 aware-UTC（D16；「近 24h」滚动窗）。"""
    _UTCProbeDatetime.calls = []
    monkeypatch.setattr(routes_mod, "datetime", _UTCProbeDatetime)
    _seed_failed_score_task(db_session)
    routes_mod._unscored_entries(db_session, None)
    assert _UTCProbeDatetime.calls, "窗口 cutoff 必须产生时钟取值"
    assert all(tz is timezone.utc for tz in _UTCProbeDatetime.calls), \
        "D16：24h 窗时钟取值一律 aware-UTC（naive 本地时钟使窗口随宿主漂移）"
