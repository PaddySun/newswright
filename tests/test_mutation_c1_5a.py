"""C1-5a 变异分诊批次 6 补强测试（authors.pipeline 执行器核心 PipelineRunner，580 条
幸存变异体分诊后 276 条 C 类的关闭测试）。

断言全部来自设计书条款：
- 产品书 AC-11.1（路线按 JSON 执行：write_run.payload.trace 恰含节点序列
  w_outline → w_draft(incubate) → w_rhythm → gates，每节点带 tier/model/tokens；
  passes 节点入序列）；AC-11.2（门禁拒收、gated 重试 ≤3、重试提示词附前次违规
  摘要、耗尽 FAILED、废稿全文留痕 trace）；DT-4（门禁失败重试<3 / 耗尽 FAILED /
  record 语义）；AC-11.4（版权 n-gram n=8）；AC-12.1（article.citations =
  [{item_id, quote}]、markdown 落库）；AC-12.3（prompt_snapshot 含「本期全网热点
  风向」段、热点不进引用）；
- 技术书 §4.1 write_run 行（payload 含 trace + static_injection、prompt_snapshot
  独立列、usage_log 按 ref_type/ref_id 归因）+ 模块表 authors/pipeline 行（节点
  编排/trace/门禁循环）；§4.4 记忆系统（topic 模块 = {topic_memory} 占位符回流源，
  add_memory 的 module 值即回流过滤键）；ADR-8（provider 调用契约：messages 结构、
  call_point/max_tokens/json_mode/model_tier 实参、计量落账不虚增）；
- US-10 author.json schema 契约（think_routing.default/per_node、
  output.max_tokens_per_node、gates.length/fingerprint/echo_check/copyright/
  topic_dedup/citation 各键、injection.selection/position、DRAFT_MODES、
  GATE_FAIL_ACTIONS、rewrite.max_attempts——schema 枚举/键名即参数契约）；
- 搭建记录纪律（作者写作管线-搭建记录-20260928：JSON 节点恒 chat 档；reasoner
  空正文回退 chat；U 形放置）。

网络纪律：FakeProvider 脚本化输出沿用 tests/test_author_pipeline.py 的 calls 捕获
形态，不真联网；生产代码零改动。
"""
import json

import pytest

import app.authors.pipeline as pl
from app.authors.importer import import_author_json
from app.authors.schema import default_author_config
from app.models import Article, Item, MemoryEntry, ScoreResult, WriteRun


class FakeProvider:
    """按 call_point 弹出脚本化输出的假 provider（calls 捕获调用契约）。"""

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


def make_draft_text(item1: int, item2: int, title: str = "关于机器写作的三点观察"):
    return (
        f"# {title}\n\n他说要写一篇文章。事实一。[^1]事实二。[^2]\n\n"
        f"[^1]: [条目 {item1}] 事实一\n"
        f"[^2]: [条目 {item2}] 事实二\n"
    )


BAD_DRAFT = "# 废稿标题\n\n一段没有引用的正文。"


@pytest.fixture()
def env(db_session):
    """1 方向 + 2 条目（passed）基础环境，返回 (db, item1_id, item2_id)。"""
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


def base_config(name="分诊批次六作者"):
    cfg = default_author_config("c15a_t", name)
    cfg["route"]["gates"]["length"] = {"min": 20, "max": 5000, "unit": "chars"}
    cfg["route"]["gates"]["citation"] = {"min_count": 2}
    return cfg


def _author(db, cfg, **kw):
    return import_author_json(db, cfg, model="test-model",
                              readable_directions=[{"direction_id": 1, "threshold": 60}], **kw)


def _pairs(db):
    from app.models import ScoreResult as SR

    rows = db.query(Item, SR).join(SR, SR.item_id == Item.id).all()
    return [(it, sr) for it, sr in rows]


def _run_e2e(db, author, fake, **kw):
    orig = pl.DeepSeekProvider
    pl.DeepSeekProvider = lambda _db: fake
    try:
        return pl.run_pipeline_write(db, author, triggered_by="test", **kw)
    finally:
        pl.DeepSeekProvider = orig


def _runner(db, author, cfg, fake):
    """直接构造执行器（绕过 author.json 校验，用于缺省键/私有方法场景）。"""
    run = WriteRun(author_id=author.id, triggered_by="test", model="test-model")
    db.add(run)
    db.commit()
    return pl.PipelineRunner(db, author, run, cfg, fake), run


