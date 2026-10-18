"""旧直路写作终态与引用违规标记契约（run_write 无 author_json 分支——
作者 W0 面回归族分诊补面）。

覆盖三面：选源返回 None（全部候选冷却）时 write_run 落 FAILED 终态且
错误原因落库（可诊断性——与方向打分终态契约同构）；引用违规后重试
通过的复位语义（重试成功即不带标记——标记只属于「耗尽后仍违规」的
输出）；write 决策产出文章入 C 流（status 为 models 声明的
PUBLISHED_TO_C 唯一值，NOT NULL 列无空值形态）。
设计依据见 docs/design-index.md「LR-3」「DT-4」「AC-11.3」。
"""
from app.models import Author, Article, Item, ScoreResult


def _mk_author_with_reading_set(db):
    """造无 author_json 的作者+两条过筛条目（旧直路 run_write 判据面，
    与既有引用校验测试同形态）。"""
    a = Author(name="c5-5 直路作者", model="m",
               readable_directions=[{"direction_id": 1, "threshold": 60}])
    i1 = Item(source_id=1, guid="g-c55-1", title="t1",
              content_text="DeepSeek 发布了新模型，速度提升两倍。")
    db.add_all([a, i1])
    db.commit()
    db.add(ScoreResult(item_id=i1.id, direction_id=1, quality_score=80,
                       relevance_score=80, band="high", reason="r",
                       prompt_version="v1", model="m", passed=True, status="OK"))
    db.commit()
    return a, i1


def test_no_provider_degrades_to_failed_terminal(db_session, monkeypatch):
    """选源返回 None（候选全部冷却）：write_run 落 FAILED 终态且错误原因
    落库（终态二值域不落空值；错误原因可查——消费方走各自既有降级链）。"""
    from app.authors import writer as wr

    a, _ = _mk_author_with_reading_set(db_session)
    monkeypatch.setattr(wr, "resolve_chat", lambda _db: None)
    run = wr.run_write(db_session, a, triggered_by="test")
    assert run.status == "FAILED"
    assert run.error  # 错误原因落库（非空——可诊断性）


def test_violation_then_corrected_retry_leaves_no_flag(db_session, monkeypatch):
    """引用违规重试通过即复位：首答违规（拒收并附说明重试一次）、次答
    合规 → 入库文章不带引用违规标记（标记只属于耗尽后仍违规的输出）。"""
    from app.authors import writer as wr

    a, i1 = _mk_author_with_reading_set(db_session)
    bad = {"decision": "write", "article": {
        "title": "首答违规", "body": "正文。",
        "citations": [{"item_id": i1.id, "quote": "这句不在正文里"}]},
        "reason": "r", "thinking": "t"}
    good = {"decision": "write", "article": {
        "title": "次答合规", "body": "正文。",
        "citations": [{"item_id": i1.id, "quote": "DeepSeek 发布了新模型，速度提升两倍。"}]},
        "reason": "r", "thinking": "t"}

    class FakeTwoAnswer:
        def __init__(self):
            self.n = 0

        def chat_json(self, messages, **kw):
            self.n += 1
            return (bad, "m") if self.n == 1 else (good, "m")

    monkeypatch.setattr(wr, "resolve_chat", lambda _db: FakeTwoAnswer())
    run = wr.run_write(db_session, a, triggered_by="test")
    assert run.status == "OK" and run.decision == "WRITE"
    article = db_session.get(Article, run.article_id)
    assert article is not None
    assert article.citation_violated is False


def test_written_article_enters_c_flow_status(db_session, monkeypatch):
    """write 决策产出文章入 C 流：status 落 models 声明的唯一发布值
    PUBLISHED_TO_C（NOT NULL 列，空值即落库失败——文章入 C 流的库内
    形态）。"""
    from app.authors import writer as wr

    a, i1 = _mk_author_with_reading_set(db_session)
    good = {"decision": "write", "article": {
        "title": "C 流文章", "body": "正文。",
        "citations": [{"item_id": i1.id, "quote": "DeepSeek 发布了新模型，速度提升两倍。"}]},
        "reason": "r", "thinking": "t"}

    class FakeOneAnswer:
        def chat_json(self, messages, **kw):
            return good, "m"

    monkeypatch.setattr(wr, "resolve_chat", lambda _db: FakeOneAnswer())
    run = wr.run_write(db_session, a, triggered_by="test")
    assert run.status == "OK" and run.decision == "WRITE"
    article = db_session.get(Article, run.article_id)
    assert article is not None
    assert article.status == "PUBLISHED_TO_C"
