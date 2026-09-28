"""M10 测试：热榜聚合——全量落库、关键词提炼、降级（API 不可达如实 FAILED）。"""
import app.hot.service as hot_service
from app.models import HotBatch, HotTopic, PipelineTask


WEIBO_ITEMS = [{"title": f"微博热点{i}", "url": f"https://weibo.com/{i}",
                "extra": {"info": f"{10000 - i}热度"}} for i in range(1, 26)]
ZHIHU_ITEMS = [{"title": f"知乎问题{i}", "url": f"https://zhihu.com/q/{i}", "extra": None}
               for i in range(1, 21)]


def _fake_fetch(monkeypatch, mapping):
    monkeypatch.setattr(hot_service, "fetch_platform", lambda p, **kw: mapping[p])
    monkeypatch.setattr(hot_service.time, "sleep", lambda s: None)


def test_hot_round_full_store_and_keywords(db_session, monkeypatch):
    _fake_fetch(monkeypatch, {"weibo": WEIBO_ITEMS, "zhihu": ZHIHU_ITEMS})

    def fake_extract(db, topics):
        assert len(topics) == 20 + 20  # 每平台前 20 条进提炼（keyword_contrib）
        assert any(t.platform == "weibo" for t in topics)
        return ["关键词A", "关键词B"], "今日风向综述", "deepseek-flash"

    monkeypatch.setattr(hot_service, "_extract_keywords", fake_extract)

    out = hot_service.run_hot_round(db_session, triggered_by="test")
    assert out["status"] == "DONE"
    assert out["topics_stored"] == 45  # 全量：25+20
    assert out["keywords"] == ["关键词A", "关键词B"]

    batch = db_session.query(HotBatch).one()
    assert batch.date and batch.keywords == ["关键词A", "关键词B"]
    assert batch.summary == "今日风向综述"
    assert sorted(batch.source_platforms) == ["weibo", "zhihu"]
    assert batch.model == "deepseek-flash"

    assert db_session.query(HotTopic).count() == 45
    # 覆盖式 batch 语义：每平台 rank 从 1 连续
    top_weibo = db_session.query(HotTopic).filter_by(platform="weibo", rank=1).one()
    assert top_weibo.title == "微博热点1" and top_weibo.keyword_contrib is True
    # 第 21 条之后不进提炼输入
    tail = db_session.query(HotTopic).filter_by(platform="weibo", rank=25).one()
    assert tail.keyword_contrib is False

    task = db_session.get(PipelineTask, out["task_id"])
    assert task.status == "DONE" and task.payload["stats"]["topics_stored"] == 45


def test_hot_round_partial_platform_failure(db_session, monkeypatch):
    """单平台失败不中断整轮；成功平台照常落库。"""
    def flaky(p, **kw):
        if p == "zhihu":
            return ZHIHU_ITEMS
        raise RuntimeError("api down")

    monkeypatch.setattr(hot_service, "fetch_platform", flaky)
    monkeypatch.setattr(hot_service.time, "sleep", lambda s: None)

    def fake_extract(db, topics):
        return ["k"], "s", "m"
    monkeypatch.setattr(hot_service, "_extract_keywords", fake_extract)

    out = hot_service.run_hot_round(db_session, triggered_by="test")
    assert out["status"] == "DONE"
    assert out["topics_stored"] == 20
    stats = out["platforms"]
    assert [s["ok"] for s in stats] == [False, True, False, False, False]


def test_hot_round_all_platforms_failed_no_mock(db_session, monkeypatch):
    """聚合 API 全不可达：FAILED 如实呈现，不 mock 数据。"""
    def down(p, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(hot_service, "fetch_platform", down)
    monkeypatch.setattr(hot_service.time, "sleep", lambda s: None)

    out = hot_service.run_hot_round(db_session, triggered_by="test")
    assert out["status"] == "FAILED"
    assert db_session.query(HotBatch).count() == 0
    assert db_session.query(HotTopic).count() == 0
    task = db_session.get(PipelineTask, out["task_id"])
    assert task.status == "FAILED" and "全部平台拉取失败" in (task.last_error or "")


def test_hot_round_anti_overlap(db_session, monkeypatch):
    _fake_fetch(monkeypatch, {"weibo": WEIBO_ITEMS})
    monkeypatch.setattr(hot_service, "_extract_keywords", lambda db, t: (["k"], "s", "m"))
    hot_service.run_hot_round(db_session, triggered_by="test")
    # 上一轮已 DONE，不阻塞
    out2 = hot_service.run_hot_round(db_session, triggered_by="test")
    assert out2.get("skipped") != True or out2["status"] == "DONE"
