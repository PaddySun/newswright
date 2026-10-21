"""BE-8/AC-4 超龄闸：score_round 跳过超龄条目落 EXPIRED 终态 + rescore 豁免。

覆盖（任务书 §五必含用例逐项）：
- 年龄边界两态：1.9d 进（照常打分）/2.1d 出（EXPIRED 行+不再选取）；
- EXPIRED 行落账：status=EXPIRED + error 机器可读归因（「超 {n} 天跳过打分」）；
- 幂等：已有 EXPIRED 行不重写（批量场景一次性落账，不逐轮累积）；
- rescore 豁免：超龄条目经 rescore 任务照打（明确意图，D7 站长显式裁定）；
- expired_skipped 计数；site_config score_expire_days 覆写与 0=关闸。

时间纪律：fetched_at 显式注入控龄；预筛直通桩（本文件只验年龄闸，
预筛三路行为见 test_jev_prefilter.py）。
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Direction, Item, PipelineTask, ScoreResult, Source
from app.pipeline.runner import process_rescore_tasks, score_round


@pytest.fixture(autouse=True)
def _prefilter_passthrough(monkeypatch):
    """预筛直通（KEEP 高置信）——年龄闸行为的受控面。"""
    monkeypatch.setattr(
        "app.scoring.prefilter.jev_prefilter",
        lambda db, item, direction: {"verdict": "KEEP", "confidence": 0.99,
                                     "reason": "stub"})


@pytest.fixture(autouse=True)
def clean_resolve():
    """选源层进程态复位（BE-2 判例）。"""
    from app.providers import resolve as resolve_mod

    resolve_mod._reset_for_tests()
    yield resolve_mod
    resolve_mod._reset_for_tests()


def _route_stubs(monkeypatch):
    monkeypatch.setattr("app.retrieval.embedder.ensure_item_vectors",
                        lambda db, its, **kw: None)
    monkeypatch.setattr("app.retrieval.query.ensure_direction_query_vec",
                        lambda db, direction, **kw: False)


def _mk(db, ages_hours: list[float]):
    """方向+源+控龄条目组（fetched_at 显式注入）。"""
    d = Direction(name="超龄闸方向", prompt="p", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url="https://example.com/rss")
    db.add(src)
    db.commit()
    now = datetime.now(timezone.utc)
    items = []
    for i, h in enumerate(ages_hours):
        it = Item(source_id=src.id, guid=f"g{i}", url=f"https://example.com/{i}",
                  title=f"t{i}", content_text="正文" * 50, fetch_status="FETCHED",
                  direction_id=d.id, sanitize_status="PASSED",
                  fetched_at=now - timedelta(hours=h))
        db.add(it)
        items.append(it)
    db.commit()
    return d, items


def _score_recorder(calls: list[int]):
    def fake_score(db, item, direction, *, model=None, provider_name=None):
        calls.append(item.id)
        sr = ScoreResult(item_id=item.id, direction_id=direction.id,
                         model="m", status="OK", passed=True,
                         relevance_score=80, quality_score=80, band="high")
        db.add(sr)
        db.commit()
        return sr
    return fake_score


def test_age_boundary_fresh_in_stale_out(db_session, monkeypatch):
    """1.9d 进（打分）/2.1d 出（EXPIRED 行：归因+不再选取）；expired_skipped=1。"""
    d, items = _mk(db_session, ages_hours=[45.6, 50.4])
    fresh, stale = items
    _route_stubs(monkeypatch)
    calls: list[int] = []
    monkeypatch.setattr("app.scoring.service.score_item", _score_recorder(calls))

    summary = score_round(db_session, triggered_by="test")
    assert calls == [fresh.id]
    row = (db_session.query(ScoreResult)
           .filter_by(item_id=stale.id, direction_id=d.id).one())
    assert row.status == "EXPIRED"
    assert "expired:" in (row.error or "")
    assert "超 2 天跳过打分" in (row.error or "")
    assert row.model  # NOT NULL 列有归因值
    assert summary["directions"][0]["expired_skipped"] == 1
    # 超龄条目下轮不再选取（EXPIRED 幂等）
    summary2 = score_round(db_session, triggered_by="test")
    assert calls == [fresh.id]
    assert summary2["directions"][0]["expired_skipped"] == 0
    count = (db_session.query(ScoreResult)
             .filter_by(item_id=stale.id, status="EXPIRED").count())
    assert count == 1  # 不逐轮累积


def test_expired_prefilter_not_invoked_for_stale(db_session, monkeypatch):
    """超龄条目在预筛之前就被闸掉（不烧 jev 调用、不进三路路由）。"""
    d, (stale,) = _mk(db_session, ages_hours=[50.0])
    _route_stubs(monkeypatch)
    prefilter_calls: list[int] = []
    monkeypatch.setattr(
        "app.scoring.prefilter.jev_prefilter",
        lambda db, item, direction: prefilter_calls.append(item.id)
        or {"verdict": "KEEP", "confidence": 0.99, "reason": "stub"})
    monkeypatch.setattr("app.scoring.service.score_item",
                        _score_recorder([]))
    score_round(db_session, triggered_by="test")
    assert prefilter_calls == []


def test_rescore_exempt_from_age_gate(db_session, monkeypatch):
    """rescore 豁免年龄闸：超龄条目（含 FAILED 行）经 rescore 任务照打
    （D7 站长显式裁定——重打分是明确意图）。"""
    d, (stale,) = _mk(db_session, ages_hours=[72.0])
    db_session.add(ScoreResult(item_id=stale.id, direction_id=d.id,
                               model="m", status="FAILED",
                               error="历史失败行"))
    db_session.commit()

    _route_stubs(monkeypatch)
    calls: list[int] = []
    monkeypatch.setattr("app.scoring.service.score_item", _score_recorder(calls))

    # 常规轮：超龄条目被闸（只有 EXPIRED 行，不打分）
    score_round(db_session, triggered_by="test")
    assert calls == []
    # 插 rescore 任务（score_round 入口会先消化 rescore 任务，故后插）
    db_session.add(PipelineTask(kind="rescore", status="PENDING",
                                payload={"direction_id": d.id, "scope": "failed"}))
    db_session.commit()
    # rescore 消化：超龄条目照打
    outs = process_rescore_tasks(db_session)
    assert outs and outs[0]["rescored"] == 1
    assert calls == [stale.id]


def test_expire_days_site_config_override(db_session, monkeypatch):
    """score_expire_days 可调：调大（5 天）后 3 天条目回到闸内照常打分。"""
    from app.siteconfig import set_config

    d, (item3d,) = _mk(db_session, ages_hours=[72.0])
    _route_stubs(monkeypatch)
    calls: list[int] = []
    monkeypatch.setattr("app.scoring.service.score_item", _score_recorder(calls))

    set_config(db_session, "score_expire_days", 5)
    summary = score_round(db_session, triggered_by="test")
    assert calls == [item3d.id]
    assert summary["directions"][0]["expired_skipped"] == 0


def test_expire_days_zero_disables_gate(db_session, monkeypatch):
    """score_expire_days=0（关闸）：超龄条目照常打分、无 EXPIRED 行。"""
    from app.siteconfig import set_config

    d, (item3d,) = _mk(db_session, ages_hours=[72.0])
    _route_stubs(monkeypatch)
    calls: list[int] = []
    monkeypatch.setattr("app.scoring.service.score_item", _score_recorder(calls))

    set_config(db_session, "score_expire_days", 0)
    summary = score_round(db_session, triggered_by="test")
    assert calls == [item3d.id]
    assert summary["directions"][0]["expired_skipped"] == 0
    assert (db_session.query(ScoreResult)
            .filter_by(item_id=item3d.id, status="EXPIRED").count()) == 0