def _execute_direct(db, author, cfg, fake):
    """直接执行 execute（schema 必填键被删后的缺省路径场景）。"""
    run = WriteRun(author_id=author.id, triggered_by="test", model="test-model")
    db.add(run)
    db.commit()
    runner = pl.PipelineRunner(db, author, run, cfg, fake)
    runner.pairs = _pairs(db)
    article = runner.execute()
    return run, article


# ---------- _tier：档位路由（US-10 think_routing + AC-11.1） ----------

def test_tier_routing_json_contract(db_session, env):
    db, _, _ = env
    cfg = base_config()
    cfg["route"]["think_routing"] = {"default": "reasoner", "per_node": {"w_draft": "chat"}}
    author = _author(db, cfg)
    runner, _ = _runner(db, author, cfg, FakeProvider({}))
    assert runner._tier("w_outline") == "chat"    # JSON 节点恒 chat（搭建记录纪律4）
    assert runner._tier("w_incubate") == "chat"
    assert runner._tier("w_draft") == "chat"      # per_node 覆写生效
    assert runner._tier("w_revise") == "reasoner"  # default 生效
    cfg2 = base_config()
    cfg2["route"]["think_routing"] = {}
    runner2, _ = _runner(db, author, cfg2, FakeProvider({}))
    assert runner2._tier("w_revise") == "chat"    # 无 default 键回退 chat


# ---------- _max_tokens：节点覆写契约（US-10 output.max_tokens_per_node） ----------

def test_max_tokens_per_node_override_contract(db_session, env):
    db, _, _ = env
    cfg = base_config()
    cfg["output"]["max_tokens_per_node"] = {"w_outline": 777}
    author = _author(db, cfg)
    runner, _ = _runner(db, author, cfg, FakeProvider({}))
    assert runner._max_tokens("w_outline", 4000) == 777       # 覆写生效
    assert runner._max_tokens("w_draft", 4000) == pl.NODE_MAX_TOKENS["w_draft"]  # 未覆写节点查默认表
    cfg2 = base_config()
    cfg2["output"].pop("max_tokens_per_node")                  # schema 可选键：缺省须可用
    runner2, _ = _runner(db, author, cfg2, FakeProvider({}))
    assert runner2._max_tokens("w_outline", 4000) == pl.NODE_MAX_TOKENS["w_outline"]


# ---------- _call/_flush：provider 调用契约 + trace entry（ADR-8 + AC-11.1 + §4.1） ----------

def test_call_trace_entry_usage_and_provider_contract(db_session, env):
    db, _, _ = env
    cfg = base_config()
    cfg["route"]["think_routing"] = {"default": "reasoner", "per_node": {"w_draft": "chat"}}
    cfg["output"]["max_tokens_per_node"] = {"w_draft": 777}
    author = _author(db, cfg)
    fake = FakeProvider({"w_draft": ["正文输出"]})
    runner, run = _runner(db, author, cfg, fake)
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    content, entry = runner._call("w_draft", msgs, temperature=0.9)  # 非 JSON 节点不传 json_mode
    assert content == "正文输出"
    call = fake.calls[0]
    assert call["messages"] == msgs                       # ADR-8：messages 原样传递
    assert call["call_point"] == "w_draft"
    assert call["ref_type"] == "author" and call["ref_id"] == author.id  # §4.1 usage_log 归因列
    assert call["json_mode"] is False                     # 缺省非 JSON 模式（非 JSON 节点不得启用）
    assert call["max_tokens"] == 777                      # 覆写按节点解析
    assert call["temperature"] == 0.9
    assert call["model_tier"] == "chat"                   # AC-11.1 tier 按节点路由
    assert entry["node"] == "w_draft" and entry["tier"] == "chat"
    assert entry["model"] == "fake-model"                 # AC-11.1 每节点带 model
    assert entry["tokens_in"] == 10 and entry["tokens_out"] == 20  # AC-11.1 每节点带 tokens
    assert entry["output"] == "正文输出"
    assert run.payload["trace"] and run.payload["trace"][0]["node"] == "w_draft"  # §4.1 payload trace
    # usage 缺键须回 0——计量账本不虚增（ADR-8 计量落账）
    fake2 = FakeProvider({"w_draft": ["x"]})
    fake2.last_usage = {}
    runner2, _ = _runner(db, author, cfg, fake2)
    _, entry2 = runner2._call("w_draft", msgs, temperature=0.9)
    assert entry2["tokens_in"] == 0 and entry2["tokens_out"] == 0


