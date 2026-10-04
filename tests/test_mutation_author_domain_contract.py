"""C1-7 变异分诊批次 9 补强测试（authors 域收官批：writer/gates/memory/importer

> 追溯注记：本文件原名 tests/test_mutation_c1_7.py（原批次代号见文件名），按对象重命名于 F1⑫治理批。
477 条幸存变异体分诊后 255 条新增 C 类的关闭测试）。

断言全部来自设计书条款：
- 产品书 v1.6 US-11/12：AC-11.2（门禁拒收、重试提示词附违规摘要 R6）、AC-11.3
  （引用硬校验：空白归一化+NFKC 逐字命中、集外 item 拒收）、AC-11.4（版权门禁
  n-gram 命中数必须为 0）、AC-11.5（不写判定：SKIP + reason/thinking=模型原始输出）、
  AC-11.6（single 路线回归：call_point="writing"）、AC-12.1（markdown+citations 绑定
  item）、DT-4（重试耗尽→FAILED 废稿留痕；skip 语义）、AC-20.4（topic_dedup 拒收）；
- 技术书 v1.7 §2 模块表（authors/gates 六门禁 [纯]、memory 记忆双轨、importer
  round-trip、writer 管线分派钩子）、§4.1 表结构（write_run payload=trace+rank 明细/
  prompt_snapshot 独立列/skip_reason/thinking/batch_id；article citations 引用绑定 item；
  memory_entry author_id/module/source_event；usage_log ref_type/ref_id）、§3（authors
  export 与导入 round-trip 一致 AC-10.1；import 同名=更新 200）、§4.4 记忆双轨（动态
  条目按量 recency 载入）、ADR-8（provider 计量落账依赖会话、messages 契约）；
- W4 demo 基线（验证报告 20260928：阅读集正文/ISO 日期/来源/人设进 prompt_snapshot
  逐字可核）、W5（write_run 按作者/模型归因）；gates.py/模块 docstring 契约（verdict
  统一形态、clean 口径=去脚注标记+空白归一化、句长标准差节奏指标、feedback 违规说明）。

网络纪律：FakeProvider/FakeOld 脚本化输出沿用 tests/test_author_pipeline.py 形态，
不真联网；生产代码零改动；空阅读集语义（F1 域）与可选字段显式 null 语义均不钉
（任务书 §4 边界）。
"""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest

import app.authors.gates as G
import app.authors.writer as wr
import app.rerank.registry as rank_registry_mod
from app.authors.importer import import_author_json, roundtrip_check
from app.authors.memory import fill_placeholders
from app.authors.schema import default_author_config
from app.models import Article, Author, Direction, HotBatch, Item, MemoryEntry, ScoreResult, WriteRun
from app.providers.base import ProviderError


# ---------- 基础夹具 ----------

@pytest.fixture()
def env(db_session):
    """1 方向 + 2 条目（passed，带发布时间/正文/来源）+ 无 JSON 作者基元。"""
    db = db_session
    db.add(Direction(id=1, name="AI 与软件工程", prompt="方向提示词P", threshold=60))
    i1 = Item(source_id=1, guid="g1", title="AI 写作实验",
              content_text="事实一：模型写出了完整的文章。",
              published_at=datetime(2026, 10, 1, 8, 0, 0),
              url="https://a.example/one")
    i2 = Item(source_id=1, guid="g2", title="软件工程观察",
              content_text="事实二：代码评审提高了质量。",
              published_at=datetime(2026, 10, 2, 9, 0, 0),
              url="https://a.example/two")
    db.add_all([i1, i2])
    db.commit()
    db.add_all([
        ScoreResult(item_id=i1.id, direction_id=1, quality_score=90, relevance_score=90,
                    band="high", reason="r", prompt_version=1, model="m", passed=True, status="OK"),
        ScoreResult(item_id=i2.id, direction_id=1, quality_score=85, relevance_score=85,
                    band="high", reason="r", prompt_version=1, model="m", passed=True, status="OK"),
    ])
    db.commit()
    return db, i1, i2


def _old_author(db, **kw):
    a = Author(name=kw.pop("name", "旧路线作者"), model=kw.pop("model", "test-model"), **kw)
    db.add(a)
    db.commit()
    return a


def _pairs(db):
    rows = db.query(Item, ScoreResult).join(ScoreResult, ScoreResult.item_id == Item.id).all()
    return [(it, sr) for it, sr in rows]


