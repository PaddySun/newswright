"""M14 单元测试：管线执行器（假 provider 脚本化输出，不烧钱）。

覆盖：端到端 WRITE（trace/门禁/citations/文章落库）、gated_retry 重试（废稿留痕）、
zero_revision 审计语义、静态切片硬预算注入、copyright 门禁、topic_dedup 门禁、
reasoner 档不可用回退。
"""
import json

import pytest

import app.authors.pipeline as pl
from app.authors.importer import import_author_json
from app.authors.schema import default_author_config
from app.models import Article, Item, ScoreResult, WriteRun
from app.providers.base import ProviderError
from app.providers.deepseek import DeepSeekProvider


class FakeProvider:
    """按 call_point 弹出脚本化输出的假 provider。"""

    name = "deepseek-fake"

    def __init__(self, scripts: dict[str, list[str]]):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.calls: list[dict] = []
        self.last_usage = {"prompt_tokens": 10, "completion_tokens": 20}
        self.fallback_note = None
        self.reasoner_available = None

    def chat(self, messages, *, call_point, model=None, **kw):
        self.calls.append({"call_point": call_point, "messages": messages, **kw})
        out = self.scripts[call_point].pop(0)
        return out, "fake-model"


def make_draft_text(item1: int, item2: int, body: str = "他说要写一篇文章。事实一。[^1]事实二。[^2]"):
    title = "关于机器写作的三点观察"
    return (
        f"# {title}\n\n{body}\n\n"
        f"[^1]: [条目 {item1}] 事实一\n"
        f"[^2]: [条目 {item2}] 事实二\n"
    )


@pytest.fixture()
def env(db_session):
    """1 方向 + 2 条目（passed）+ 无 JSON 的基础环境，返回 (db, cfg模板, item ids)。"""
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


def base_config(name="管线测试作者"):
    cfg = default_author_config("pipe_t", name)
    cfg["route"]["gates"]["length"] = {"min": 20, "max": 5000, "unit": "chars"}
    cfg["route"]["gates"]["citation"] = {"min_count": 2}
    return cfg


def _author(db, cfg, **kw):
    return import_author_json(db, cfg, model="test-model",
                              readable_directions=[{"direction_id": 1, "threshold": 60}], **kw)


def test_pipeline_write_e2e(db_session, env):
    db, i1, i2 = env
    cfg = base_config()
    author = _author(db, cfg)
    fake = FakeProvider({"w_draft": [make_draft_text(i1, i2)]})
    orig = pl.DeepSeekProvider
    pl.DeepSeekProvider = lambda _db: fake
    try:
        run = pl.run_pipeline_write(db, author, triggered_by="test")
    finally:
        pl.DeepSeekProvider = orig
    assert run.status == "OK" and run.decision == "WRITE"
    article = db.get(Article, run.article_id)
    assert article.title.startswith("关于机器写作")
    assert "[^1]: [条目" in article.body  # 脚注定义区已装配
    assert len(article.citations) == 2
    assert article.citations[0]["item_id"] == i1
    # trace 完整：节点名/tokens/输出全文
    trace = run.payload["trace"]
    assert [t["node"] for t in trace] == ["w_draft"]
    assert trace[0]["tokens_out"] == 20 and trace[0]["output"].startswith("#")
    assert run.payload["gates_final"]["passed"] is True
    # prompt 快照含阅读集条目（可核）
    assert f"【条目 {i1}】" in run.prompt_snapshot


def test_gated_retry_discarded_drafts_kept(db_session, env):
    db, i1, i2 = env
    cfg = base_config()
    author = _author(db, cfg)
    bad = "# 废稿标题\n\n一段没有引用的正文。"
    good = make_draft_text(i1, i2)
    fake = FakeProvider({"w_draft": [bad], "w_revise": [good]})
    orig = pl.DeepSeekProvider
    pl.DeepSeekProvider = lambda _db: fake
    try:
        run = pl.run_pipeline_write(db, author, triggered_by="test")
    finally:
        pl.DeepSeekProvider = orig
    assert run.status == "OK"
    assert run.payload["rewrite"]["attempts"] == 1
    assert [t["node"] for t in run.payload["trace"]] == ["w_draft", "w_revise"]
    assert run.payload["trace"][0].get("discarded") is True  # 废稿留痕
    assert run.payload["trace"][0]["output"] == bad  # 废稿全文 DB 可见
    assert run.payload["gate_history"][0]["verdict"]["passed"] is False