# ---------- run_gates：门禁配置契约（US-10 gates + AC-11.2/11.4） ----------

def test_gate_length_and_fingerprint_config(db_session, env):
    db, _, _ = env
    cfg = base_config()
    cfg["route"]["gates"]["length"] = {"min": 100, "max": 5000, "unit": "chars"}
    cfg["route"]["gates"]["citation"] = {"min_count": 0}
    cfg["identity"]["style_rules"]["fingerprint"] = ["铁十字", "荒谬"]
    cfg["route"]["gates"]["fingerprint"] = {"min_hits": 2}
    author = _author(db, cfg)
    runner, _ = _runner(db, author, cfg, FakeProvider({}))
    v = runner.run_gates("# 短文\n\n铁十字挂在墙上。", {}, [], [])
    assert v.passed is False
    assert any("字数" in i for i in v.issues)      # length.min=100 生效
    assert any("风格指纹" in i for i in v.issues)   # 词表+min_hits=2 生效（1 命中 < 2 须拒）
    # 词表断裂改判：双词全命中 + min_hits=2 → 不得出指纹 issue（词表须真实参与计数）
    v2 = runner.run_gates("# 短文\n\n铁十字与荒谬都在正文里出现。", {}, [], [])
    assert not any("风格指纹" in i for i in v2.issues)
    # min_hits 键缺省（schema 必填，直接构造执行器）：缺省 0 → 零命中不出指纹 issue
    cfg3 = base_config()
    cfg3["route"]["gates"]["citation"] = {"min_count": 0}
    cfg3["route"]["gates"]["length"] = {"min": 0, "max": 5000, "unit": "chars"}
    cfg3["route"]["gates"]["fingerprint"] = {}
    cfg3["identity"]["style_rules"]["fingerprint"] = ["铁十字", "荒谬"]
    runner3, _ = _runner(db, author, cfg3, FakeProvider({}))
    v3 = runner3.run_gates("# 短文\n\n没有任何指纹词的正文内容。", {}, [], [])
    assert not any("风格指纹" in i for i in v3.issues)
    # style_rules 键缺省：词表空 → 零命中 + min_hits=2 仍须拒（词表解析不得崩）
    cfg4 = base_config()
    cfg4["route"]["gates"]["citation"] = {"min_count": 0}
    cfg4["route"]["gates"]["fingerprint"] = {"min_hits": 2}
    cfg4["identity"].pop("style_rules")
    runner4, _ = _runner(db, author, cfg4, FakeProvider({}))
    v4 = runner4.run_gates("# 短文\n\n铁十字挂在墙上。", {}, [], [])
    assert any("风格指纹" in i for i in v4.issues)
    # fingerprint 词表键缺省：词表空 → 同上须拒（不得崩）
    cfg5 = base_config()
    cfg5["route"]["gates"]["citation"] = {"min_count": 0}
    cfg5["route"]["gates"]["fingerprint"] = {"min_hits": 2}
    cfg5["identity"]["style_rules"].pop("fingerprint")
    runner5, _ = _runner(db, author, cfg5, FakeProvider({}))
    v5 = runner5.run_gates("# 短文\n\n铁十字挂在墙上。", {}, [], [])
    assert any("风格指纹" in i for i in v5.issues)


def test_gate_echo_check_config(db_session, env):
    db, _, _ = env
    cfg = base_config()
    cfg["route"]["gates"]["citation"] = {"min_count": 0}
    cfg["identity"]["style_anchor"] = (
        "黄昏的铁十字在废墟上空缓慢旋转，像一枚生锈的指南针指向早已不存在的北方之地。")
    cfg["route"]["gates"]["echo_check"] = True
    author = _author(db, cfg)
    runner, _ = _runner(db, author, cfg, FakeProvider({}))
    chunk = cfg["identity"]["style_anchor"][3:26]  # 23 字 ≥ 回显阈值
    v = runner.run_gates(f"# 回显测试\n\n开头。{chunk}后续正文内容继续。", {}, [], [])
    assert any("回显风格锚" in i for i in v.issues)  # echo_check 开 + 锚配置生效