class FakeOld:
    """single 路线假 provider：捕获 messages 与计量形参（ADR-8 契约观测）。"""

    def __init__(self, db_arg, scripts):
        assert db_arg is not None  # provider 构造实参=请求级会话（ADR-8 计量落账）
        self.db_arg = db_arg
        self.scripts = list(scripts)
        self.calls = []

    def chat_json(self, messages, **kw):
        self.calls.append({"messages": messages, **kw})
        return self.scripts.pop(0), "fake-old-model"


def _write_payload(iid1, iid2, title="旧路线文章", body="正文内容充实。"):
    return {"decision": "write", "article": {
        "title": title, "body": body,
        "citations": [{"item_id": iid1, "quote": "事实一：模型写出了完整的文章。"},
                      {"item_id": iid2, "quote": "事实二：代码评审提高了质量。"}]},
        "reason": "r", "thinking": "t"}


# ---------- gates：Verdict 形态与 feedback ----------

def test_verdict_shape_and_feedback():
    """verdict 统一形态四键（gates docstring）+ 违规说明完整到达（AC-11.2 R6）。"""
    v = G.Verdict(passed=False, issues=["问题甲"], warns=["警示乙"], stats={"x": 1})
    d = v.to_dict()
    assert set(d) == {"passed", "issues", "warns", "stats"}
    assert d["passed"] is False and d["issues"] == ["问题甲"] and d["warns"] == ["警示乙"]
    fb = v.feedback()
    assert "问题甲" in fb and "警示乙" in fb and fb != "（无）"


# ---------- gates：length ----------

def test_gate_length_bounds_and_measured_chars():
    """length 门禁上下限判定（docs route 表 gates.length {min,max,unit:chars}）。"""
    v1 = G.Verdict()
    G.gate_length("字数不足的文本", {"min": 100, "max": 200}, v1)
    assert v1.issues                                 # 低于下限必须报（issues 非空即不通过）
    v2 = G.Verdict()
    G.gate_length("字" * 250, {"min": 100, "max": 200}, v2)
    assert v2.issues                                 # 超上限必须报
    v3 = G.Verdict()
    G.gate_length("他 说。", {"min": 0, "max": 1000}, v3)
    assert v3.stats["len_chars"] == 3                # clean 口径：空白不计入字数
    assert v3.issues == []


# ---------- gates：fingerprint ----------

def test_gate_fingerprint_hits():
    """指纹词命中语义（docs identity 表 style_rules.fingerprint + 六门禁[纯]）。"""
    words = ["铁十字", "荒谬"]
    v1 = G.Verdict()
    G.gate_fingerprint("他谈起铁十字与荒谬的战争。", words, 2, v1)
    assert v1.issues == []                            # 词全命中且达标 → 不拒
    v2 = G.Verdict()
    G.gate_fingerprint("完全不相关的内容。", words, 2, v2)
    assert v2.issues                                  # 零命中低于 min_hits → 拒


# ---------- gates：copyright ----------

BLOCK = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳"  # 16 字互异


def test_gate_copyright_detection_domain():
    """n-gram 复述检测域与 ≥2/1 处判定（AC-11.4 + gates docstring）。"""
    def run(body, blocks, ngram=8):
        v = G.Verdict()
        G.gate_copyright(body, blocks, ngram, v)
        return v
    # 恰 1 处重叠 → warn 不 issue
    v1 = run("开头段落。" + BLOCK[4:12] + "结尾段落。", [{"text": BLOCK}])
    assert v1.issues == [] and v1.warns and v1.passed is True
    # 恰 2 处重叠 → issue（命中数必须为 0，否则拒收）
    v2 = run(BLOCK[0:8] + "中断。" + BLOCK[8:16], [{"text": BLOCK}])
    assert v2.issues
    # 同一 gram 重复出现仍按 1 处计（去重口径）
    v3 = run(BLOCK[0:8] + "衔接。" + BLOCK[0:8], [{"text": BLOCK}])
    assert v3.issues == [] and v3.warns
    # 恰长 ngram 的块也参与检测
    b8 = "红橙黄绿青蓝紫黑"
    v4 = run("正文有。" + b8 + "。收尾", [{"text": b8}])
    assert v4.issues == [] and v4.warns
    # 块尾 gram 与正文尾 gram 均在检测域内
    v5 = run("前缀内容。" + BLOCK[8:16], [{"text": BLOCK}])
    assert v5.warns
    v6 = run("前缀内容。" + BLOCK[0:8], [{"text": BLOCK}])
    assert v6.warns
    # 短块跳过不得中断后续块遍历
    v7 = run("开头。" + BLOCK[0:8] + "。结尾", [{"text": "短文本"}, {"text": BLOCK}])
    assert v7.warns
    # 合法配置 ngram=2 仍检测
    v8 = run("文中写到甲乙二字。", [{"text": BLOCK}], ngram=2)
    assert v8.warns


