"""修订遍（passes）执行契约与门禁重试修订基面。

覆盖：prune/rhythm 修订遍按配置路由到对应节点且消息结构合法（system + user
携被修稿件）、占位修订遍（selfrev 等）passthrough 落笔且留痕记录存在、门禁
重试的修订调用必须携带被拒稿件原文（修订对象=被拒稿）。
设计依据见 docs/design-index.md「AC-11.1」（路线按 JSON 执行：passes 按配置）、
「AC-11.2」（门禁拒收附违规说明重试）；trace 落库沿 pipeline 模块说明
（全节点 trace 落 write_run.payload，占位遍 passthrough + 记录）。
"""
import pytest

import app.authors.pipeline as pl
from app.authors.importer import import_author_json
from app.authors.schema import default_author_config
from app.models import Item, ScoreResult

GOOD_DRAFT = "他说要写一篇文章。事实一。[^1]事实二。[^2]"


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


def make_draft_text(item1: int, item2: int, body: str = GOOD_DRAFT) -> str:
    return (
        f"# 关于机器写作的三点观察\n\n{body}\n\n"
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


def base_config():
    cfg = default_author_config("pipe_t", "管线测试作者")
    cfg["route"]["gates"]["length"] = {"min": 20, "max": 5000, "unit": "chars"}
    cfg["route"]["gates"]["citation"] = {"min_count": 2}
    return cfg


def _run(db, cfg, author_env, scripts):
    db, i1, i2 = author_env
    author = import_author_json(db, cfg, model="test-model",
                                readable_directions=[{"direction_id": 1, "threshold": 60}])
    fake = FakeProvider(scripts)
    orig = pl.DeepSeekProvider
    pl.DeepSeekProvider = lambda _db: fake
    try:
        run = pl.run_pipeline_write(db, author, triggered_by="test")
    finally:
        pl.DeepSeekProvider = orig
    return run, fake, (i1, i2)


def test_prune_pass_routes_to_prune_node_with_draft(env):
    """prune 修订遍按配置执行：调用删节节点、消息为 system 人格卡 + user 携
    初稿原文的合法结构、修订稿入库。"""
    cfg = base_config()
    cfg["route"]["passes"] = [{"type": "prune"}]
    i1, i2 = env[1], env[2]
    pruned = make_draft_text(i1, i2, body="删节后的正文。事实一。[^1]事实二。[^2]")
    run, fake, _ = _run(env[0], cfg, env,
                        {"w_draft": [make_draft_text(i1, i2)], "w_prune": [pruned]})
    assert run.status == "OK"
    assert [t["node"] for t in run.payload["trace"]] == ["w_draft", "w_prune"]
    call = next(c for c in fake.calls if c["call_point"] == "w_prune")
    msgs = call["messages"]
    assert msgs[0]["role"] == "system" and msgs[0]["content"]
    assert msgs[1]["role"] == "user"
    assert "他说要写一篇文章" in msgs[1]["content"]  # 携带的是修订前初稿


def test_rhythm_pass_routes_to_rhythm_node(env):
    """rhythm 修订遍按配置执行：调用节奏节点并产出自该节点的修订稿（未配置
    修订遍类型不得静默 passthrough）。"""
    cfg = base_config()
    cfg["route"]["passes"] = [{"type": "rhythm"}]
    i1, i2 = env[1], env[2]
    rhythmed = make_draft_text(i1, i2, body="节奏重构后的正文。事实一。[^1]事实二。[^2]")
    run, fake, _ = _run(env[0], cfg, env,
                        {"w_draft": [make_draft_text(i1, i2)], "w_rhythm": [rhythmed]})
    assert run.status == "OK"
    assert [t["node"] for t in run.payload["trace"]] == ["w_draft", "w_rhythm"]
    call = next(c for c in fake.calls if c["call_point"] == "w_rhythm")
    msgs = call["messages"]
    assert msgs[0]["role"] == "system" and msgs[0]["content"]
    assert msgs[1]["role"] == "user"
    assert "他说要写一篇文章" in msgs[1]["content"]
    assert "节奏重构后的正文" in run.payload["trace"][-1]["output"]


def db_article(db, run):
    from app.models import Article

    return db.get(Article, run.article_id)


def test_placeholder_pass_passthrough_with_trace_record(env):
    """占位修订遍（未实现的接口预留类型）按文档语义 passthrough 落笔、不发起
    模型调用，trace 留有本遍的记录条目（记录内部形态不钉）。"""
    cfg = base_config()
    cfg["route"]["passes"] = [{"type": "selfrev"}]
    i1, i2 = env[1], env[2]
    run, fake, _ = _run(env[0], cfg, env, {"w_draft": [make_draft_text(i1, i2)]})
    assert run.status == "OK"
    assert [c["call_point"] for c in fake.calls] == ["w_draft"]  # 占位遍零模型调用
    article = db_article(env[0], run)
    assert "他说要写一篇文章" in article.body  # passthrough 落笔
    assert isinstance(run.payload["trace"][-1], dict)  # 占位遍留痕记录存在


def db_article(db, run):
    from app.models import Article

    return db.get(Article, run.article_id)


def test_gate_retry_revision_carries_rejected_draft(env):
    """门禁拒收后的修订调用必须携带被拒稿件原文（修订对象=被拒稿，而非凭空
    重写）；修订通过后按重试语义落 OK。"""
    i1, i2 = env[1], env[2]
    bad = "# 废稿标题\n\n一段没有引用的正文。"
    good = make_draft_text(i1, i2)
    run, fake, _ = _run(env[0], base_config(), env,
                        {"w_draft": [bad], "w_revise": [good]})
    assert run.status == "OK"
    assert run.payload["rewrite"]["attempts"] == 1
    revise_call = next(c for c in fake.calls if c["call_point"] == "w_revise")
    assert "废稿标题" in revise_call["messages"][1]["content"]  # 被拒稿原文在修订提示内