def test_gate_copyright_ngram_config(db_session, env):
    db, _, _ = env
    # ngram 覆写生效：n=6 时 7 字复述 ≥2 处命中须拒（n=8 则不命中）
    cfg = base_config()
    cfg["route"]["gates"]["citation"] = {"min_count": 0}
    cfg["route"]["gates"]["copyright"] = {"ngram": 6}
    block6 = "夕阳沉入断墙之后，风把尘埃卷成灰色的漩涡，覆盖了所有的名字。"
    cfg["memory"]["static_blocks"] = [
        {"id": "s1", "text": block6, "source": "素材/1", "injection": {"max_chars": 500}}]
    author = _author(db, cfg)
    runner, _ = _runner(db, author, cfg, FakeProvider({}))
    region6 = block6[2:9]  # 恰 7 字
    v = runner.run_gates(f"# 版权测试\n\n前文。{region6}后文继续展开内容。", {}, [], [])
    assert any("n-gram" in i for i in v.issues)
    # ngram 缺省 = 8（AC-11.4 钉 n=8）：两个不相交的 8 字复述 → 2 处命中须拒；n=9 则不命中
    cfg2 = base_config()
    cfg2["route"]["gates"]["citation"] = {"min_count": 0}
    cfg2["route"]["gates"]["copyright"] = {"enabled": True}   # 无 ngram 键 → 走缺省 n=8
    a8, b8 = "铁十字在暮色里缓", "生锈的指南针早停"   # 恰 8 字：n=8 各 1 处命中（≥2 拒）；n=9 零命中
    block8 = a8 + "，中间隔断。," + b8
    cfg2["memory"]["static_blocks"] = [
        {"id": "s1", "text": block8, "source": "素材/1", "injection": {"max_chars": 500}}]
    runner2, _ = _runner(db, author, cfg2, FakeProvider({}))
    text8 = f"# 版权测试二\n\n开头{a8}中间内容。再写{b8}结尾收束。"
    v2 = runner2.run_gates(text8, {}, [], [])
    assert any("n-gram" in i for i in v2.issues)


def test_gate_topic_dedup_and_citation_config(db_session, env):
    db, i1, i2 = env
    good = make_draft_text(i1, i2)
    defs = pl.parse_footnote_defs(good)
    pairs = _pairs(db)
    cfg = base_config()
    author = _author(db, cfg)
    # recent_n 覆写生效：recent_n=2 时第 3 条同题不进窗，须放行
    cfg1 = base_config()
    cfg1["route"]["gates"]["topic_dedup"] = {"recent_n": 2, "threshold": 0.55}
    runner1, _ = _runner(db, author, cfg1, FakeProvider({}))
    v1 = runner1.run_gates(good, defs, pairs,
                           ["近期文章甲标题", "近期文章乙标题", "关于机器写作的三点观察"])
    assert v1.passed is True
    # 同题判重：同题在窗内须拒（标题实参不可为 None）
    v1b = runner1.run_gates(good, defs, pairs,
                            ["关于机器写作的三点观察", "近期文章甲标题"])
    assert v1b.passed is False and any("同题" in i for i in v1b.issues)
    # threshold 覆写生效：0.9 时 0.87 相似度须放行（缺省 0.55 会拒）
    cfg2 = base_config()
    cfg2["route"]["gates"]["topic_dedup"] = {"recent_n": 2, "threshold": 0.9}
    runner2, _ = _runner(db, author, cfg2, FakeProvider({}))
    v2 = runner2.run_gates(good, defs, pairs, ["关于机器写作的三点观察评论版"])
    assert v2.passed is True
    # recent_n 可省略：缺省窗 5，同题在窗内须拒
    cfg3 = base_config()
    cfg3["route"]["gates"]["topic_dedup"] = {"threshold": 0.55}
    runner3, _ = _runner(db, author, cfg3, FakeProvider({}))
    v3 = runner3.run_gates(good, defs, pairs, ["关于机器写作的三点观察"])
    assert v3.passed is False and any("同题" in i for i in v3.issues)
    # min_count 覆写生效：min_count=3 时 2 条引用须拒
    cfg4 = base_config()
    cfg4["route"]["gates"]["citation"] = {"min_count": 3}
    runner4, _ = _runner(db, author, cfg4, FakeProvider({}))
    v4 = runner4.run_gates(good, defs, pairs, [])
    assert v4.passed is False and any("脚注引用" in i for i in v4.issues)
    # min_count 键缺省（schema 必填，直接构造执行器）：缺省 2 → 2 条引用放行（verdict 全过）
    cfg5 = base_config()
    cfg5["route"]["gates"]["citation"] = {}
    runner5, _ = _runner(db, author, cfg5, FakeProvider({}))
    v5 = runner5.run_gates(good, defs, pairs, [])
    assert v5.passed is True


# ---------- execute：静态注入放置（US-10 injection.position/selection） ----------