# ---------- gates：topic_dedup ----------

def test_gate_topic_dedup_dice_semantics():
    """不相似选题不得判重（docstring Dice 相似度 + AC-20.4）；同题直接判重。"""
    v1 = G.Verdict()
    G.gate_topic_dedup("关于机器写作的三点观察", ["天气预报说明天有雨"], 0.55, v1)
    assert v1.issues == []
    v2 = G.Verdict()
    G.gate_topic_dedup("关于机器写作的三点观察", ["关于机器写作的三点观察"], 0.55, v2)
    assert v2.issues
    # 空白差异经归一化后视为同题（gates docstring 空白归一化口径）
    v3 = G.Verdict()
    G.gate_topic_dedup("甲乙丙 丁", ["甲乙丙丁"], 0.55, v3)
    assert v3.issues


# ---------- gates：clean 口径 + 节奏指标 ----------

def test_clean_pipeline_and_rhythm_metric():
    """去脚注标记+空白归一化的 clean 口径（gates docstring）与句长标准差（节奏指标）。"""
    draft = ("他是 作者。[^1]事实二。[^2]\n\n"
             "[^1]: [条目 1] 事实一定义\n"
             "[^2]: [条目 2] 事实二定义\n")
    v = G.Verdict()
    G.gate_length(draft, {"min": 0, "max": 1000}, v)
    assert v.stats["len_chars"] == 9   # 定义行/脚注标记/空白均不计入（"他是作者。事实二。"）
    assert v.issues == []
    # 空白差异不影响复述命中（空白归一化）
    block = "天空中的铁十字在燃烧着大地被炮火"
    v2 = G.Verdict()
    G.gate_copyright("开头。天空中的 铁十字在燃烧着大地被炮火。结尾。", [{"text": block}], 8, v2)
    assert v2.issues
    # 句长序列与标准差（round 1 位小数）
    t1 = "好。AB。三个字。四个字的句子来了。再来一句凑数吧。最后一个更长的句子结尾呀。"
    assert G.sentence_lengths(t1) == [2, 3, 8, 7, 12]
    assert G.rhythm_stddev(t1) == 3.6          # mean=6.4, var=13.04
    t2 = "丁一。丁二丁三。丁四丁五丁六。丁七丁八丁九丁十。天王盖地虎宝塔镇河妖。"
    assert G.rhythm_stddev(t2) == 2.8          # lens=[2,4,6,8,10], var=8
    assert G.rhythm_stddev("短句。太短。") is None   # 样本不足不产指标


# ---------- writer.assemble_reading_set ----------

def test_reading_set_filter_order_threshold(db_session):
    """装配语义：可读方向 + 阈值 + passed 过滤 + relevance 降序 top-K（docstring）。"""
    db = db_session
    db.add_all([
        Direction(id=2, name="其他方向", prompt="p2", threshold=60),
        Item(source_id=1, guid="e1", title="次高合格", content_text="e"),
        Item(source_id=1, guid="b1", title="低于阈值", content_text="b"),
        Item(source_id=1, guid="a1", title="最高合格", content_text="a"),
        Item(source_id=1, guid="d1", title="未通过评分", content_text="d"),
        Item(source_id=1, guid="c1", title="他向高分", content_text="c"),
    ])
    db.commit()
    its = {it.title: it.id for it in db.query(Item).all()}
    scores = [
        ("次高合格", 1, 86, True), ("低于阈值", 1, 88, True), ("最高合格", 1, 90, True),
        ("未通过评分", 1, 99, False), ("他向高分", 2, 95, True),
    ]
    for title, did, rel, passed in scores:
        db.add(ScoreResult(item_id=its[title], direction_id=did, quality_score=rel,
                           relevance_score=rel, band="high", reason="r", prompt_version=1,
                           model="m", passed=passed, status="OK"))
    db.commit()
    # 场景一（阈值语义）：阈值 89 只放行最高合格(90)，方向阈值过滤生效
    author1 = _old_author(db, name="阈值作者", readable_directions=[{"direction_id": 1, "threshold": 89}])
    pairs = wr.assemble_reading_set(db, author1, k=2)
    assert [it.id for it, _ in pairs] == [its["最高合格"]]
    assert all(sr.item_id == it.id for it, sr in pairs)                     # 条目-分数配对本体
    # 场景二（排序/过滤语义）：阈值 60 放行 3 条，k=1 取 relevance 最高者
    author2 = _old_author(db, name="排序作者", readable_directions=[{"direction_id": 1, "threshold": 60}])
    pairs2 = wr.assemble_reading_set(db, author2, k=1)
    assert [it.id for it, _ in pairs2] == [its["最高合格"]]


