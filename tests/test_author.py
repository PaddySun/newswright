"""M5 单元测试：引用硬校验（子串命中/空白归一化/越界 ID）+ 记忆占位符填充。"""
import pytest

from app.authors.writer import CitationError, _validate_citations
from app.models import Author, Item, ScoreResult


@pytest.fixture()
def author_items(db_session):
    a = Author(name="测试作者", model="m", readable_directions=[{"direction_id": 1, "threshold": 60}])
    i1 = Item(source_id=1, guid="g1", title="t1", content_text="DeepSeek 发布了新模型，速度提升两倍。")
    i2 = Item(source_id=1, guid="g2", title="t2", content_text="第二篇文章内容。")
    db_session.add_all([a, i1, i2])
    db_session.commit()
    db_session.add_all([
        ScoreResult(item_id=i1.id, direction_id=1, quality_score=80, relevance_score=80,
                    band="high", reason="r", prompt_version="v1", model="m", passed=True, status="OK"),
        ScoreResult(item_id=i2.id, direction_id=1, quality_score=70, relevance_score=70,
                    band="high", reason="r", prompt_version="v1", model="m", passed=True, status="OK"),
    ])
    db_session.commit()
    return a, i1, i2


def test_citation_ok(db_session, author_items):
    _, i1, i2 = author_items
    data = {"article": {"citations": [
        {"item_id": i1.id, "quote": "DeepSeek 发布了新模型，速度提升两倍。"},
        {"item_id": i2.id, "quote": "第二篇文章\n 内容。"},  # 空白差异应归一化后命中
    ]}}
    pairs = [(db_session.get(Item, i1.id), None), (db_session.get(Item, i2.id), None)]
    _validate_citations(data, pairs)  # 不抛即通过


def test_citation_quote_not_found(db_session, author_items):
    _, i1, _ = author_items
    data = {"article": {"citations": [{"item_id": i1.id, "quote": "这句话根本不在正文里"}]}}
    pairs = [(db_session.get(Item, i1.id), None)]
    with pytest.raises(CitationError):
        _validate_citations(data, pairs)


def test_citation_id_out_of_reading_set(db_session, author_items):
    data = {"article": {"citations": [{"item_id": 99999, "quote": "任意"}]}}
    with pytest.raises(CitationError):
        _validate_citations(data, [])


def test_citation_empty(db_session, author_items):
    with pytest.raises(CitationError):
        _validate_citations({"article": {"citations": []}}, [])


def test_placeholder_filling(db_session, author_items):
    from app.authors.memory import add_memory, fill_placeholders

    a, _, _ = author_items
    a.memory_config = {"feedback_memory": 5, "topic_memory": 3}
    db_session.commit()
    add_memory(db_session, a, module="feedback", content="读者点赞了《X》", source_event="feedback")
    tpl = "【反馈】{feedback_memory} 【选题】{topic_memory} 【未配置】{style_memory}"
    out = fill_placeholders(db_session, a, tpl)
    assert "读者点赞了《X》" in out
    assert "暂无记录" in out
    assert "{style_memory}" in out