@pytest.mark.parametrize("pos", ["head", "u", "tail"])
def test_injection_position_placement(db_session, env, pos):
    db, i1, i2 = env
    cfg = base_config()
    cfg["memory"]["static_blocks"] = [
        {"id": "b1", "text": "AI写作实验里的声音记忆片段甲。", "source": "素材/1",
         "injection": {"max_chars": 500}},
        {"id": "b2", "text": "与本期选题毫无交集的通用声音片段乙。", "source": "素材/2",
         "injection": {"max_chars": 500}},
    ]
    cfg["memory"]["injection"] = {"max_slices_per_run": 2, "per_block_max_chars": 500,
                                  "selection": "relevant", "position": pos}
    author = _author(db, cfg)
    fake = FakeProvider({"w_draft": [make_draft_text(i1, i2)]})
    run = _run_e2e(db, author, fake)
    assert run.status == "OK"
    snap = run.prompt_snapshot
    i_read = snap.index("【本期阅读集】")
    i_b1 = snap.rindex("片段甲")   # relevant 选取：b1 与阅读集标题重叠分最高 → 第 1 块
    i_b2 = snap.rindex("片段乙")   # rindex：防重复块混入（u 放置断裂会复制出第二处）
    if pos == "head":
        assert i_b1 < i_read and i_b2 < i_read
    elif pos == "u":               # U 形：第 1 块在前、其余在后（搭建记录 U 形放置）
        assert i_b1 < i_read < i_b2
        assert snap.count("片段乙") == 1   # 乙仅尾部出现一次——头部全量复制即断裂
    else:
        assert i_b1 > i_read and i_b2 > i_read


def test_injection_position_default_head(db_session, env):
    """position 键缺省（schema 必填，直接构造执行器）：缺省 head 放置。"""
    db, i1, i2 = env
    cfg = base_config()
    cfg["memory"]["static_blocks"] = [
        {"id": "b1", "text": "AI写作实验里的声音记忆片段甲。", "source": "素材/1",
         "injection": {"max_chars": 500}},
    ]
    cfg["memory"]["injection"] = {"max_slices_per_run": 1, "per_block_max_chars": 500,
                                  "selection": "relevant"}   # 无 position 键 → 缺省 head
    author = _author(db, base_config())
    fake = FakeProvider({"w_draft": [make_draft_text(i1, i2)]})
    run, article = _execute_direct(db, author, cfg, fake)
    assert article is not None
    snap = run.prompt_snapshot
    assert snap.index("片段甲") < snap.index("【本期阅读集】")


# ---------- execute：recent_n 配置 + 近期标题段（US-10 + AC-11.2 + §4.1） ----------

def test_recent_n_config_gates_context(db_session, env):
    db, i1, i2 = env
    cfg = base_config()
    cfg["route"]["gates"]["topic_dedup"] = {"recent_n": 2, "threshold": 0.55}
    author = _author(db, cfg)
    # _recent_titles 取最近 N 条（id 倒序）：同题插在最前 → 不进 recent_n=2 的窗
    for t in ["关于机器写作的三点观察", "近期文章甲标题", "近期文章乙标题"]:
        db.add(Article(author_id=author.id, title=t, body="x", citations=[],
                       status="PUBLISHED_TO_C"))
    db.commit()
    fake = FakeProvider({"w_draft": [make_draft_text(i1, i2)]})
    run = _run_e2e(db, author, fake)
    assert run.status == "OK"          # recent_n=2：同题第 3 条不入窗，不触发判重
    snap = run.prompt_snapshot
    assert "【本期阅读集】" in snap                       # §4.1 snapshot 阅读集逐字可核（W4）
    assert "《近期文章甲标题》" in snap and "《近期文章乙标题》" in snap
    assert "《关于机器写作的三点观察》" not in snap        # recent_n=2 只带 2 条
    # recent_n 缺省路径（schema 必填，直接构造执行器）：缺省窗 5 → 同题入窗 → 耗尽 FAILED
    cfg2 = base_config()
    cfg2["route"]["gates"]["topic_dedup"] = {"threshold": 0.55}
    author2 = _author(db, base_config())
    db.add(Article(author_id=author2.id, title="关于机器写作的三点观察", body="x", citations=[],
                   status="PUBLISHED_TO_C"))
    db.commit()
    fake2 = FakeProvider({"w_draft": [make_draft_text(i1, i2)],
                          "w_revise": [make_draft_text(i1, i2), make_draft_text(i1, i2)]})
    run2, article2 = _execute_direct(db, author2, cfg2, fake2)
    assert article2 is None and run2.status == "FAILED"