# ---------- writer.assemble_ranked_reading_set ----------

class FakeRank:
    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error
        self.seen = []

    def rank(self, criteria, candidates, criteria_key=None):
        self.seen.append({"criteria": criteria, "candidates": candidates, "criteria_key": criteria_key})
        if self.error:
            raise self.error
        return list(self.results)


def _R(item_id, score, band="high"):
    return SimpleNamespace(id=item_id, score=score, band=band, confidence=None, provider="fake")


def test_ranked_none_provider_meta_exact(env):
    """rank_provider=none：回退 relevance 且 meta 如实 = {"rank_provider":"none"}（docstring）。"""
    db, i1, i2 = env
    a1 = _old_author(db, readable_directions=[{"direction_id": 1, "threshold": 60}])
    pairs, meta = wr.assemble_ranked_reading_set(db, a1)
    assert meta == {"rank_provider": "none"}
    assert [it.id for it, _ in pairs] == [i1.id, i2.id]
    a2 = _old_author(db, name="空排序作者", rank_provider="",
                     readable_directions=[{"direction_id": 1, "threshold": 60}])
    _, meta2 = wr.assemble_ranked_reading_set(db, a2)
    assert meta2 == {"rank_provider": "none"}


def test_ranked_path_criteria_candidates_details(db_session, monkeypatch):
    """rank 契约：criteria=方向提示词、候选文本=标题+正文、明细逐字段（§4.1 rank 明细）。"""
    db = db_session
    db.add(Direction(id=1, name="AI 与软件工程", prompt="方向提示词P", threshold=60))
    db.add(Item(source_id=1, guid="rdummy", title="占位条目", content_text=""))  # 错开 item/score 行 id
    db.commit()
    ia = Item(source_id=1, guid="ra", title="标题甲", content_text="正文甲")
    ib = Item(source_id=1, guid="rb", title="标题乙", content_text="正文乙")
    ic = Item(source_id=1, guid="rc", title="标题丙", content_text=None)
    db.add_all([ia, ib, ic])
    db.commit()
    for it, rel in ((ia, 90), (ib, 85), (ic, 80)):
        db.add(ScoreResult(item_id=it.id, direction_id=1, quality_score=rel, relevance_score=rel,
                           band="high", reason="r", prompt_version=1, model="m", passed=True, status="OK"))
    db.commit()
    author = _old_author(db, rank_provider="fake_rank", rank_exclude_below=30,
                         readable_directions=[{"direction_id": 1, "threshold": 60}])
    fake = FakeRank(results=[_R(ia.id, 90, "high"), _R(ib.id, 10, "low")])
    monkeypatch.setattr(rank_registry_mod, "_registry", {"fake_rank": lambda _db: fake})
    pairs, meta = wr.assemble_ranked_reading_set(db, author)
    assert [it.id for it, _ in pairs] == [ia.id]          # 丙无明细跳过；乙低于排除线
    d = db.get(Direction, 1)
    call = fake.seen[0]
    assert call["criteria"] == d.prompt                   # criteria=方向提示词
    assert call["criteria_key"] == d.name                 # criteria_key=方向名
    assert [c.text for c in call["candidates"]] == ["标题甲\n正文甲", "标题乙\n正文乙", "标题丙\n"]
    assert meta["rank_provider"] == "fake_rank"
    assert meta["details"] == [                           # rank 明细逐字段
        {"item_id": ia.id, "score": 90, "band": "high", "relevance": 90},
        {"item_id": ib.id, "score": 10, "band": "low", "relevance": 85},
    ]
    assert isinstance(meta["latency_ms"], int)


def test_ranked_fallback_keeps_reading_set(db_session, monkeypatch):
    """排序失败/全排除 → 回退 relevance 不丢阅读集 + 失败如实记录（docstring）。"""
    db = db_session
    db.add(Direction(id=1, name="AI 与软件工程", prompt="P", threshold=60))
    i1 = Item(source_id=1, guid="f1", title="甲", content_text="甲甲")
    i2 = Item(source_id=1, guid="f2", title="乙", content_text="乙乙")
    db.add_all([i1, i2])
    db.commit()
    for it, rel in ((i1, 90), (i2, 85)):
        db.add(ScoreResult(item_id=it.id, direction_id=1, quality_score=rel, relevance_score=rel,
                           band="high", reason="r", prompt_version=1, model="m", passed=True, status="OK"))
    db.commit()
    author = _old_author(db, rank_provider="fake_rank",
                         readable_directions=[{"direction_id": 1, "threshold": 60}])
    boom = FakeRank(error=__import__("app.rerank.base", fromlist=["RankError"]).RankError("排序boom失败"))
    monkeypatch.setattr(rank_registry_mod, "_registry", {"fake_rank": lambda _db: boom})
    pairs, meta = wr.assemble_ranked_reading_set(db, author)
    assert [it.id for it, _ in pairs] == [i1.id, i2.id]   # 回退不丢阅读集
    assert "boom" in (meta.get("rank_error") or "")       # 失败原因如实记录
    low = FakeRank(results=[_R(i1.id, 5, "low"), _R(i2.id, 5, "low")])
    monkeypatch.setattr(rank_registry_mod, "_registry", {"fake_rank": lambda _db: low})
    pairs2, _ = wr.assemble_ranked_reading_set(db, author)
    assert [it.id for it, _ in pairs2] == [i1.id, i2.id]  # 全被排除 → 回退而非清空


