"""C1-5b 变异分诊批次 7 补强测试（authors.pipeline 模块级函数 431 条幸存变异体
分诊后 135 条新增 C 类的关闭测试；另 17 条 C 已由既有测试闭合）。

断言全部来自设计书条款：
- 产品书 v1.6 / 需求稿 v2.6 §4.4 记忆双轨：写作记忆与素材注入全部预算化
  （占位符载入量控制）、静态块注入内容进 prompt；
- W4 demo 基线（验证报告 20260928）：static_injection 硬预算（恰 n 片 × ≤per 字，
  截断如实记录 truncated）、切片与阅读集在 prompt_snapshot 逐字可核、round_robin
  相位 = 历史 run 数轮换、引用护栏不绕过（改写引文被拦 + 附原句提示修复）；
- W5 demo 基线：write_run 按作者/模型归因（model 列）；
- US-10 author.json schema：injection.selection/position、gates.length/topic_dedup
  .recent_n、route.passes、DRAFT_MODES（键名即参数契约）；
- US-11 AC-11.1（路线按 JSON 执行）、AC-11.2（门禁拒收、失败留痕）、AC-11.3
  （引用硬校验：编号↔定义 1:1、item 在阅读集内、quote 逐字、改写即拒）；
- US-12 AC-12.1（markdown 落库 + [^nK] 脚注双轨）；ADR-7②（HTML 转义渲染纪律）；
- 技术书 v1.7 §4.1 write_run 行：payload(trace + static_injection + rank 明细)、
  prompt_snapshot 独立列、status/error 失败留痕、triggered_by/model 归因列；
- ADR-8（provider 调用失败留痕）；搭建记录 §36（route_overrides 仅本次执行生效、
  不回写 author_json）。

网络纪律：FakeProvider 脚本化输出沿用 tests/test_author_pipeline.py 的 calls 捕获
形态，不真联网；生产代码零改动；不触碰空阅读集路径的状态枚举语义（DT-4 拍板
随 F1 改实现，本批不钉 SKIP/FAILED——任务书 §2）。
"""
import json
import re
from datetime import datetime
from types import SimpleNamespace

import pytest

import app.authors.pipeline as pl
from app.authors.importer import import_author_json
from app.authors.schema import default_author_config
from app.models import Article, Author, Item, ScoreResult, WriteRun
from app.providers.base import ProviderError


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

    def chat_json(self, messages, **kw):  # 兼容 single 路线分派
        raise AssertionError("管线作者不应走 single 路线")


def make_draft_text(item1: int, item2: int, title: str = "关于机器写作的三点观察"):
    return (
        f"# {title}\n\n他说要写一篇文章。事实一。[^1]事实二。[^2]\n\n"
        f"[^1]: [条目 {item1}] 事实一\n"
        f"[^2]: [条目 {item2}] 事实二\n"
    )


BAD_DRAFT = "# 废稿标题\n\n一段没有引用的正文。"


@pytest.fixture()
def env(db_session):
    """1 方向 + 2 条目（passed，带发布时间与正文）基础环境。"""
    from app.models import Direction

    db = db_session
    db.add(Direction(id=1, name="AI 与软件工程", prompt="p", threshold=60))
    i1 = Item(source_id=1, guid="g1", title="AI 写作实验",
              content_text="事实一：模型写出了完整的文章。",
              published_at=datetime(2026, 10, 1, 8, 0, 0))
    i2 = Item(source_id=1, guid="g2", title="软件工程观察",
              content_text="事实二：代码评审提高了质量。",
              published_at=datetime(2026, 10, 2, 9, 0, 0))
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


def base_config(name="分诊批次七作者"):
    cfg = default_author_config("c15b_t", name)
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


def _inj_cfg(blocks: list, *, n: int, per: int, selection: str) -> dict:
    return {"memory": {"static_blocks": blocks,
                       "injection": {"max_slices_per_run": n, "per_block_max_chars": per,
                                     "selection": selection, "position": "head"}}}


# ---------- _static_injection：硬预算/截断/记录（§4.4 预算化 + W4 + 搭建记录） ----------

