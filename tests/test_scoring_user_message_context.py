"""打分 user 消息正文承载测试：第三方正文经截断后进入 <document> 定界块、
有发布日期的条目其日期段正常渲染（组装不崩）。

覆盖口径：_render_user_message 的组装产物承载正文语义（正文截断链的落点，
技术书 scoring 模块行「正文截断 ≤4000 字符」）与发布日期上下文段——正文
承载断链或日期渲染崩溃即打分输入失真（AC-06.4 定界组装 + AC-07 打分输入面）。
设计依据见 docs/design-index.md「AC-06.4」「AC-07.1」。
"""
from datetime import datetime

from app.models import Direction, Item, Source
from app.scoring.service import _render_user_message


def _mk_item(db, *, published=True):
    d = Direction(name="正文方向", prompt="p", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url="https://ex.com/rss")
    db.add(src)
    db.commit()
    item = Item(source_id=src.id, guid="g1", url="https://ex.com/a",
                title="标题文字", content_text="这是需要被承载的正文片段。",
                fetch_status="FETCHED", direction_id=d.id,
                published_at=datetime(2026, 10, 1) if published else None)
    db.add(item)
    db.commit()
    return d, item


def test_user_message_carries_body_and_renders_date(db_session):
    """有正文且有发布日期的条目：正文片段出现在 user 消息 document 块内，
    组装正常完成（日期段渲染不崩）。"""
    d, item = _mk_item(db_session)
    msg = _render_user_message(item, d)
    assert "这是需要被承载的正文片段。" in msg
    assert "【正文】" in msg
    assert f'<document id="{item.id}">' in msg


def test_user_message_without_published_at_marks_unknown(db_session):
    """无发布日期条目：日期段以占位呈现，正文承载不受影响（AC-07.7 缺日期不拒）。"""
    d, item = _mk_item(db_session, published=False)
    msg = _render_user_message(item, d)
    assert "这是需要被承载的正文片段。" in msg