# ---------- writer._render_reading_set ----------

def test_render_reading_set_facts():
    """阅读集渲染事实逐字可核（W4）：正文/ISO 日期/来源/缺省形态。"""
    it1 = SimpleNamespace(id=11, title="标题甲", content_text="正文内容甲乙丙",
                          published_at=datetime(2026, 10, 1, 8, 0, 0), url="https://a.example/x")
    sr1 = SimpleNamespace(relevance_score=90)
    it2 = SimpleNamespace(id=12, title="标题乙", content_text=None,
                          published_at=None, url=None)
    sr2 = SimpleNamespace(relevance_score=70)
    text = wr._render_reading_set([(it1, sr1), (it2, sr2)])
    assert "【条目 11】标题甲" in text
    assert "来源: https://a.example/x" in text
    assert "发布: 2026-10-01" in text                      # ISO 日期
    assert "正文: 正文内容甲乙丙" in text
    assert "发布: 未知" in text                            # 缺日期缺省形态
    assert "来源: 未知" in text                            # 缺来源缺省形态
    assert "正文: （无正文）" in text                      # 缺正文缺省形态
    assert "相关分: 90" in text and "相关分: 70" in text


# ---------- writer._build_prompt / _hot_brief ----------

def test_prompt_placeholder_assembly(env):
    """占位符装配契约（writer docstring + W4）：人设/全局/记忆/热点/阅读集全部注入。"""
    db, i1, i2 = env
    db.add(HotBatch(date="2026-10-04", keywords=["关键词甲", "关键词乙"], summary="综述内容丙",
                    source_platforms=[], model=""))
    db.commit()
    author = _old_author(db, persona_prompt="人设标记ABC", global_system_prompt="全局标记DEF",
                         memory_config={"topic_memory": 3}, include_hot_brief=True)
    db.add(MemoryEntry(author_id=author.id, module="topic", content="选题记忆内容Z", source_event="write"))
    db.commit()
    text = wr._build_prompt(db, author, _pairs(db))
    assert author.name in text and "{{author_name}}" not in text
    assert "人设标记ABC" in text and "{{persona_prompt}}" not in text
    assert "全局标记DEF" in text and "{{global_system_prompt}}" not in text
    assert "选题记忆内容Z" in text and "{{topic_memory}}" not in text
    assert "关键词甲" in text and "综述内容丙" in text and "{{hot_brief}}" not in text
    assert "【条目" in text and "{{reading_set}}" not in text


def test_prompt_no_persona_no_garbage(env):
    """无人设/无全局提示的作者占位符仍被替换为空（不留 XXXX 残渣）。"""
    db, i1, i2 = env
    author = _old_author(db, persona_prompt=None, global_system_prompt=None)
    text = wr._build_prompt(db, author, _pairs(db))
    assert "XXXX" not in text


def test_hot_brief_latest_batch_and_empty(env):
    """热点风向=最新批次（docstring「本期」）；无批次/未开启不注入。"""
    db, i1, i2 = env
    db.add(HotBatch(date="2026-10-03", keywords=["旧关键词"], summary="旧综述", source_platforms=[], model=""))
    db.add(HotBatch(date="2026-10-04", keywords=["新关键词"], summary="新综述内容", source_platforms=[], model=""))
    db.commit()
    author = _old_author(db, include_hot_brief=True)
    brief = wr._hot_brief(db, author)
    assert "新关键词" in brief and "新综述内容" in brief     # 本期=最新批次（id 降序）
    # 无任何批次 → 空串（不注入垃圾占位）
    db.query(HotBatch).delete()
    db.commit()
    assert wr._hot_brief(db, author) == ""
    # 未开启 → 不注入
    author2 = _old_author(db, name="未开启作者", include_hot_brief=False)
    db.add(HotBatch(date="2026-10-04", keywords=["词"], summary="综述", source_platforms=[], model=""))
    db.commit()
    text3 = wr._build_prompt(db, author2, _pairs(db))
    assert "【本期全网热点风向" not in text3


