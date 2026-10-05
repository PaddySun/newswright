"""JSON 节点（大纲/腹稿）调用契约与解析失败附反馈重试语义。

覆盖：JSON 节点以 JSON 模式调用且消息结构合法（system 人格卡 + user 上下文）、
解析失败后以「assistant 原样稿 + user 修复指令」消息对重发一次且仍走 JSON 模式、
大纲输出缺 sections 时写作轮落 FAILED 而非崩溃。
设计依据见 docs/design-index.md「AC-11.1」（路线按 JSON 执行）、「AC-11.2」
（附违规说明重试）、「DT-4」（失败落 FAILED 废稿留痕）；JSON 节点重试纪律沿
pipeline 模块说明（lab 移植：解析失败附反馈重试一次，再失败如实失败）。
"""
import pytest

import app.authors.pipeline as pl
from app.authors.importer import import_author_json
from app.authors.schema import default_author_config
from app.models import Item, ScoreResult

OUTLINE_OK = ('{"title":"关于机器写作的三点观察","thesis":"机器写作改变生产",'
              '"sections":[{"key":"现象","brief":"b1"},{"key":"机制","brief":"b2"},'
              '{"key":"人","brief":"b3"}]}')
INCUBATE_OK = ('{"theme":"机器写作的核心之事","chain":["一","二","三"],'
               '"opening_image":"深夜的机房","closing_line":"灯还亮着"}')
BAD_JSON = "这不是合法的JSON输出"


class FakeProvider:
    """按 call_point 弹出脚本化输出的假 provider（记录全部调用参数）。"""

    name = "deepseek-fake"

    def __init__(self, scripts: dict[str, list[str]]):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.calls: list[dict] = []
        self.last_usage = {"prompt_tokens": 10, "completion_tokens": 20}
        self.fallback_note = None
        self.reasoner_available = None

    def chat(self, messages, *, call_point, model=None, **kw):
        self.calls.append({"call_point": call_point, "messages": messages, **kw})
        return self.scripts[call_point].pop(0), "fake-model"


def make_draft_text(item1: int, item2: int) -> str:
    return (
        "# 关于机器写作的三点观察\n\n他说要写一篇文章。事实一。[^1]事实二。[^2]\n\n"
        f"[^1]: [条目 {item1}] 事实一\n"
        f"[^2]: [条目 {item2}] 事实二\n"
    )


@pytest.fixture()
def env(db_session):
    """1 方向 + 2 条目（passed）的基础写作环境，返回 (db, 条目 id 二元组)。"""
    from app.models import Direction

    db = db_session
    db.add(Direction(id=1, name="AI 与软件工程", prompt="p", threshold=60))
    i1 = Item(source_id=1, guid="g1", title="AI 写作实验", content_text="事实一：模型写出了完整的文章。")
    i2 = Item(source_id=1, guid="g2", title="软件工程观察", content_text="事实二：代码评审提高了质量。")
    db.add_all([i1, i2])
    db.commit()
    db.add_all([
        ScoreResult(item_id=i1.id, direction_id=1, quality_score=90, relevance_score=90,
                    band="high", reason="r", prompt_version="v1", model="m", passed=True, status="OK"),
        ScoreResult(item_id=i2.id, direction_id=1, quality_score=85, relevance_score=85,
                    band="high", reason="r", prompt_version="v1", model="m", passed=True, status="OK"),
    ])
    db.commit()
    return db, i1.id, i2.id


def _run(db, cfg, scripts):
    author = import_author_json(db, cfg, model="test-model",
                                readable_directions=[{"direction_id": 1, "threshold": 60}])
    fake = FakeProvider(scripts)
    orig = pl.DeepSeekProvider
    pl.DeepSeekProvider = lambda _db: fake
    try:
        run = pl.run_pipeline_write(db, author, triggered_by="test")
    finally:
        pl.DeepSeekProvider = orig
    return run, fake


def base_config():
    cfg = default_author_config("pipe_t", "管线测试作者")
    cfg["route"]["gates"]["length"] = {"min": 20, "max": 5000, "unit": "chars"}
    cfg["route"]["gates"]["citation"] = {"min_count": 2}
    return cfg


def test_outline_json_mode_and_retry_feedback_structure(env):
    """大纲节点两次调用均走 JSON 模式；首调消息为 system 人格卡 + user 上下文
    合法结构；解析失败重试以 assistant 原稿 + user 修复指令消息对重发。"""
    cfg = base_config()
    cfg["route"]["outline"]["template"] = "pyramid"
    run, fake = _run(env[0], cfg,
                     {"w_outline": [BAD_JSON, OUTLINE_OK], "w_draft": [make_draft_text(env[1], env[2])]})
    assert run.status == "OK"
    outline_calls = [c for c in fake.calls if c["call_point"] == "w_outline"]
    assert len(outline_calls) == 2
    assert all(c["json_mode"] is True for c in outline_calls)  # JSON 节点 JSON 模式
    first = outline_calls[0]["messages"]
    assert first[0]["role"] == "system" and first[0]["content"]  # 人格卡稳定段
    assert first[1]["role"] == "user"
    retry = outline_calls[1]["messages"]
    assert len(retry) == 4
    assert retry[2]["role"] == "assistant" and retry[2]["content"] == BAD_JSON  # 原样稿回传
    assert retry[3]["role"] == "user" and "解析失败" in retry[3]["content"]  # 修复指令


def test_incubate_json_mode_and_retry_feedback_structure(env):
    """腹稿节点同受 JSON 模式与附反馈重试契约约束（消息结构合法、原稿回传、
    修复指令附解析失败说明）。"""
    cfg = base_config()
    cfg["route"]["draft"]["mode"] = "incubate"
    run, fake = _run(env[0], cfg,
                     {"w_incubate": [BAD_JSON, INCUBATE_OK], "w_draft": [make_draft_text(env[1], env[2])]})
    assert run.status == "OK"
    inc_calls = [c for c in fake.calls if c["call_point"] == "w_incubate"]
    assert len(inc_calls) == 2
    assert all(c["json_mode"] is True for c in inc_calls)
    first = inc_calls[0]["messages"]
    assert first[0]["role"] == "system" and first[0]["content"]
    assert first[1]["role"] == "user"
    retry = inc_calls[1]["messages"]
    assert len(retry) == 4
    assert retry[2]["role"] == "assistant" and retry[2]["content"] == BAD_JSON
    assert retry[3]["role"] == "user" and "解析失败" in retry[3]["content"]


def test_outline_missing_sections_lands_failed_not_crash(env):
    """大纲输出缺 sections：写作轮按失败留痕落 FAILED（而非未捕获异常崩溃），
    无文章落库。"""
    cfg = base_config()
    cfg["route"]["outline"]["template"] = "pyramid"
    run, _ = _run(env[0], cfg,
                  {"w_outline": ['{"title":"T","thesis":"论点"}'], "w_draft": []})
    assert run.status == "FAILED"
    assert run.article_id is None