def test_gated_retry_exhausted_fails(db_session, env):
    db, i1, i2 = env
    cfg = base_config()
    author = _author(db, cfg)
    # 逐轮不同的长度问题（正文长度递增）→ 每轮门禁问题集合不同，走满重试上限
    # 而非同因早停（同因喂同稿会提前终止，见 test_gate_retry_stops_early_on_repeated_same_issues）
    bad1 = "# 废稿标题\n\n一段没有引用的正文。"
    bad2 = "# 废稿标题\n\n一段没有引用的正文，这一版更长一些但依然没有任何脚注引用。"
    bad3 = "# 废稿标题\n\n又是一版没有脚注引用的废稿，正文长度继续变化以逐轮产生不同的字数问题。"
    fake = FakeProvider({"w_draft": [bad1], "w_revise": [bad2, bad3]})
    orig = pl.DeepSeekProvider
    pl.DeepSeekProvider = lambda _db: fake
    try:
        run = pl.run_pipeline_write(db, author, triggered_by="test")
    finally:
        pl.DeepSeekProvider = orig
    assert run.status == "FAILED"
    assert "门禁重试耗尽" in (run.error or "")
    assert run.article_id is None  # 无文章落库（废稿只在 trace 可见）
    assert len(run.payload["trace"]) == 3  # 初稿 + 2 次重试，全部留痕


def test_zero_revision_records_audit(db_session, env):
    db, i1, i2 = env
    cfg = base_config()
    cfg["route"]["rewrite"] = {"mode": "zero_revision", "max_attempts": 3, "on_gate_fail": "record"}
    author = _author(db, cfg)
    bad = "# 废稿标题\n\n一段没有引用的正文。"
    fake = FakeProvider({"w_draft": [bad]})
    orig = pl.DeepSeekProvider
    pl.DeepSeekProvider = lambda _db: fake
    try:
        run = pl.run_pipeline_write(db, author, triggered_by="test")
    finally:
        pl.DeepSeekProvider = orig
    assert run.status == "OK" and run.decision == "WRITE"  # 违规仍入库（零修订语义）
    assert run.payload["rewrite"]["attempts"] == 0
    assert run.payload["gates_final"]["passed"] is False
    assert "audit_note" in run.payload


def test_static_injection_hard_budget(db_session, env):
    db, i1, i2 = env
    cfg = base_config()
    blocks = [{"id": f"s{i:02d}", "text": f"记忆片段{i}。" + "内容" * 300,
               "source": f"小说素材/{i}.txt loc1-2", "injection": {"max_chars": 500}}
              for i in range(5)]
    cfg["memory"]["static_blocks"] = blocks
    cfg["memory"]["injection"] = {"max_slices_per_run": 3, "per_block_max_chars": 500,
                                  "selection": "round_robin", "position": "head"}
    author = _author(db, cfg)
    fake = FakeProvider({"w_draft": [make_draft_text(i1, i2)]})
    orig = pl.DeepSeekProvider
    pl.DeepSeekProvider = lambda _db: fake
    try:
        run = pl.run_pipeline_write(db, author, triggered_by="test")
    finally:
        pl.DeepSeekProvider = orig
    assert run.status == "OK"
    rec = run.payload["static_injection"]
    assert len(rec) == 3  # 硬预算：5 块只注 3
    assert all(r["chars"] <= 500 for r in rec)
    assert all(r["truncated"] for r in rec)  # 原块 400+ 字 → 截断记录
    # prompt 快照逐段可核
    assert sum(1 for i in range(5) if f"记忆片段{i}。" in run.prompt_snapshot) == 3