# ---------- writer._parse_output ----------

def test_parse_output_accepts_skip_and_write():
    """decision ∈ write|skip（AC-11.5/DT-4）：skip 与 write 均合法放行。"""
    data = {"decision": "skip", "reason": "r", "thinking": "t"}
    assert wr._parse_output(data) is data
    wdata = {"decision": "write", "article": {}}
    assert wr._parse_output(wdata) is wdata
    from app.providers.base import JSONParseError
    with pytest.raises(JSONParseError):
        wr._parse_output({"decision": "publish"})


# ---------- writer.run_write：分派语义（M14） ----------

def _cfg(db):
    cfg = default_author_config("c17_t", "管线分派作者")
    cfg["route"]["gates"]["length"] = {"min": 20, "max": 5000, "unit": "chars"}
    cfg["route"]["gates"]["citation"] = {"min_count": 1}
    return cfg


def _make_draft(iid1):
    return ("# 分派测试成文标题\n\n他说要写一篇文章。事实一。[^1]\n\n"
            f"[^1]: [条目 {iid1}] 事实一\n")


def test_single_dispatch_to_pipeline(env, monkeypatch):
    """有 author_json 走 JSON 管线，全部运行时参数透传（docstring 分派语义 + W5 + §4.1）。"""
    import app.authors.pipeline as pl

    db, i1, i2 = env
    author = import_author_json(db, _cfg(db), model="test-model",
                                readable_directions=[{"direction_id": 1, "threshold": 60}])
    fake = FakeProviderPipeline({"w_draft": [_make_draft(i1.id)]})
    monkeypatch.setattr(pl, "DeepSeekProvider", lambda _db: fake)
    overrides = {"gates": {"length": {"min": 20, "max": 5000, "unit": "chars"}}}
    run = wr.run_write(db, author, triggered_by="test", model="explicit-m", batch_id=7,
                       reading_window=(0, 1), route_overrides=overrides)
    assert run.status == "OK" and run.decision == "WRITE"
    assert "trace" in run.payload                          # 管线语义（非 single 落库形状）
    assert run.triggered_by == "test"                      # W5 归因
    assert run.model == "explicit-m"                       # W5 model 归因
    assert run.payload["batch_id"] == 7                    # §4.1 batch_id
    assert run.payload["reading_window"] == {"offset": 0, "k": 1}
    assert run.payload["route"]["overrides"] == overrides  # route_overrides 到达管线
    snap = run.prompt_snapshot
    assert f"【条目 {i1.id}】" in snap and f"【条目 {i2.id}】" not in snap  # 窗口切片生效（W4）


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


# ---------- writer.run_write：single 路线落库形状 ----------

def test_single_route_e2e_row_shape(env, monkeypatch):
    """single 路线 write_run/article/记忆落库形状（§4.1 + W4/W5 + AC-11.6 + ADR-8）。"""
    db, i1, i2 = env
    author = _old_author(db, readable_directions=[{"direction_id": 1, "threshold": 60}],
                         memory_config={"topic_memory": 2})
    fake = FakeOld(db, [_write_payload(i1.id, i2.id)])

    def recorder(db_arg):
        assert db_arg is db            # provider 构造实参=请求级会话（ADR-8 计量落账）
        return fake

    monkeypatch.setattr(wr, "DeepSeekProvider", recorder)
    run = wr.run_write(db, author, triggered_by="test")
    assert run.status == "OK" and run.decision == "WRITE"
    assert run.triggered_by == "test"
    assert run.reading_set_item_ids == [i1.id, i2.id]      # 阅读集落库
    assert run.payload == {"rank_provider": "none"}        # rank_meta 如实（none 路线）
    assert run.model == "fake-old-model"
    # messages 契约与计量归因（ADR-8 + AC-11.6）
    call = fake.calls[0]
    assert [m["role"] for m in call["messages"]] == ["system", "user"]
    assert call["model"] == "test-model"
    assert call["call_point"] == "writing"
    assert call["ref_type"] == "author" and call["ref_id"] == author.id
    # 快照完整：system 段 + user 段（W4）
    snap = run.prompt_snapshot
    assert snap.startswith(call["messages"][0]["content"])
    assert snap.endswith(call["messages"][1]["content"])
    assert "---USER---" in snap
    # article 落库（§4.1 + W1）
    article = db.get(Article, run.article_id)
    assert article.title == "旧路线文章"
    assert article.body == "正文内容充实。"
    assert article.citations[0]["item_id"] == i1.id and len(article.citations) == 2
    assert article.status == "PUBLISHED_TO_C"
    # topic 记忆沉淀（§4.4 动态条目）
    entry = db.query(MemoryEntry).filter_by(author_id=author.id).one()
    assert entry.module == "topic" and entry.source_event == "write"
    assert "旧路线文章" in entry.content and f"阅读集条目 {i1.id}" in entry.content
    # article 缺 body → 空串落库（不得注入垃圾占位）
    fake2 = FakeOld(db, [{"decision": "write", "article": {
        "title": "无正文文章",
        "citations": [{"item_id": i1.id, "quote": "事实一：模型写出了完整的文章。"}]},
        "reason": "r", "thinking": "t"}])
    monkeypatch.setattr(wr, "DeepSeekProvider", lambda _db: fake2)
    author3 = _old_author(db, name="无正文作者",
                          readable_directions=[{"direction_id": 1, "threshold": 60}])
    run2 = wr.run_write(db, author3, triggered_by="test")
    assert run2.status == "OK"
    assert db.get(Article, run2.article_id).body == ""