def test_injection_hard_budget_boundaries(db_session):
    """硬预算逐块生效与如实记录：per 覆写截断、恰 n 块、边界块不误标、记录可核。"""
    blocks = [{"id": "b1", "text": "甲" * 200, "source": "s1"},
              {"id": "b2", "text": "乙" * 100, "source": "s2"}]  # b2 恰等于 per=100
    # per=100 配置真实生效：200 字块截到 100、100 字块不截（W4 硬预算 × per 块）
    out, rec = pl._static_injection(None, None, _inj_cfg(blocks, n=2, per=100,
                                                         selection="recency"), [])
    assert out[0]["text"] == "甲" * 100            # 超长截断到 per
    assert out[1]["text"] == "乙" * 100
    assert rec[0]["truncated"] is True and rec[0]["chars"] == 100   # 截断如实记录
    assert rec[1]["truncated"] is False                             # 恰等边界不算截断
    assert rec[0]["block_id"] == "b1" and rec[1]["block_id"] == "b2"  # 记录指向真实块 id
    # n=0：零注入（硬预算上界为 0 即不注入）
    out0, rec0 = pl._static_injection(None, None, _inj_cfg(blocks, n=0, per=100,
                                                           selection="recency"), [])
    assert out0 == [] and rec0 == []
    # n=1：恰 1 块
    out1, _ = pl._static_injection(None, None, _inj_cfg(blocks, n=1, per=100,
                                                        selection="recency"), [])
    assert len(out1) == 1 and out1[0]["text"] == "乙" * 100  # recency 取末块


def test_injection_selection_recency_tail():
    """selection=recency 取列表末尾 N 块（US-10 selection 枚举 + 搭建记录静态块注入）。"""
    blocks = [{"id": f"b{i}", "text": f"片段{i}号的内容", "source": "s"} for i in range(4)]
    out, rec = pl._static_injection(None, None, _inj_cfg(blocks, n=2, per=500,
                                                         selection="recency"), [])
    assert [o["text"] for o in out] == ["片段2号的内容", "片段3号的内容"]  # 末尾 2 块
    assert [r["block_id"] for r in rec] == ["b2", "b3"]


def test_injection_selection_relevant_bigram_metric():
    """selection=relevant 按与阅读集标题的字符 bigram 重叠取前 N（搭建记录：零 LLM 成本）。

    计分必须真实来自标题 bigram：无关块排前也不得逆转选取；首个/末个/恰 2 字命中
    均须计分；计分源只能是标题（不得混入非标题 token）。
    """
    def pick(blocks, titles):
        pairs = [(SimpleNamespace(id=i + 1, title=t), None) for i, t in enumerate(titles)]
        out, _ = pl._static_injection(None, None, _inj_cfg(blocks, n=1, per=500,
                                                           selection="relevant"), pairs)
        return out[0]["text"]

    # 无关块排第一、相关块排第二：必须按重叠分选相关块（防止稳定排序假阳性）
    assert "甲乙" in pick([{"id": "w", "text": "完全无关的内容"},
                           {"id": "j", "text": "甲乙相关内容"}], ["甲乙议题观察"])
    # 仅首 bigram 命中（甲乙 在块首）也须计分
    assert "甲乙" in pick([{"id": "w", "text": "完全无关的内容"},
                           {"id": "j", "text": "甲乙无关内容"}], ["甲乙议题观察"])
    # 仅末 bigram 命中（甲乙 在块尾）也须计分
    assert "甲乙" in pick([{"id": "w", "text": "完全无关的内容"},
                           {"id": "j", "text": "无关内容甲乙"}], ["甲乙议题观察"])
    # 恰 2 字块（只有 1 个 bigram）须参与计分
    assert "甲乙" in pick([{"id": "w", "text": "完全无关的内容"},
                           {"id": "j", "text": "甲乙"}], ["甲乙议题观察"])
    # 无 gram 短块不得靠兜底分逆转选取（空 gram 块计 0 分）
    assert "甲乙" in pick([{"id": "s", "text": "短"},
                           {"id": "j", "text": "甲乙无关内容"}], ["甲乙议题观察"])
    # 计分源不得混入非标题 token：垃圾 token 拼进标题不得改变选取
    assert "甲乙" in pick([{"id": "x", "text": "x丙组块的内容"},
                           {"id": "j", "text": "甲乙相关内容"}], ["甲乙议题", "丙丁议题"])
    # 空标题条目：不得给标题贡献垃圾 token（计分源仍为空）
    assert "甲乙" in pick([{"id": "j", "text": "甲乙相关内容"},
                           {"id": "x", "text": "xx组块的内容"}], [None])


