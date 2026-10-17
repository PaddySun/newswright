"""方向打分终态契约（scoring.service.score_item）：AC-07 补面。

两面（产品书 AC-07.1 / AC-07.3 与降级条款）：
- 成功路径 score_result 落 status="OK"（终态域 OK/FAILED 二值——OK 不得
  落空值，score_round 的幂等跳过口径「OK 绝不重打」依赖该值）；
- 选源返回 None（全部候选冷却）时逐条记 status="FAILED" 且错误原因落库
  （内容不丢、错误原因可查——任务可诊断性）。
设计依据见《产品设计书-正式-TDD》AC-07.1 / AC-07.3 与「错误原因落库」
降级条款（§US-09 方向打分）；docs/design-index.md「LR-3」（消费方走
各自既有降级链）。
"""
from app.models import Direction, Item, Source
from app.scoring.service import score_item


def _mk_item_with_direction(db):
    """造一对方向+来源+条目（与既有 scoring 契约测试同形态）。"""
    d = Direction(name="d-c5-2-terminal", prompt="接纳高质量内容",
                  prompt_version=1, threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url="https://ex-c52.example/rss")
    db.add(src)
    db.commit()
    item = Item(source_id=src.id, guid="g-c5-2", url="https://ex-c52.example/a",
                title="某报道", content_text="正文内容足够长。" * 30,
                fetch_status="FETCHED", direction_id=d.id)
    db.add(item)
    db.commit()
    return d, item


def test_score_item_ok_status_on_success(db_session, monkeypatch):
    """成功路径：score_result.status == "OK"（终态二值域——OK 绝不落空，
    下轮 score_round 幂等跳过按此判定）。"""

    class _FakeChat:
        def chat_json(self, messages, **kwargs):
            return {"quality": 88, "relevance": 92, "band": "high",
                    "reason": "一手实测数据"}, "deepseek-flash"

    monkeypatch.setattr("app.scoring.service.resolve_chat",
                        lambda db: _FakeChat())
    direction, item = _mk_item_with_direction(db_session)
    result = score_item(db_session, item, direction)
    assert result.status == "OK"


def test_score_item_failed_carries_reason_when_no_provider(db_session, monkeypatch):
    """选源 None（候选全部冷却）：逐条记 status="FAILED" 且 error 落库
    （错误原因落库——可诊断性；内容不丢，下轮重试）。"""
    monkeypatch.setattr("app.scoring.service.resolve_chat", lambda db: None)
    direction, item = _mk_item_with_direction(db_session)
    result = score_item(db_session, item, direction)
    assert result.status == "FAILED"
    assert result.error  # 错误原因落库（非空）