def test_single_route_skip_card(env, monkeypatch):
    """不写判定：SKIP + reason/thinking=模型原始输出（AC-11.5 + DT-4）。"""
    db, i1, i2 = env
    author = _old_author(db, readable_directions=[{"direction_id": 1, "threshold": 60}])
    fake = FakeOld(db, [{"decision": "skip", "reason": "素材不足R", "thinking": "思考内容T"}])
    monkeypatch.setattr(wr, "DeepSeekProvider", lambda _db: fake)
    run = wr.run_write(db, author, triggered_by="test")
    assert run.decision == "SKIP" and run.status == "OK"
    assert run.skip_reason == "素材不足R" and run.skip_thinking == "思考内容T"
    assert run.article_id is None
    # 缺 reason/thinking 键 → 空串（不是垃圾占位）
    fake2 = FakeOld(db, [{"decision": "skip"}])
    monkeypatch.setattr(wr, "DeepSeekProvider", lambda _db: fake2)
    run2 = wr.run_write(db, author, triggered_by="test")
    assert run2.decision == "SKIP"
    assert run2.skip_reason == "" and run2.skip_thinking == ""
    assert "XXXX" not in (run2.skip_reason or "") and "XXXX" not in (run2.skip_thinking or "")


def test_single_route_retry_semantics(env, monkeypatch):
    """重试一次语义 + 失败留痕（writer docstring「重试一次，二次失败落 FAILED」+ DT-5）。
    注：以 JSONParseError 耗尽为观测路径——CitationError 耗尽在 Demo 现行实现下
    不走 FAILED（data 已在解析后绑定），该偏差见执行汇报 §3 备案，本测试不钉。"""
    from app.providers.base import JSONParseError

    db, i1, i2 = env
    author = _old_author(db, readable_directions=[{"direction_id": 1, "threshold": 60}])

    class BadJSONOld(FakeOld):
        def chat_json(self, messages, **kw):
            self.calls.append({"messages": messages, **kw})
            raise JSONParseError("输出不是合法 JSON")

    fake = BadJSONOld(db, [])
    monkeypatch.setattr(wr, "DeepSeekProvider", lambda _db: fake)
    run = wr.run_write(db, author, triggered_by="test")
    assert len(fake.calls) == 2                            # 恰重试一次
    assert run.status == "FAILED" and run.article_id is None
    assert "JSONParseError" in (run.error or "")           # 失败留痕含类型与原因


def test_single_route_provider_error_failed(env, monkeypatch):
    """ProviderError 逃逸路径：write_run 落 FAILED（writer docstring + ADR-8）。"""
    db, i1, i2 = env
    author = _old_author(db, readable_directions=[{"direction_id": 1, "threshold": 60}])

    class BoomOld(FakeOld):
        def chat_json(self, messages, **kw):
            raise ProviderError("HTTP 500: provider down")

    fake = BoomOld(db, [])
    monkeypatch.setattr(wr, "DeepSeekProvider", lambda _db: fake)
    with pytest.raises(ProviderError):
        wr.run_write(db, author, triggered_by="test")
    db.expire_all()
    last = db.query(WriteRun).order_by(WriteRun.id.desc()).first()
    assert last.status == "FAILED" and last.author_id == author.id