def test_copyright_gate_blocks_copying(db_session, env):
    db, i1, i2 = env
    cfg = base_config()
    block_text = "天空中的铁十字在燃烧，大地被炮火犁开，这就是所谓的圣战，实在是荒谬透顶的历史闹剧。"
    cfg["memory"]["static_blocks"] = [
        {"id": "s1", "text": block_text, "source": "小说素材/1.txt loc1", "injection": {"max_chars": 500}}]
    cfg["memory"]["injection"] = {"max_slices_per_run": 3, "per_block_max_chars": 500,
                                  "selection": "round_robin", "position": "tail"}
    author = _author(db, cfg)
    body = "开头。" + block_text + "结尾。"
    fake = FakeProvider({"w_draft": [make_draft_text(i1, i2, body=body)], "w_revise": [bad := make_draft_text(i1, i2, body=body), bad]})
    orig = pl.DeepSeekProvider
    pl.DeepSeekProvider = lambda _db: fake
    try:
        run = pl.run_pipeline_write(db, author, triggered_by="test")
    finally:
        pl.DeepSeekProvider = orig
    assert run.status == "FAILED"  # gated_retry 耗尽（每次重试都照抄）
    assert any("n-gram" in i for a in run.payload["gate_history"]
               for i in a["verdict"]["issues"])


def test_topic_dedup_gate(db_session, env):
    db, i1, i2 = env
    cfg = base_config()
    author = _author(db, cfg)
    db.add(Article(author_id=author.id, title="关于机器写作的三点观察",
                   body="x", citations=[], status="PUBLISHED_TO_C"))
    db.commit()
    fake = FakeProvider({"w_draft": [make_draft_text(i1, i2)],
                         "w_revise": [make_draft_text(i1, i2), make_draft_text(i1, i2)]})  # 同题
    orig = pl.DeepSeekProvider
    pl.DeepSeekProvider = lambda _db: fake
    try:
        run = pl.run_pipeline_write(db, author, triggered_by="test")
    finally:
        pl.DeepSeekProvider = orig
    assert run.status == "FAILED"
    assert any("同题" in i or "过于相似" in i for a in run.payload["gate_history"]
               for i in a["verdict"]["issues"])


def test_single_route_regression_no_json(db_session, env, monkeypatch):
    """无 author_json 的作者走现行 single 路线，行为不变。"""
    from app.models import Author

    db, i1, i2 = env
    author = Author(name="旧作者", model="m",
                    readable_directions=[{"direction_id": 1, "threshold": 60}])
    db.add(author)
    db.commit()

    class FakeOld:
        def __init__(self, _db):
            pass

        def chat_json(self, messages, **kw):
            data = {"decision": "write", "article": {
                "title": "旧路线文章", "body": "正文六百字" * 100,
                "citations": [{"item_id": i1, "quote": "事实一：模型写出了完整的文章。"}]},
                "reason": "r", "thinking": "t"}
            return data, "m"

    monkeypatch.setattr("app.authors.writer.DeepSeekProvider", FakeOld)
    # 直接调 run_write，验证分派：无 JSON 不进管线（不会出现 payload.trace）
    from app.authors.writer import run_write

    run = run_write(db, author, triggered_by="test")
    assert run.status == "OK" and run.decision == "WRITE"
    assert "trace" not in (run.payload or {})
    assert db.get(Article, run.article_id).title == "旧路线文章"


