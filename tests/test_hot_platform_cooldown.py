"""hot 平台连败冷却测试（BE-6/AC-1，R3.7）：HotCallLog 回读判定 + run_hot_round
挂点（冷却跳过/全冷却 DONE 不建 batch/部分冷却其余照抓）。

判定口径（HG-1）：该 platform 最近 HOT_COOLDOWN_STREAK=3 行全 ok=False 且最新
一行距 now < HOT_COOLDOWN_MINUTES=30 分钟 → 冷却中；行数不足/夹成功/超窗 → 否。
纯 DB 判定零新状态；判定键=platform（fetch_platform 失败行=全候选皆败）。

时间纪律：纯函数注入 now；run_hot_round 挂点测试用近窗口行（now-60s）零真等。
设计依据见 docs/design-index.md「HG-1」。
"""
from datetime import datetime, timedelta, timezone

import app.config as app_config
import app.hot.service as hot_service
from app.models import HotBatch, HotCallLog, HotTopic, PipelineTask

NOW = datetime.now(timezone.utc)


def _log(db, platform: str, *, ok: bool, fetched_at: datetime) -> None:
    """直插一行终态账（fetched_at 显式——冷却窗口判据的受控面）。"""
    db.add(HotCallLog(provider="https://agg.example", platform=platform, ok=ok,
                      status="200" if ok else "RetryExhausted", latency_ms=10,
                      error=None if ok else "聚合 API 全候选失败",
                      fetched_at=fetched_at))
    db.commit()


# ---------- 纯函数判定（platform_in_cooldown） ----------

def test_three_recent_failures_in_cooldown(db_session):
    """3 连败且最新失败在窗口内 → True（冷却）。"""
    for i in range(3):
        _log(db_session, "weibo", ok=False, fetched_at=NOW - timedelta(minutes=3 - i))
    assert hot_service.platform_in_cooldown(db_session, "weibo", now=NOW) is True


def test_fewer_than_streak_rows_not_in_cooldown(db_session):
    """行数不足 3 行（无历史不罚）→ False。"""
    _log(db_session, "weibo", ok=False, fetched_at=NOW - timedelta(minutes=1))
    _log(db_session, "weibo", ok=False, fetched_at=NOW - timedelta(seconds=30))
    assert hot_service.platform_in_cooldown(db_session, "weibo", now=NOW) is False


def test_no_history_not_in_cooldown(db_session):
    """零历史 → False（新平台不罚）。"""
    assert hot_service.platform_in_cooldown(db_session, "weibo", now=NOW) is False


def test_success_breaks_streak(db_session):
    """最近 3 行夹一次成功 → False（一次成功断连败）。"""
    _log(db_session, "weibo", ok=False, fetched_at=NOW - timedelta(minutes=3))
    _log(db_session, "weibo", ok=True, fetched_at=NOW - timedelta(minutes=2))
    _log(db_session, "weibo", ok=False, fetched_at=NOW - timedelta(minutes=1))
    assert hot_service.platform_in_cooldown(db_session, "weibo", now=NOW) is False


def test_latest_failure_beyond_window_not_in_cooldown(db_session):
    """3 连败但最新失败距 now ≥ 30min → False（冷却期满自然重试，注入 now）。"""
    for i in range(3):
        _log(db_session, "weibo", ok=False,
             fetched_at=NOW - timedelta(minutes=31, seconds=30 - i * 10))
    assert hot_service.platform_in_cooldown(db_session, "weibo", now=NOW) is False


def test_judgement_keyed_by_platform(db_session):
    """判定键=platform：weibo 的连败账不波及 zhihu。"""
    for i in range(3):
        _log(db_session, "weibo", ok=False, fetched_at=NOW - timedelta(minutes=3 - i))
    assert hot_service.platform_in_cooldown(db_session, "zhihu", now=NOW) is False


def test_window_boundary_exactly_30min_still_cooldown(db_session):
    """最新失败恰距 now 30min 边界（< 窗口才冷却，30min 整已期满）→ False。"""
    for i in range(3):
        _log(db_session, "weibo", ok=False,
             fetched_at=NOW - timedelta(minutes=30, seconds=i))
    assert hot_service.platform_in_cooldown(db_session, "weibo", now=NOW) is False


# ---------- run_hot_round 挂点 ----------

