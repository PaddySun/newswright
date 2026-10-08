"""写作管线 execute 装配契约测试：reading_window 切片、rolling/incubate 模式
装配段配置消费、文章状态落库。

覆盖口径（设计依据见 docs/design-index.md「US-11」「W4」「AC-05.1」）：
- reading_window=(offset, k) 语义 = 取 pairs[offset:offset+k] 窗口（W4 阅读集
  逐字可核的窗口半边）——既有窗口测试为 2 条 pairs 取 (0,1)，切片起点非零时
  窗口长度与起点必须同时成立，故本测试用 3 条条目取 (1,1) 钉「窗口从 offset
  起取 k 条」；
- rolling 模式的逐节长度指引（min//3 与 int(max*0.4)）与【规划】/【已写成的
  正文】装配段、incubate 模式的【你的腹稿】段均为 draft.mode 配置的消费面
  （配置值必须原样进入提示词，C3-1 配置消费判例族同型）；
- 门禁通过的文章以 PUBLISHED_TO_C 状态落库（非空列完整性，AC-05.1 账目域）。

网络纪律：FakeProviderPipeline 脚本化输出，不真联网；生产代码零改动。
"""
import json

import pytest

import app.authors.pipeline as pl
import app.authors.writer as wr
from app.authors.importer import import_author_json
from app.authors.schema import default_author_config
from app.models import Article, Direction, Item, ScoreResult
from datetime import datetime


@pytest.fixture()
def three_items(db_session):
    """1 方向 + 3 条 passed 条目：窗口切片语义（起点非零）的被测面。"""
    db = db_session
    db.add(Direction(id=1, name="窗口方向", prompt="方向提示词P", threshold=60))
    db.commit()
    items = []
    for i in (1, 2, 3):
        it = Item(source_id=1, guid=f"w{i}", title=f"窗口条目{i}",
                  content_text=f"事实{i}：这是第{i}条目的正文内容。",
                  published_at=datetime(2026, 10, i, 8, 0, 0),
                  url=f"https://w.example/{i}")
        db.add(it)
        db.flush()
        db.add(ScoreResult(item_id=it.id, direction_id=1, quality_score=90,
                           relevance_score=90, band="high", reason="r",
                           prompt_version=1, model="m", passed=True,
                           status="OK"))
        items.append(it)
    db.commit()
    return db, items


def _cfg(db):
    cfg = default_author_config("c6_exec", "装配契约作者")
    cfg["route"]["gates"]["length"] = {"min": 20, "max": 5000, "unit": "chars"}
    cfg["route"]["gates"]["citation"] = {"min_count": 1}
    return cfg


def _draft(iid, item_quote, marker="装配契约成文"):
    """成文脚本：脚注引用逐字摘自阅读集条目正文（引用门禁的校验面）。"""
    body = "他说要写一篇文章，事实已经核对清楚，语句足够长以通过长度门禁。" * 3
    return (f"# {marker}\n\n{body}[^1]\n\n"
            f"[^1]: [条目 {iid}] {item_quote}\n")


class FakeProviderPipeline:
    def __init__(self, scripts):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.calls = []
        self.last_usage = {"prompt_tokens": 10, "completion_tokens": 20}
        self.fallback_note = None
        self.reasoner_available = None

    def chat(self, messages, *, call_point, model=None, **kw):
        self.calls.append({"call_point": call_point, "messages": messages, **kw})
        return self.scripts[call_point].pop(0), "fake-model"


def _outline_json():
    return json.dumps({"title": "滚动规划标题", "thesis": "一句论点",
                       "sections": [{"key": "起", "brief": "要点一"},
                                    {"key": "承", "brief": "要点二"},
                                    {"key": "合", "brief": "要点三"}]},
                      ensure_ascii=False)


