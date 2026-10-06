"""时区与日切测试（产品书 §0 时区决策，设计依据见 docs/design-index.md
「D16」）：site_config timezone 键（默认 Asia/Shanghai）经统一解析函数接入
四个日切消费点——①预算日 ②观测滚动窗（时区不变式口径确认）③通知自然日
④TTL 零点；非法值回退 UTC 并 WARN。
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import app.timeline as timeline
from app.models import UsageLog
from app.pipeline.budget import tokens_used_today
from app.siteconfig import set_config
from app.timeline import local_date_key, local_day_start, local_day_start_after, resolve_zone

SHANGHAI = ZoneInfo("Asia/Shanghai")


# ---------- 解析函数 ----------

def test_resolve_zone_valid_and_default():
    assert resolve_zone("Asia/Shanghai") is not None
    assert resolve_zone("Asia/Shanghai").key == "Asia/Shanghai"


def test_resolve_zone_invalid_falls_back_utc_with_warn(caplog):
    with caplog.at_level("WARNING", logger="newswright.timeline"):
        z = resolve_zone("Mars/Olympus")
    assert z.key == "UTC"
    assert any("Mars/Olympus" in r.message for r in caplog.records)


def test_resolve_zone_empty_falls_back_utc():
    assert resolve_zone(None).key == "UTC"
    assert resolve_zone("").key == "UTC"


def test_local_day_start_shanghai_crossing():
    """跨日场景：UTC 16:30 = 上海次日 00:30 → 今日零点（上海）= UTC 16:00。"""
    now = datetime(2026, 10, 6, 16, 30, tzinfo=timezone.utc)
    assert local_day_start(SHANGHAI, now_utc=now) \
        == datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)


def test_local_day_start_shanghai_same_day():
    """未跨日场景：UTC 10:00 = 上海 18:00（同日）→ 今日零点=前一日 UTC 16:00。"""
    now = datetime(2026, 10, 6, 10, 0, tzinfo=timezone.utc)
    assert local_day_start(SHANGHAI, now_utc=now) \
        == datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)


def test_local_day_start_after_seven_days():
    """TTL 零点：上海 18:00 起 +7 天 → 第 7 日上海零点 = UTC 前 8 小时。"""
    now = datetime(2026, 10, 6, 10, 0, tzinfo=timezone.utc)  # 上海 10-06 18:00
    assert local_day_start_after(SHANGHAI, 7, now_utc=now) \
        == datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)  # 上海 10-13 00:00


def test_local_date_key_uses_zone():
    now = datetime(2026, 10, 6, 16, 30, tzinfo=timezone.utc)
    assert local_date_key(SHANGHAI, now_utc=now) == "2026-10-07"  # 上海已跨日
    assert local_date_key(ZoneInfo("UTC"), now_utc=now) == "2026-10-06"


# ---------- 消费点①：预算日 ----------

def test_budget_day_cut_excludes_yesterday_local(db_session):
    """预算日切翻转：站点时区今日零点前的消耗（上海前一日）不计入今日预算，
    零点后的计入。"""
    from app.timeline import site_zone

    set_config(db_session, "timezone", "Asia/Shanghai")
    day_start = local_day_start(site_zone(db_session))
    db_session.add(UsageLog(provider="p", model="m", call_point="writing",
                            prompt_tokens=100, completion_tokens=0,
                            created_at=day_start - timedelta(minutes=60)))
    db_session.add(UsageLog(provider="p", model="m", call_point="writing",
                            prompt_tokens=50, completion_tokens=0,
                            created_at=day_start + timedelta(minutes=1)))
    db_session.commit()
    assert tokens_used_today(db_session) == 50


def test_budget_day_cut_utc_fallback_on_invalid_zone(db_session):
    """非法时区回退 UTC：日切起点=UTC 零点（回退不阻断预算判定）。"""
    from app.timeline import site_zone

    set_config(db_session, "timezone", "Not/AZone")
    assert site_zone(db_session).key == "UTC"
    utc_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)
    db_session.add(UsageLog(provider="p", model="m", call_point="writing",
                            prompt_tokens=10, completion_tokens=0,
                            created_at=utc_start + timedelta(minutes=1)))
    db_session.commit()
    assert tokens_used_today(db_session) == 10


# ---------- 消费点②：观测滚动窗（时区不变式口径确认） ----------

def test_observability_rolling_window_timezone_invariant(db_session):
    """观测 24h 窗为滚动窗：换任意站点时区，窗口边界（now-24h）不变——
    时区键不改变滚动窗语义（无零点切口径确认）。"""
    from app.observability import _llm_error_rate_24h

    now = datetime.now(timezone.utc)
    db_session.add(UsageLog(provider="p", model="m", call_point="scoring",
                            prompt_tokens=1, completion_tokens=1, ok=False,
                            created_at=now - timedelta(hours=1)))
    db_session.add(UsageLog(provider="p", model="m", call_point="scoring",
                            prompt_tokens=1, completion_tokens=1, ok=True,
                            created_at=now - timedelta(hours=2)))
    db_session.commit()
    set_config(db_session, "timezone", "Asia/Shanghai")
    rate_sh = _llm_error_rate_24h(db_session, now)
    set_config(db_session, "timezone", "UTC")
    rate_utc = _llm_error_rate_24h(db_session, now)
    set_config(db_session, "timezone", "America/New_York")
    rate_ny = _llm_error_rate_24h(db_session, now)
    assert rate_sh == rate_utc == rate_ny == 0.5


# ---------- 消费点③：通知自然日 ----------

def test_notify_budget_day_key_uses_site_zone(db_session, monkeypatch):
    """预算触发通知的自然日去重键取站点时区日期（上海跨日后=次日，UTC=当日）。"""
    from app.notify.triggers import notify_budget_exceeded

    set_config(db_session, "timezone", "Asia/Shanghai")

    class _FixedDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 6, 16, 30, tzinfo=timezone.utc)

    monkeypatch.setattr(timeline, "datetime", _FixedDT)
    sent = []

    def fake_dispatch(db, *, switch_key, category, dedupe_key, subject, body):
        sent.append(dedupe_key)
        return {"sent": True}

    monkeypatch.setattr("app.notify.triggers._dispatch", fake_dispatch)
    notify_budget_exceeded(db_session, used_tokens=100, budget=100)
    assert sent == ["daily-2026-10-07"]  # 上海已跨入次日，自然日=10-07


# ---------- 消费点④：TTL 零点 ----------

def test_temp_direction_ttl_midnight_in_site_zone(auth_client, db_session, monkeypatch):
    """临时方向 TTL 到期时刻 = 站点时区第 N 日零点（D16 落地：上海 18:00 建
    +7 天 → 上海 10-13 00:00 = UTC 10-12 16:00）。"""
    from app.timeline import site_zone

    set_config(db_session, "timezone", "Asia/Shanghai")

    class _FixedDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 6, 10, 0, tzinfo=timezone.utc)  # 上海 18:00

    monkeypatch.setattr(timeline, "datetime", _FixedDT)
    r = auth_client.post("/api/directions", json={
        "name": "时区TTL方向", "prompt": "p", "threshold": 60,
        "temp": True, "ttl_days": 7})
    assert r.status_code == 201
    expires = datetime.fromisoformat(r.json()["expires_at"].replace("Z", "+00:00"))
    if expires.tzinfo is None:  # SQLite 存储丢 tz，读回为 naive（按 UTC 解释）
        expires = expires.replace(tzinfo=timezone.utc)
    assert expires == datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)


def test_hot_to_direction_ttl_uses_site_zone_midnight(auth_client, db_session,
                                                      monkeypatch):
    """热点转临时方向同口径：到期=站点时区第 7 日零点。"""
    from app.timeline import site_zone

    set_config(db_session, "timezone", "Asia/Shanghai")

    class _FixedDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 6, 10, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(timeline, "datetime", _FixedDT)
    r = auth_client.post("/api/hot/to-direction", json={"keyword": "时区热点词"})
    assert r.status_code == 201
    from app.models import Direction
    d = db_session.get(Direction, r.json()["direction_id"])
    expires = d.expires_at if d.expires_at.tzinfo else \
        d.expires_at.replace(tzinfo=timezone.utc)
    assert expires == datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)