# ---------- execute：热点风向段（AC-12.3） ----------

def test_hot_brief_in_snapshot(db_session, env):
    db, i1, i2 = env
    from app.models import HotBatch

    cfg = base_config()
    author = _author(db, cfg)
    author.include_hot_brief = True
    db.add(HotBatch(date="2026-10-03", keywords=["风电", "卫星"], summary="风向综述内容。",
                    source_platforms=[]))
    db.commit()
    fake = FakeProvider({"w_draft": [make_draft_text(i1, i2)]})
    run = _run_e2e(db, author, fake)
    assert run.status == "OK"
    assert "本期全网热点风向" in run.prompt_snapshot   # AC-12.3：snapshot 含热点风向段


# ---------- execute：节点序列按 JSON 执行（AC-11.1）+ 产物契约（AC-12.1/§4.1/§4.4） ----------

def test_route_sequence_single_with_outline(db_session, env):
    db, i1, i2 = env
    cfg = base_config()
    cfg["route"]["outline"]["template"] = "variation"
    outline_json = json.dumps({"title": "规划标题甲", "thesis": "中心论点。",
                               "sections": [{"key": "甲", "brief": "要点甲"},
                                            {"key": "乙", "brief": "要点乙"},
                                            {"key": "丙", "brief": "要点丙"}]},
                              ensure_ascii=False)
    author = _author(db, cfg)
    fake = FakeProvider({"w_outline": [outline_json], "w_draft": [make_draft_text(i1, i2)]})
    run = _run_e2e(db, author, fake)
    assert run.status == "OK" and run.decision == "WRITE"
    trace = run.payload["trace"]
    assert [t["node"] for t in trace] == ["w_outline", "w_draft"]   # AC-11.1 节点序列
    outline_call = fake.calls[0]
    assert outline_call["messages"] and outline_call["messages"][1]["role"] == "user"
    assert "【本期阅读集】" in outline_call["messages"][1]["content"]   # 规划须携带阅读集上下文
    assert "discarded" not in trace[1]     # 正常稿不得误标废稿（AC-11.2 留痕语义）
    draft_call = fake.calls[1]
    assert draft_call["messages"][0]["role"] == "system"
    assert draft_call["messages"][0]["content"]
    assert draft_call["messages"][1]["role"] == "user"
    assert draft_call["messages"][1]["content"]
    article = db.get(Article, run.article_id)
    assert set(article.citations[0].keys()) == {"item_id", "quote"}   # AC-12.1
    assert article.status == "PUBLISHED_TO_C"                          # DT-4 文章入 C 流
    mem = db.query(MemoryEntry).filter_by(author_id=author.id).all()
    assert any(m.module == "topic" for m in mem)                       # §4.4 topic 回流模块


def test_route_sequence_incubate(db_session, env):
    db, i1, i2 = env
    cfg = base_config()
    cfg["route"]["draft"]["mode"] = "incubate"
    incubate_json = json.dumps({"theme": "核心之事", "chain": ["一", "二", "三"],
                                "opening_image": "起笔", "closing_line": "收束"},
                               ensure_ascii=False)
    author = _author(db, cfg)
    fake = FakeProvider({"w_incubate": [incubate_json], "w_draft": [make_draft_text(i1, i2)]})
    run = _run_e2e(db, author, fake)
    assert run.status == "OK"
    assert [t["node"] for t in run.payload["trace"]] == ["w_incubate", "w_draft"]  # AC-11.1
    incubate_call = fake.calls[0]
    assert incubate_call["messages"] and incubate_call["messages"][0]["role"] == "system"
    assert "【本期阅读集】" in incubate_call["messages"][1]["content"]  # 构思须携带阅读集上下文


def test_route_sequence_rolling_three_sections(db_session, env):
    db, i1, i2 = env
    cfg = base_config()
    cfg["route"]["outline"]["template"] = "pyramid"
    cfg["route"]["draft"]["mode"] = "rolling"
    sections = [{"key": f"k{n}", "brief": f"要点{n}"} for n in range(1, 6)]  # 5 节：截断至契约 ×3
    outline_json = json.dumps({"title": "规划标题甲", "thesis": "中心论点。", "sections": sections},
                              ensure_ascii=False)
    author = _author(db, cfg)
    fake = FakeProvider({"w_outline": [outline_json],
                         "w_draft": [make_draft_text(i1, i2) for _ in range(3)]})
    run = _run_e2e(db, author, fake)
    assert run.status == "OK"
    assert [t["node"] for t in run.payload["trace"]] == [
        "w_outline", "w_draft", "w_draft", "w_draft"]      # AC-11.1：outline 契约 sections 恰好 3
    article = db.get(Article, run.article_id)
    assert article.title == "规划标题甲"                    # rolling 取大纲标题（§4.1 title 列）