def test_reading_window_slice_offset_and_length(three_items, monkeypatch):
    """reading_window=(1,1)：窗口=第 2 条（起点 1、长度 1 同时成立）。"""
    db, items = three_items
    author = import_author_json(db, _cfg(db), model="test-model",
                                readable_directions=[{"direction_id": 1, "threshold": 60}])
    fake = FakeProviderPipeline({"w_draft": [_draft(items[1].id, "这是第2条目的正文内容")]})
    monkeypatch.setattr(pl, "DeepSeekProvider", lambda _db: fake)
    run = wr.run_write(db, author, triggered_by="test", reading_window=(1, 1))
    assert run.status == "OK" and run.decision == "WRITE"
    snap = run.prompt_snapshot
    assert f"【条目 {items[1].id}】" in snap
    assert f"【条目 {items[0].id}】" not in snap
    assert f"【条目 {items[2].id}】" not in snap


def test_rolling_prompt_carries_plan_and_previous_sections(three_items, monkeypatch):
    """rolling 逐节装配：【规划】段与【已写成的正文（衔接，勿重复）】段。"""
    db, items = three_items
    cfg = _cfg(db)
    cfg["route"]["outline"]["template"] = "pyramid"
    cfg["route"]["draft"]["mode"] = "rolling"
    author = import_author_json(db, cfg, model="test-model",
                                readable_directions=[{"direction_id": 1, "threshold": 60}])
    fake = FakeProviderPipeline({
        "w_outline": [_outline_json()],
        "w_draft": [_draft(items[0].id, "这是第1条目的正文内容", "滚动一"),
                    _draft(items[1].id, "这是第2条目的正文内容", "滚动二"),
                    _draft(items[2].id, "这是第3条目的正文内容", "滚动三")],
    })
    monkeypatch.setattr(pl, "DeepSeekProvider", lambda _db: fake)
    run = wr.run_write(db, author, triggered_by="test")
    assert run.status == "OK", run.error
    draft_prompts = [c["messages"][-1]["content"] for c in fake.calls
                     if c["call_point"] == "w_draft"]
    assert "【规划】" in draft_prompts[0] and "第1/3节" in draft_prompts[0]
    assert "【已写成的正文（衔接，勿重复）】" in draft_prompts[1] and "第2/3节" in draft_prompts[1]
    assert "滚动一" in draft_prompts[1]  # 上一节成文进入衔接段


def test_incubate_mode_feeds_incubation_into_draft(three_items, monkeypatch):
    """incubate 模式：腹稿 JSON 进入落笔调用的【你的腹稿】段。"""
    db, items = three_items
    cfg = _cfg(db)
    cfg["route"]["draft"]["mode"] = "incubate"
    author = import_author_json(db, cfg, model="test-model",
                                readable_directions=[{"direction_id": 1, "threshold": 60}])
    incubation = json.dumps({"theme": "腹稿主题句", "chain": ["追问一"],
                             "opening_image": "起笔小事",
                             "closing_line": "收束句"},
                            ensure_ascii=False)
    fake = FakeProviderPipeline({
        "w_incubate": [incubation],
        "w_draft": [_draft(items[0].id, "这是第1条目的正文内容")],
    })
    monkeypatch.setattr(pl, "DeepSeekProvider", lambda _db: fake)
    run = wr.run_write(db, author, triggered_by="test")
    assert run.status == "OK", run.error
    draft_prompt = [c["messages"][-1]["content"] for c in fake.calls
                    if c["call_point"] == "w_draft"][0]
    assert "【你的腹稿（照此落笔，可微调）】" in draft_prompt and "腹稿主题句" in draft_prompt


def test_published_article_lands_with_status(three_items, monkeypatch):
    """门禁通过的文章以 PUBLISHED_TO_C 状态落库、run 转 OK（非空列完整性）。"""
    db, items = three_items
    author = import_author_json(db, _cfg(db), model="test-model",
                                readable_directions=[{"direction_id": 1, "threshold": 60}])
    fake = FakeProviderPipeline({"w_draft": [_draft(items[0].id, "这是第1条目的正文内容")]})
    monkeypatch.setattr(pl, "DeepSeekProvider", lambda _db: fake)
    run = wr.run_write(db, author, triggered_by="test")
    assert run.status == "OK" and run.decision == "WRITE"
    article = db.get(Article, run.article_id)
    assert article is not None and article.status == "PUBLISHED_TO_C"