def test_injection_selection_round_robin_phase(db_session):
    """round_robin 相位 = 该作者历史 WriteRun 数（W4：批跑中切片组合真实轮换），
    且只数本作者的 run（不混入其他作者）。"""
    db = db_session
    author = Author(name="轮转作者", model="m",
                    readable_directions=[{"direction_id": 1, "threshold": 60}])
    other = Author(name="别家作者", model="m")
    db.add_all([author, other])
    db.flush()
    db.add(WriteRun(author_id=author.id, model="m"))          # 本作者相位 1
    db.add_all([WriteRun(author_id=other.id, model="m"), WriteRun(author_id=other.id, model="m")])
    db.commit()
    blocks = [{"id": f"b{i}", "text": f"互不相同的片段第{i}号", "source": "s"} for i in range(4)]
    out, rec = pl._static_injection(db, author, _inj_cfg(blocks, n=2, per=500,
                                                         selection="round_robin"), [])
    assert [o["text"] for o in out] == ["互不相同的片段第1号", "互不相同的片段第2号"]  # 相位=1 轮转
    assert [r["block_id"] for r in rec] == ["b1", "b2"]


# ---------- _recent_titles：recent_n 窗口语义（US-10 gates.topic_dedup + AC-11.2） ----------

def test_recent_titles_latest_n_window(db_session):
    """近期标题 = 按 id 倒序取最近 n 条（AC-11.2 同题判重窗口的取数语义）。"""
    db = db_session
    author = Author(name="近期作者", model="m")
    db.add(author)
    db.flush()
    for i, t in enumerate(["同题旧文", "中间文章甲", "中间文章乙", "最新文章丙"]):
        db.add(Article(author_id=author.id, title=t, body="x", citations=[],
                       status="PUBLISHED_TO_C"))
    db.commit()
    assert pl._recent_titles(db, author, 2) == ["最新文章丙", "中间文章乙"]  # 最近 2 条
    assert pl._recent_titles(db, author, 1) == ["最新文章丙"]                # n=1 恰 1 条
    assert pl._recent_titles(db, author, 0) == []                            # n=0 不取


# ---------- _refs_listing：阅读集逐字可核（W4） ----------

def test_reading_set_bodies_and_dates_in_snapshot(db_session, env):
    """阅读集条目正文与发布信息进 prompt_snapshot 逐字可核（W4：阅读集逐字可核）。"""
    db, i1, i2 = env
    cfg = base_config()
    author = _author(db, cfg)
    fake = FakeProvider({"w_draft": [make_draft_text(i1, i2)]})
    run = _run_e2e(db, author, fake)
    assert run.status == "OK"
    snap = run.prompt_snapshot
    assert "事实一：模型写出了完整的文章。" in snap   # 条目正文逐字可核（引用溯源前提）
    assert "事实二：代码评审提高了质量。" in snap
    assert "2026-10-01" in snap                        # 发布日期事实逐字可核（ISO 日期进阅读集）
    assert "AI 写作实验" in snap and "软件工程观察" in snap


# ---------- _identity_system：identity 配置进 system prompt（ADR-8 + 人格卡事实性） ----------

def test_identity_rules_reach_system_prompt(db_session, env):
    """style_rules.do/dont 与 quotes_original 非空时管线可用且条目进 system 消息
    （人格卡整体注入，语义对齐 lab persona_system_v3——模块 docstring）。"""
    db, i1, i2 = env
    cfg = base_config()
    cfg["identity"]["style_rules"]["do"] = ["每天步行三十分钟"]
    cfg["identity"]["style_rules"]["dont"] = ["不写排比句"]
    cfg["identity"]["quotes_original"] = ["天下大事必作于细"]
    author = _author(db, cfg)
    fake = FakeProvider({"w_draft": [make_draft_text(i1, i2)]})
    run = _run_e2e(db, author, fake)
    assert run.status == "OK"
    system = fake.calls[0]["messages"][0]["content"]
    assert fake.calls[0]["messages"][0]["role"] == "system"
    assert "每天步行三十分钟" in system   # do 条目事实进人格卡
    assert "不写排比句" in system          # dont 条目事实进人格卡
    assert "天下大事必作于细" in system    # 自我引句进人格卡


# ---------- run_pipeline_write：route_overrides 契约（搭建记录 §36） ----------