def test_single_route_citation_guard(env, monkeypatch):
    """引用硬校验不可绕过：集外 item 拒收 + 拒收说明到达重试消息（AC-11.3 + writer docstring）。"""
    db, i1, i2 = env
    author = _old_author(db, readable_directions=[{"direction_id": 1, "threshold": 60}])
    fake = FakeOld(db, [_write_payload(i1.id, 99999), _write_payload(i1.id, i2.id)])
    monkeypatch.setattr(wr, "DeepSeekProvider", lambda _db: fake)
    run = wr.run_write(db, author, triggered_by="test")
    assert len(fake.calls) == 2                            # 首稿被拒 → 恰重试一次
    assert run.status == "OK"                              # 重试后合规放行
    assert db.get(Article, run.article_id).citations[0]["item_id"] == i1.id
    # 重试消息：roles 契约（ADR-8）+ 违规原因原样附上（writer docstring「附违规说明」）
    retry_msgs = fake.calls[1]["messages"]
    assert [m["role"] for m in retry_msgs] == ["system", "user", "assistant", "user"]
    assert all(set(m) == {"role", "content"} for m in retry_msgs)   # ADR-8 messages 契约
    assert "99999" in retry_msgs[3]["content"]


# ---------- importer ----------

def test_import_same_name_update_runtime_binding(db_session):
    """同名=更新（技术书 §3 200 语义）+ 运行时绑定未传保留原值（importer docstring）。"""
    db = db_session
    cfg = default_author_config("c17_imp", "同名导入作者甲")
    a1 = import_author_json(db, cfg, model="m1",
                            readable_directions=[{"direction_id": 1, "threshold": 60}],
                            rank_provider="rp1")
    cfg2 = default_author_config("c17_imp", "同名导入作者甲")
    cfg2["identity"]["description"] = "第二次导入的描述"
    a2 = import_author_json(db, cfg2, model="m2")
    assert a2.id == a1.id                                   # upsert 不新建
    assert db.query(Author).filter_by(name="同名导入作者甲").count() == 1
    assert a2.model == "m2"                                 # 显式传入覆盖
    assert a2.rank_provider == "rp1"                        # 未传入保留原值
    a3 = import_author_json(db, cfg2, model="m2", rank_provider="rp2")
    assert a3.id == a1.id and a3.rank_provider == "rp2"     # 显式传入覆盖


def test_import_dynamic_modules_key_mapping(db_session):
    """dynamic_modules → memory_config 占位符键归一（§4.4 + memory 占位符约定）。"""
    db = db_session
    cfg = default_author_config("c17_imp2", "动态模块作者")
    cfg["memory"]["dynamic_modules"] = {"topic": 3, "writing_memory": 2}
    author = import_author_json(db, cfg, model="m1")
    assert author.memory_config == {"topic_memory": 3, "writing_memory": 2}


def test_roundtrip_check_consistency(db_session):
    """round-trip 一致性判定（AC-10.1/技术书 §3）：一致无差异，差异必检出。"""
    db = db_session
    cfg = default_author_config("c17_rt", "往返作者")
    author = import_author_json(db, cfg, model="m1")
    ok, diffs = roundtrip_check(author, cfg)
    assert ok is True and diffs == []
    bad = deepcopy(cfg)
    bad["identity"]["description"] = "改动过的描述"
    ok2, diffs2 = roundtrip_check(author, bad)
    assert ok2 is False and len(diffs2) >= 1
    missing = deepcopy(cfg)
    del missing["output"]                                   # 原文件缺键 → DB 多出
    ok3, diffs3 = roundtrip_check(author, missing)
    assert ok3 is False and len(diffs3) >= 1


# ---------- memory ----------

def test_memory_placeholder_scoped_recent_limited(db_session):
    """动态条目：按作者隔离 + recency 取最新 N 条（§4.4 + memory_entry 表归属）。"""
    db = db_session
    a = _old_author(db, name="记忆作者甲", memory_config={"topic_memory": 2})
    b = _old_author(db, name="记忆作者乙")
    for content in ("选题记忆一E1", "选题记忆二E2", "选题记忆三E3"):
        db.add(MemoryEntry(author_id=a.id, module="topic", content=content, source_event="write"))
    db.add(MemoryEntry(author_id=a.id, module="feedback", content="反馈内容F", source_event="feedback"))
    db.add(MemoryEntry(author_id=b.id, module="topic", content="他人内容H", source_event="write"))
    db.commit()
    out = fill_placeholders(db, a, "前缀{topic_memory}后缀")
    assert "选题记忆三E3" in out and "选题记忆二E2" in out   # 最新 2 条
    assert "选题记忆一E1" not in out                          # 载入量控制
    assert "反馈内容F" not in out                             # 模块隔离
    assert "他人内容H" not in out                             # 作者隔离