def _fake_round_env(monkeypatch, platforms, mapping=None, fail_all=None):
    """run_hot_round 测试环境：平台清单 + fetch_platform 计数桩（零出网零等待）。"""
    monkeypatch.setattr(app_config, "HOT_PLATFORMS", platforms)
    calls: list[str] = []

    def fake_fetch(p, **kw):
        calls.append(p)
        if fail_all and p in fail_all:
            raise RuntimeError("api down")
        return (mapping or {}).get(p, [{"title": f"条目-{p}", "url": "https://x/1"}])

    monkeypatch.setattr(hot_service, "fetch_platform", fake_fetch)
    monkeypatch.setattr(hot_service.time, "sleep", lambda s: None)
    monkeypatch.setattr(hot_service, "_extract_keywords",
                        lambda db, topics: (["k"], "s", "m"))
    monkeypatch.setattr(hot_service, "_rank_filter_topics",
                        lambda db, topics: (topics, {}))
    return calls


def test_all_platforms_cooldown_done_no_batch(db_session, monkeypatch):
    """全平台皆冷却：DONE 早退（不建 batch 非 FAILED——冷却中无采集是合法稳态），
    stats 含 skipped_cooldown 清单，冷却平台零 fetch_platform 调用。"""
    calls = _fake_round_env(monkeypatch, ["weibo", "zhihu"])
    for p in ("weibo", "zhihu"):
        for i in range(3):
            _log(db_session, p, ok=False, fetched_at=NOW - timedelta(minutes=3 - i))

    out = hot_service.run_hot_round(db_session, triggered_by="test")
    assert out["status"] == "DONE"
    assert calls == []  # 冷却平台零 fetch_platform 调用（计数桩）
    assert db_session.query(HotBatch).count() == 0
    assert db_session.query(HotTopic).count() == 0
    assert sorted(out["skipped_cooldown"]) == ["weibo", "zhihu"]
    task = db_session.get(PipelineTask, out["task_id"])
    assert task.status == "DONE" and task.last_error is None
    assert sorted(task.payload["stats"]["skipped_cooldown"]) == ["weibo", "zhihu"]


def test_partial_cooldown_rest_fetched(db_session, monkeypatch):
    """部分冷却其余照抓：weibo 冷却跳过、zhihu 照抓落库；platform_stats 含
    skipped_cooldown 条目。"""
    calls = _fake_round_env(
        monkeypatch, ["weibo", "zhihu"],
        mapping={"zhihu": [{"title": "知乎条目", "url": "https://z/1"}]})
    for i in range(3):
        _log(db_session, "weibo", ok=False, fetched_at=NOW - timedelta(minutes=3 - i))

    out = hot_service.run_hot_round(db_session, triggered_by="test")
    assert out["status"] == "DONE"
    assert calls == ["zhihu"]  # 仅未冷却平台被取用
    assert out["topics_stored"] == 1
    by_platform = {s["platform"]: s for s in out["platforms"]}
    assert by_platform["weibo"].get("skipped_cooldown") is True
    assert by_platform["zhihu"]["ok"] is True


def test_cooldown_with_rest_failed_is_real_failure(db_session, monkeypatch):
    """部分冷却 + 其余真失败：不是全冷却稳态 → 仍走 FAILED 早退（分态）。"""
    calls = _fake_round_env(monkeypatch, ["weibo", "zhihu"], fail_all={"zhihu"})
    for i in range(3):
        _log(db_session, "weibo", ok=False, fetched_at=NOW - timedelta(minutes=3 - i))

    out = hot_service.run_hot_round(db_session, triggered_by="test")
    assert out["status"] == "FAILED"
    assert calls == ["zhihu"]
    assert db_session.query(HotBatch).count() == 0


def test_no_cooldown_history_round_unchanged(db_session, monkeypatch):
    """零历史（无冷却）轮次行为零变：平台照抓、stats 无 skipped_cooldown 键。"""
    calls = _fake_round_env(monkeypatch, ["weibo", "zhihu"])
    out = hot_service.run_hot_round(db_session, triggered_by="test")
    assert out["status"] == "DONE"
    assert calls == ["weibo", "zhihu"]
    assert "skipped_cooldown" not in out
    assert all(s["ok"] for s in out["platforms"])