def test_route_overrides_merge_and_no_writeback(db_session, env):
    """route_overrides：深合并进 route 后重新校验，仅本次执行生效、不回写 author_json
    （搭建记录 M17：批跑对照用 route_overrides）。dict 对 dict 深合并；dict 对列表
    整体替换。"""
    db, i1, i2 = env
    cfg = base_config()
    cfg["route"]["passes"] = [{"type": "rhythm", "params": {}}]
    author = _author(db, cfg)
    fake = FakeProvider({"w_incubate": [json.dumps({"theme": "核心之事", "chain": ["一", "二", "三"],
                                                    "opening_image": "起笔", "closing_line": "收束"},
                                                   ensure_ascii=False)],
                         "w_draft": [make_draft_text(i1, i2)],
                         "w_rhythm": [make_draft_text(i1, i2)],
                         "w_prune": [make_draft_text(i1, i2)]})
    # 场景一：dict 深合并（draft.mode single→incubate），本次生效
    run = _run_e2e(db, author, fake, route_overrides={"draft": {"mode": "incubate"}})
    assert run.status == "OK"
    assert "w_incubate" in [t["node"] for t in run.payload["trace"]]  # 覆写本次生效
    db.refresh(author)
    assert author.author_json["route"]["draft"]["mode"] == "single"   # 不回写 author_json
    assert author.author_json["route"]["passes"][0]["type"] == "rhythm"
    # 场景二：dict 值对列表键 = 整体替换（passes rhythm→prune），本次生效
    fake2 = FakeProvider({"w_draft": [make_draft_text(i1, i2)],
                          "w_prune": [make_draft_text(i1, i2, title="第二篇不同选题的文章观察")]})
    run2 = _run_e2e(db, author, fake2, route_overrides={"passes": [{"type": "prune", "params": {}}]})
    assert run2.status == "OK"
    assert [t["node"] for t in run2.payload["trace"]] == ["w_draft", "w_prune"]
    db.refresh(author)
    assert author.author_json["route"]["passes"][0]["type"] == "rhythm"  # 不回写
    # 场景三：dict 值对列表键 = 整体替换后重新校验失败 → 落 FAILED（不得崩溃）
    run3 = _run_e2e(db, author, FakeProvider({}), route_overrides={"passes": {"bad": 1}})
    assert run3.status == "FAILED" and run3.error


# ---------- run_pipeline_write：write_run 落库形状（§4.1 + W5） ----------

def test_config_error_failed_run_contract(db_session):
    """author.json 运行时校验失败：run 落 FAILED + 原因留痕 + 归因列齐全，
    零 provider 调用（§4.1 write_run 失败留痕 + W5 归因 + 成本纪律）。"""
    db = db_session
    author = Author(name="坏配置作者", model="cfgerr-model",
                    author_json={"id": "bad", "identity": {}})  # 缺 route/memory 等必填节
    db.add(author)
    db.commit()
    fake = FakeProvider({})
    orig = pl.DeepSeekProvider
    pl.DeepSeekProvider = lambda _db: fake
    try:
        run = pl.run_pipeline_write(db, author, triggered_by="test")  # 不传 model → 归因 author.model
    finally:
        pl.DeepSeekProvider = orig
    assert run.status == "FAILED"                      # 失败终态
    assert run.error                                   # 失败原因留痕
    assert run.author_id == author.id                  # 作者归因
    assert run.triggered_by == "test"                  # 触发来源归因
    assert run.model == "cfgerr-model"                 # 模型归因（W5）
    assert len(fake.calls) == 0                        # 校验失败零 LLM 调用


def test_run_row_payload_rank_and_triggered_by(db_session, env):
    """write_run payload 携带 rank 明细（§4.1：payload = trace + static_injection + rank 明细）、
    triggered_by 落列、provider 以请求会话构造（ADR-8 计量落账依赖会话）。"""
    db, i1, i2 = env
    cfg = base_config()
    author = _author(db, cfg)
    fake = FakeProvider({"w_draft": [make_draft_text(i1, i2)]})
    seen = {}
    orig = pl.DeepSeekProvider

    def recorder(db_arg):
        seen["db"] = db_arg
        return fake

    pl.DeepSeekProvider = recorder
    try:
        run = pl.run_pipeline_write(db, author, triggered_by="test")
    finally:
        pl.DeepSeekProvider = orig
    assert run.status == "OK"
    assert "rank" in run.payload and isinstance(run.payload["rank"], dict)  # §4.1 rank 明细
    assert run.triggered_by == "test"
    assert seen["db"] is db   # provider 构造实参 = 请求级会话（usage_log 记账）