def test_reasoner_fallback(db_session, monkeypatch):
    """思考档模型不可用（400 类）→ 标记不可用并回退 chat 重发（官方 thinking 档位）。"""
    import app.config as cfgmod

    monkeypatch.setattr(cfgmod, "DEEPSEEK_THINKING_MODEL", "deepseek-v4-pro")
    p = DeepSeekProvider(db_session)
    calls = []

    def fake_call(payload, **kw):
        calls.append(payload["model"])
        if payload.get("thinking", {}).get("type") == "enabled" or payload["model"] == "deepseek-v4-pro":
            e = ProviderError("HTTP 400: Model Not Exist")
            e.retryable = False
            raise e
        return {"choices": [{"message": {"content": "ok"}}], "model": payload["model"],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    monkeypatch.setattr(p, "_call", fake_call)
    content, model = p.chat([{"role": "user", "content": "x"}],
                            call_point="w_draft", model_tier="reasoner")
    assert p.reasoner_available is False
    assert model == cfgmod.DEEPSEEK_MODEL
    assert "回退" in (p.fallback_note or "")
    # 二次调用直接走 chat（不再探测）
    calls.clear()
    p.chat([{"role": "user", "content": "x"}], call_point="w_draft", model_tier="reasoner")
    assert calls == [cfgmod.DEEPSEEK_MODEL]


def test_pipeline_empty_reading_set_lands_skip_without_llm(db_session):
    """空阅读集：写作轮直接落 SKIP 并保留 skip_reason，不发起任何模型调用
    （写作轮的本地短路语义：没有可写素材时跳过不是失败，且绝不烧一次调用）。"""
    db = db_session
    from app.models import Direction

    db.add(Direction(id=1, name="空集方向", prompt="p", threshold=60))
    db.commit()
    cfg = base_config()
    author = _author(db, cfg)
    fake = FakeProvider({})  # 任何节点调用都会因无脚本而抛错 → 测试失败即暴露
    orig = pl.DeepSeekProvider
    pl.DeepSeekProvider = lambda _db: fake
    try:
        run = pl.run_pipeline_write(db, author, triggered_by="test")
    finally:
        pl.DeepSeekProvider = orig
    assert run.status == "SKIP"
    assert run.skip_reason and "阅读集" in run.skip_reason
    assert run.article_id is None and run.decision is None
    assert fake.calls == []


def test_gate_retry_stops_early_on_repeated_same_issues(db_session, env):
    """门禁重试同因早停：修订后门禁检出与上一轮完全相同的问题集合时，修订已被证明
    无效，立即终止重试并以 FAILED 留痕，不再消耗剩余重试次数。"""
    db, i1, i2 = env
    cfg = base_config()
    author = _author(db, cfg)
    bad1 = "# 同因早停甲\n\n一段没有任何脚注引用的正文，且长度足以越过字数下限门槛线。"
    bad2 = "# 同因早停乙\n\n修订之后仍然没有任何脚注引用的正文，长度也足以越过字数下限。"
    fake = FakeProvider({"w_draft": [bad1], "w_revise": [bad2]})
    orig = pl.DeepSeekProvider
    pl.DeepSeekProvider = lambda _db: fake
    try:
        run = pl.run_pipeline_write(db, author, triggered_by="test")
    finally:
        pl.DeepSeekProvider = orig
    assert run.status == "FAILED"
    assert "早停" in (run.error or "")
    assert run.payload["rewrite"]["early_stop"] is True
    assert run.payload["rewrite"]["attempts"] == 1
    assert [t["node"] for t in run.payload["trace"]] == ["w_draft", "w_revise"]
    assert len(run.payload["gate_history"]) == 2
    assert run.article_id is None


def test_gate_retry_continues_while_issues_differ(db_session, env):
    """门禁重试异因继续：每次修订后检出的问题与上一轮不同（说明修订在起作用）时，
    重试按既定上限继续，直至门禁通过。"""
    db, i1, i2 = env
    cfg = base_config()
    cfg["route"]["gates"]["length"] = {"min": 20, "max": 100, "unit": "chars"}
    author = _author(db, cfg)
    bad1 = "# 异因交错甲\n\n没有任何脚注引用的正文内容，这里凑一些长度跨过下限门槛。"
    long2 = ("# 异因交错乙\n\n这是一段足够长的正文内容，用来触发字数上限门禁的判定逻辑。" * 3
             + "事实一。[^1]事实二。[^2]"
             + f"\n\n[^1]: [条目 {i1}] 事实一\n[^2]: [条目 {i2}] 事实二")
    good = make_draft_text(i1, i2)
    fake = FakeProvider({"w_draft": [bad1], "w_revise": [long2, good]})
    orig = pl.DeepSeekProvider
    pl.DeepSeekProvider = lambda _db: fake
    try:
        run = pl.run_pipeline_write(db, author, triggered_by="test")
    finally:
        pl.DeepSeekProvider = orig
    assert run.status == "OK"
    assert run.payload["rewrite"]["attempts"] == 2
    assert run.payload["rewrite"].get("early_stop", False) is False
    assert [t["node"] for t in run.payload["trace"]] == ["w_draft", "w_revise", "w_revise"]