def test_route_sequence_rolling_outline_none_template(db_session, env):
    """rolling + outline 模板 none：依赖运行时补算大纲（AC-11.1 rolling 依赖大纲）。"""
    db, i1, i2 = env
    cfg = base_config()
    cfg["route"]["draft"]["mode"] = "rolling"
    outline_json = json.dumps({"title": "规划标题甲", "thesis": "中心论点。",
                               "sections": [{"key": "甲", "brief": "要点甲"},
                                            {"key": "乙", "brief": "要点乙"},
                                            {"key": "丙", "brief": "要点丙"}]},
                              ensure_ascii=False)
    author = _author(db, cfg)
    fake = FakeProvider({"w_outline": [outline_json],
                         "w_draft": [make_draft_text(i1, i2) for _ in range(3)]})
    run = _run_e2e(db, author, fake)
    assert run.status == "OK"
    assert [t["node"] for t in run.payload["trace"]] == [
        "w_outline", "w_draft", "w_draft", "w_draft"]      # 大纲补算须真实发生
    assert "【本期阅读集】" in fake.calls[0]["messages"][1]["content"]


def test_route_sequence_rolling_outline_without_title(db_session, env):
    """rolling 大纲缺 title 键：回退 _title 提取（§4.1 title 列落值）。"""
    db, i1, i2 = env
    cfg = base_config()
    cfg["route"]["outline"]["template"] = "pyramid"
    cfg["route"]["draft"]["mode"] = "rolling"
    outline_json = json.dumps({"thesis": "中心论点。",
                               "sections": [{"key": "甲", "brief": "要点甲"},
                                            {"key": "乙", "brief": "要点乙"},
                                            {"key": "丙", "brief": "要点丙"}]},
                              ensure_ascii=False)
    author = _author(db, cfg)
    fake = FakeProvider({"w_outline": [outline_json],
                         "w_draft": [make_draft_text(i1, i2) for _ in range(3)]})
    run = _run_e2e(db, author, fake)
    assert run.status == "OK"
    article = db.get(Article, run.article_id)
    assert article.title == "关于机器写作的三点观察"       # 大纲无题 → 从正文提取


# ---------- node_draft：空稿守卫与 reasoner 回退（技术书 provider 纪律 + AC-11.1） ----------

def test_empty_draft_reasoner_fallback(db_session, env):
    db, i1, i2 = env
    cfg = base_config()
    cfg["route"]["think_routing"] = {"default": "chat", "per_node": {"w_draft": "reasoner"}}
    author = _author(db, cfg)
    fake = FakeProvider({"w_draft": ["", make_draft_text(i1, i2)]})
    run = _run_e2e(db, author, fake)
    assert run.status == "OK"                          # 重试后成文
    assert len(fake.calls) == 2                        # 空稿 → 回退 chat 重发一次
    assert fake.reasoner_available is False            # 标记不可用（后续调用回退依据）
    assert [t["node"] for t in run.payload["trace"]] == ["w_draft", "w_draft"]
    assert fake.calls[1]["messages"] == fake.calls[0]["messages"]


def test_empty_draft_chat_no_retry(db_session, env):
    db, i1, i2 = env
    cfg = base_config()
    cfg["route"]["think_routing"] = {"default": "chat", "per_node": {}}
    author = _author(db, cfg)
    fake = FakeProvider({"w_draft": [""]})
    run = _run_e2e(db, author, fake)
    assert run.status == "FAILED" and run.article_id is None  # 草稿为空 → FAILED（DT-4）
    assert len(fake.calls) == 1                        # chat 档空稿不触发回退重试


# ---------- execute：passes 修订遍按 JSON 执行（AC-11.1） ----------

def test_passes_prune_wiring(db_session, env):
    db, i1, i2 = env
    cfg = base_config()
    cfg["route"]["passes"] = [{"type": "prune", "params": {}}]
    author = _author(db, cfg)
    fake = FakeProvider({"w_draft": [make_draft_text(i1, i2)],
                         "w_prune": [make_draft_text(i1, i2)]})
    run = _run_e2e(db, author, fake)
    assert run.status == "OK"
    assert [t["node"] for t in run.payload["trace"]] == ["w_draft", "w_prune"]  # AC-11.1 passes 入序列