def test_reading_window_slice_verifiable_in_snapshot(db_session, env):
    """reading_window 只把窗口内条目给作者（W4：snapshot 阅读集逐字可核；
    搭建记录 M17 批跑幂等签名含 window）。"""
    db, i1, i2 = env
    cfg = base_config()
    cfg["route"]["gates"]["citation"] = {"min_count": 1}
    author = _author(db, cfg)
    window_draft = ("# 窗口观察\n\n他说要写一篇较长的观察文章。事实一。[^1]\n\n"
                    f"[^1]: [条目 {i1}] 事实一\n")
    fake = FakeProvider({"w_draft": [window_draft]})
    run = _run_e2e(db, author, fake, reading_window=(0, 1))
    assert run.status == "OK"
    snap = run.prompt_snapshot
    assert f"【条目 {i1}】" in snap          # 窗口内条目在快照
    assert f"【条目 {i2}】" not in snap      # 窗口外条目不进快照


def test_json_abort_and_provider_error_leave_reason(db_session, env):
    """失败留痕（§4.1 status/error + AC-11.2 + ADR-8）：JSON 解析重试仍失败与
    provider 调用失败均落 FAILED + 原因。"""
    db, i1, i2 = env
    cfg = base_config()
    cfg["route"]["outline"]["template"] = "pyramid"
    author = _author(db, cfg)
    fake = FakeProvider({"w_outline": ["不是JSON", "还是不是JSON"]})
    run = _run_e2e(db, author, fake)
    assert run.status == "FAILED" and run.error          # 失败原因留痕
    fake2 = FakeProvider({})
    fake2.chat = lambda messages, **kw: (_ for _ in ()).throw(ProviderError("HTTP 500: boom"))
    run2 = _run_e2e(db, author, fake2)
    assert run2.status == "FAILED" and run2.error        # provider 失败原因留痕


# ---------- _citation_discipline / validate_citations_pipeline：引用链（AC-11.3 + W4） ----------

def test_citation_discipline_single_item_reading_set(db_session):
    """单条目阅读集可成文（引用纪律以真实条目构造示例——模块 docstring M15 实测）。"""
    from app.models import Direction

    db = db_session
    db.add(Direction(id=1, name="AI 与软件工程", prompt="p", threshold=60))
    it = Item(source_id=1, guid="g1", title="AI 写作实验",
              content_text="事实一：模型写出了完整的文章。")
    db.add(it)
    db.commit()
    db.add(ScoreResult(item_id=it.id, direction_id=1, quality_score=90, relevance_score=90,
                       band="high", reason="r", prompt_version="v1", model="m",
                       passed=True, status="OK"))
    db.commit()
    cfg = base_config()
    cfg["route"]["gates"]["citation"] = {"min_count": 1}
    author = _author(db, cfg)
    draft = ("# 单条目观察\n\n他说要写一篇很长的观察文章才行。事实一。[^1]\n\n"
             f"[^1]: [条目 {it.id}] 事实一\n")
    fake = FakeProvider({"w_draft": [draft]})
    run = _run_e2e(db, author, fake)
    assert run.status == "OK"   # 单条目阅读集不崩（成文 + 引用链完整）


def test_citation_gate_reject_contract():
    """引用硬校验契约（AC-11.3：编号↔定义 1:1、item 在阅读集内、quote 逐字命中、
    改写即拒；W4：被拦后修复附原句提示）。"""
    i1 = SimpleNamespace(id=11, content_text="事实一：模型写出了完整的文章。")
    i2 = SimpleNamespace(id=12, content_text="事实二：代码评审提高了质量。")
    short = SimpleNamespace(id=13, content_text="短句。")  # 无 ≥12 字句 → 无相近原句提示
    pairs = [(i1, SimpleNamespace(relevance_score=9)), (i2, SimpleNamespace(relevance_score=8)),
             (short, SimpleNamespace(relevance_score=7))]

    def defs_of(*ks):
        src = {11: "事实一", 12: "事实二", 13: "完全不同的引文内容"}
        return {n: (iid, src[iid]) for n, iid in enumerate(ks, start=1)}

    good = "# 题\n\n正文。[^1][^2]\n"
    # 合法引用放行
    pl.validate_citations_pipeline(good, defs_of(11, 12), pairs, 2)
    # 正文有标记、文末缺定义 → 拒收并说明缺定义行
    with pytest.raises(pl.CitationError, match="缺定义行"):
        pl.validate_citations_pipeline(good + "更多。[^3]", defs_of(11, 12), pairs, 2)
    # 文末有定义、正文无标记 → 拒收并说明无对应标记
    with pytest.raises(pl.CitationError, match="没有对应标记"):
        pl.validate_citations_pipeline("# 题\n\n正文。[^1]\n", defs_of(11, 12), pairs, 1)
    # 引用阅读集外条目 → 拒收（AC-11.3 对抗样本）
    with pytest.raises(pl.CitationError, match="不在阅读集"):
        pl.validate_citations_pipeline("# 题\n\n正文。[^1]\n", {1: (999, "事实一")}, pairs, 1)
    # quote 为空 → 拒收
    with pytest.raises(pl.CitationError, match="quote 为空"):
        pl.validate_citations_pipeline("# 题\n\n正文。[^1]\n", {1: (11, "")}, pairs, 1)
    # 改写引文 → 拒收，且错误信息附相近原句提示（W4 修复路径）
    rewritten = "# 题\n\n正文。[^1]\n"
    with pytest.raises(pl.CitationError) as ei:
        pl.validate_citations_pipeline(rewritten, {1: (11, "事实一，模型写出了文章")}, pairs, 1)
    assert "找不到" in str(ei.value)
    assert "相近的原句" in str(ei.value) and "请整句逐字复制" in str(ei.value)
    # 改写引文且无相近原句（条目正文过短）→ 仍拒收（不再附提示也不崩）
    with pytest.raises(pl.CitationError):
        pl.validate_citations_pipeline(rewritten, {1: (13, "完全不同的引文内容")}, pairs, 1)


