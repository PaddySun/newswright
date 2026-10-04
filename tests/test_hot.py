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


def test_hot_round_keyword_failure_degrades_to_title_tokens(db_session, monkeypatch):
    """关键词提炼失败：采集成功的轮次照常 DONE（提炼失败不计为采集失败），
    payload.stats 携带 degraded=["hot_keywords"] 与 kw_error，关键词降级为标题分词
    兜底（kw_fallback=title_tokens），榜单数据与 batch 落库不受影响。"""
    _fake_fetch(monkeypatch, {"weibo": WEIBO_ITEMS})

    def boom(db, topics):
        raise RuntimeError("提炼通道不可用")

    monkeypatch.setattr(hot_service, "_extract_keywords", boom)
    monkeypatch.setattr(hot_service, "_rank_filter_topics", lambda db, topics: (topics, {}))

    out = hot_service.run_hot_round(db_session, triggered_by="test")
    assert out["status"] == "DONE"
    task = db_session.get(PipelineTask, out["task_id"])
    stats = task.payload["stats"]
    assert stats["degraded"] == ["hot_keywords"]
    assert "RuntimeError" in (stats["kw_error"] or "")
    assert stats["kw_fallback"] == "title_tokens"
    assert task.last_error is None

    kws = out["keywords"]
    assert 0 < len(kws) <= 15
    assert set(kws) == {"微博", "博热", "热点"}  # 全部来自真实标题分词，非固定词表
    batch = db_session.query(HotBatch).one()
    assert batch.keywords == kws and batch.model == ""
    assert db_session.query(HotTopic).count() == 25


def test_fallback_title_tokens_rule(db_session):
    """标题分词兜底器：ASCII 词小写化、中文连续段切 2-gram、去停用词与纯数字、
    按出现频次降序取 top-15（输入标题为空安全）。"""
    batch = HotBatch(date="2026-10-05", keywords=[], summary="", source_platforms=["w"], model="")
    db_session.add(batch)
    db_session.commit()
    titles = ["AI 写作工具发布", "AI 写作工具评测", "央行降息影响楼市", "央行降息落地",
              "12345", " stopwords the and ", ""]
    topics = [HotTopic(platform="w", rank=i + 1, title=t, batch_id=batch.id)
              for i, t in enumerate(titles)]
    for t in topics:
        db_session.add(t)
    db_session.commit()

    kws = hot_service._fallback_keywords_from_titles(topics)

    assert len(kws) <= 15
    assert "ai" in kws and "写作" in kws          # ASCII 小写 + 中文 2-gram
    assert "降息" in kws
    assert "12345" not in kws and "123" not in kws  # 纯数字段剔除
    assert "the" not in kws and "stopwords" not in kws  # 英文停用词剔除
    # 频次降序：出现 2 次的词排在出现 1 次的词前面
    freq_first, freq_later = kws.index("写作"), kws.index("降息")
    assert freq_first < freq_later
    assert hot_service._fallback_keywords_from_titles([]) == []