def test_passes_key_absent_default_path(db_session, env):
    """passes 键缺省（schema 必填，此处直接构造执行器走缺省路径）：无修订遍。"""
    db, i1, i2 = env
    cfg2 = base_config()
    cfg2["route"].pop("passes")
    author2 = _author(db, base_config())
    fake2 = FakeProvider({"w_draft": [make_draft_text(i1, i2)]})
    run2, article = _execute_direct(db, author2, cfg2, fake2)
    assert article is not None
    assert [t["node"] for t in run2.payload["trace"]] == ["w_draft"]


# ---------- execute：rewrite 语义（US-10 GATE_FAIL_ACTIONS + DT-4 + AC-11.2） ----------

def test_on_gate_fail_record_no_revise(db_session, env):
    db, i1, i2 = env
    cfg = base_config()
    cfg["route"]["rewrite"] = {"mode": "gated_retry", "max_attempts": 3, "on_gate_fail": "record"}
    author = _author(db, cfg)
    fake = FakeProvider({"w_draft": [BAD_DRAFT]})
    run = _run_e2e(db, author, fake)
    assert run.status == "OK" and "audit_note" in run.payload   # record：违规仍入库
    assert len(fake.calls) == 1                                  # 不触发修订


def test_on_gate_fail_absent_defaults_to_revise(db_session, env):
    """on_gate_fail 键缺省（schema 必填，直接构造执行器）：缺省须重试（DT-4 重试<3）。"""
    db, i1, i2 = env
    cfg2 = base_config()
    cfg2["route"]["rewrite"].pop("on_gate_fail")
    author2 = _author(db, base_config())
    fake2 = FakeProvider({"w_draft": [BAD_DRAFT], "w_revise": [make_draft_text(i1, i2)]})
    run2, article = _execute_direct(db, author2, cfg2, fake2)
    assert article is not None
    assert len(fake2.calls) == 2                                 # 缺省即重试


def test_max_attempts_contract(db_session, env):
    db, i1, i2 = env
    # max_attempts 覆写生效：=2 时耗尽即 FAILED，总调用 1+2
    cfg = base_config()
    cfg["route"]["rewrite"] = {"mode": "gated_retry", "max_attempts": 2, "on_gate_fail": "revise"}
    author = _author(db, cfg)
    fake = FakeProvider({"w_draft": [BAD_DRAFT], "w_revise": [BAD_DRAFT, BAD_DRAFT]})
    run = _run_e2e(db, author, fake)
    assert run.status == "FAILED" and run.article_id is None
    assert len(fake.calls) == 2            # max_attempts=2 = 初稿+1 次重试（总尝试数口径）


def test_max_attempts_absent_default_three(db_session, env):
    """max_attempts 键缺省（schema 必填，直接构造执行器）：缺省 3（AC-11.2 钉 ≤3）。"""
    db, i1, i2 = env
    cfg2 = base_config()
    cfg2["route"]["rewrite"].pop("max_attempts")
    author2 = _author(db, base_config())
    fake2 = FakeProvider({"w_draft": [BAD_DRAFT],
                          "w_revise": [BAD_DRAFT, BAD_DRAFT, BAD_DRAFT]})
    run2, article = _execute_direct(db, author2, cfg2, fake2)
    assert article is None and run2.status == "FAILED"
    assert len(fake2.calls) == 3            # 缺省 3 = 初稿+2 次重试（AC-11.2 ≤3）


# ---------- node_revise：重试消息契约（ADR-8 + AC-11.2 违规摘要附上） ----------

def test_revise_message_contract(db_session, env):
    db, i1, i2 = env
    cfg = base_config()
    author = _author(db, cfg)
    fake = FakeProvider({"w_draft": [BAD_DRAFT], "w_revise": [make_draft_text(i1, i2)]})
    run = _run_e2e(db, author, fake)
    assert run.status == "OK"
    revise_call = fake.calls[1]
    assert revise_call["call_point"] == "w_revise"
    assert revise_call["messages"][0]["role"] == "system"
    assert revise_call["messages"][0]["content"]
    assert revise_call["messages"][1]["role"] == "user"
    assert revise_call["messages"][1]["content"]
    assert "脚注引用" in revise_call["messages"][1]["content"]   # AC-11.2：重试附前次违规摘要