# ---------- parse_footnote_defs：defs 以脚注编号为键（AC-11.3 编号↔定义 1:1） ----------

def test_footnote_defs_keyed_by_mark_number(db_session):
    """条目 id 与脚注编号错位时，定义行仍必须按 [^K] 编号索引（W5 [^nK] 脚注双轨：
    [^K]: [条目 <id>] 的 K 是编号、<id> 是条目——两键不得混用）。"""
    from app.models import Direction

    db = db_session
    db.add(Direction(id=1, name="AI 与软件工程", prompt="p", threshold=60))
    pad = Item(source_id=1, guid="pad", title="占位条目", content_text="占位正文。")
    db.add(pad)
    db.flush()                                  # 占位条目占走 id=1，真实条目从 2 起
    i1 = Item(source_id=1, guid="g1", title="AI 写作实验",
              content_text="事实一：模型写出了完整的文章。")
    i2 = Item(source_id=1, guid="g2", title="软件工程观察",
              content_text="事实二：代码评审提高了质量。")
    db.add_all([i1, i2])
    db.commit()
    db.add_all([
        ScoreResult(item_id=i1.id, direction_id=1, quality_score=90, relevance_score=90,
                    band="high", reason="r", prompt_version="v1", model="m", passed=True, status="OK"),
        ScoreResult(item_id=i2.id, direction_id=1, quality_score=85, relevance_score=85,
                    band="high", reason="r", prompt_version="v1", model="m", passed=True, status="OK"),
    ])
    db.commit()
    assert (i1.id, i2.id) == (2, 3)             # 错位前提：条目 id ≠ 脚注编号 1/2
    cfg = base_config()
    author = _author(db, cfg)
    draft = ("# 错位观察\n\n他说要写一篇文章。事实一。[^1]事实二。[^2]\n\n"
             f"[^1]: [条目 {i1.id}] 事实一\n"
             f"[^2]: [条目 {i2.id}] 事实二\n")
    fake = FakeProvider({"w_draft": [draft]})
    run = _run_e2e(db, author, fake)
    assert run.status == "OK"                   # 编号 1/2 ↔ 条目 2/3 两键分离须都可解析
    assert [c["item_id"] for c in
            db.get(Article, run.article_id).citations] == [i1.id, i2.id]


# ---------- assemble_article_text：渲染白名单转义（ADR-7② + AC-12.1） ----------

def test_assemble_escapes_tag_brackets_and_keeps_footnote_block():
    """正文 HTML 标签起始角括号转义（ADR-7②：markdown 白名单渲染 + HTML 转义）；
    文末定义区规范化装配（AC-12.1 [^nK] 脚注双轨）。"""
    body = ("前文<b>加粗</b>中段<B>大写</B>尾段<em>斜体\n"
            "[^9]: [条目 1] 不在文末的散落定义行")
    out = pl.assemble_article_text("题", body, {1: (5, "引用原句")})
    assert not re.search(r"<[a-zA-Z/!]", out)  # 转义纪律本体：不得残留任何标签起始角括号（含大写开标签）
    assert out.count("&lt;") >= 3              # 小写/大写/斜体三类均以合法 HTML 实体转义
    assert out.endswith("[^1]: [条目 5] 引用原句")   # 定义区按序装配在末尾
    assert out.count("[^1]: [条目") == 1             # 正文内散落定义行已收编、不重复
