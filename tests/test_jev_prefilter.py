"""BE-8：jev 预筛两段式 + 冷却账户联动 + 本批配置钉面。

覆盖（任务书 §五必含用例逐项）：
- AC-1 模型名钉面：MOARK_CHAT_MODEL=DeepSeek-V4-Flash（实价证伪换名：
  2026-10-20 模力 /v1/models?include_details=true 实查 v4.1-flash 系 ¥2/¥8、
  V4-Flash ¥1/¥2=站长 D1 口述价）；site_config 两新键缺省钉面；
- AC-2 账户联动冷却：jev 402 → moark_jev+moark 双键冷却+边沿通知恰一次
  （以 jev 名）；chat 402 仍单键（peers 空）零回归（不反向联动 jev）；
- AC-3 jev_prefilter 三态（REJECT 高置信/KEEP 高置信/低置信）+不可用 None
  （冷却中/调用异常）+score_round 三路路由+stats 三计数+jev 用量落账
  （call_point=score_prefilter）。

时间纪律：resolve 进程态（实例缓存+冷却表）每用例复位（BE-2 判例）；
通知触发器打桩记录（触发器本体测试见 test_llm_error_rate_trigger.py）。
出网零真发：provider 出网方法实例级/模块级打桩（_post_json / post_json）。
"""
import time

import httpx
import pytest

import app.config as cfg
from app.models import ScoreResult
from app.pipeline.runner import score_round
from app.providers import base as providers_base
from app.providers.moark_jev import MoarkJevProvider
from app.providers.resolve import cooldown_remaining
from app.transport import http as transport_http
from app.transport.errors import RetryExhausted, VendorFatalError


@pytest.fixture(autouse=True)
def clean_resolve():
    """选源层进程级状态（实例缓存+冷却表）的测试隔离位（BE-2 判例）。"""
    from app.providers import resolve as resolve_mod

    resolve_mod._reset_for_tests()
    yield resolve_mod
    resolve_mod._reset_for_tests()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """重试退避零等待。"""
    monkeypatch.setattr(time, "sleep", lambda s: None)


def _raise_status(status: int, text: str = '{"error":{"message":"boom"}}'):
    """经生产分类单点 _non_2xx_error 构造指定状态的入错 post_json 桩。"""

    def _fake_post_json(url, payload, *, headers, timeout, db=None, client_factory=None):
        resp = httpx.Response(status, text=text)
        raise transport_http._non_2xx_error(resp)

    return _fake_post_json


def _jev_questions():
    return {"keep": {"type": "choice", "criteria": {"KEEP": 1, "REJECT": 0},
                     "instructions": "判断内容与方向是否相关"}}


# ---------- AC-1：配置钉面 ----------


def test_moark_chat_model_pinned_real_price_name():
    """AC-1：DeepSeek-V4-Flash（大写实名，实价 ¥1/M·¥2/M=站长 D1 口述价；
    旧缺省 deepseek-v4.1-flash 实价 ¥2/¥8 比口述价贵 2/4 倍——实查证伪换名）。"""
    assert cfg.MOARK_CHAT_MODEL == "DeepSeek-V4-Flash"


def test_be8_site_config_defaults(db_session):
    """site_config 两新键缺省钉面：升级置信阈值 0.8、超龄闸 2 天。"""
    from app.siteconfig import DEFAULTS, get_config

    assert DEFAULTS["jev_upgrade_confidence"] == 0.8
    assert DEFAULTS["score_expire_days"] == 2
    assert float(get_config(db_session, "jev_upgrade_confidence")) == 0.8
    assert int(get_config(db_session, "score_expire_days")) == 2


# ---------- AC-2：账户联动冷却（peers） ----------


def test_jev_402_marks_dual_key_cooldown_and_notifies_once(db_session, monkeypatch):
    """jev 402 → moark_jev+moark 双键冷却（同 key 同账户联动：jev 冷却时 chat
    主源也该冷却）+边沿通知恰一次且以 jev 名；冷却期内第二次 402 不重发。"""
    calls: list[dict] = []
    monkeypatch.setattr("app.notify.triggers.notify_provider_switched",
                        lambda db, **kw: calls.append(kw))
    monkeypatch.setattr(providers_base, "post_json", _raise_status(402))
    p = MoarkJevProvider(db_session)
    with pytest.raises(RetryExhausted):
        p.decide(state="s", questions=_jev_questions(), call_point="ut")

    assert cooldown_remaining("moark_jev") > 0
    assert cooldown_remaining("moark") > 0
    assert len(calls) == 1
    assert calls[0]["name"] == "moark_jev"
    assert calls[0]["status"] == 402

    with pytest.raises(RetryExhausted):
        p.decide(state="s", questions=_jev_questions(), call_point="ut")
    assert len(calls) == 1  # 边沿一次


def test_chat_402_still_single_key_zero_regression(db_session, monkeypatch):
    """llm chat 402 仍单键（peers 空零回归）：只标 moark，不反向联动 moark_jev。"""
    from app.providers.moark_chat import MoarkChatProvider

    calls: list[dict] = []
    monkeypatch.setattr("app.notify.triggers.notify_provider_switched",
                        lambda db, **kw: calls.append(kw))
    monkeypatch.setattr(providers_base, "post_json", _raise_status(402))
    p = MoarkChatProvider(db_session)
    with pytest.raises(RetryExhausted):
        p._call({"model": cfg.MOARK_CHAT_MODEL}, call_point="ut")

    assert cooldown_remaining("moark") > 0
    assert cooldown_remaining("moark_jev") == 0.0
    assert len(calls) == 1
    assert calls[0]["name"] == "moark"


def test_deepseek_402_no_peers_linkage(db_session, monkeypatch):
    """deepseek 402 只标自身（无 peers 的候选零回归）。"""
    from app.providers.deepseek import DeepSeekProvider

    monkeypatch.setattr(providers_base, "post_json", _raise_status(402))
    p = DeepSeekProvider(db_session)
    with pytest.raises(RetryExhausted):
        p._call({"model": "m"}, call_point="ut")
    assert cooldown_remaining("deepseek") > 0
    assert cooldown_remaining("moark") == 0.0
    assert cooldown_remaining("moark_jev") == 0.0


def test_mark_vendor_cooldown_module_level_direct(db_session, monkeypatch):
    """模块级 mark_vendor_cooldown 直调：peers 扩展键集、边沿通知以主名、
    TTL=0 时 no-op 不通知（「首次进入冷却」语义对 peers 并集成立）。"""
    from app.providers.base import mark_vendor_cooldown
    from app.providers import resolve as resolve_mod

    calls: list[dict] = []
    monkeypatch.setattr("app.notify.triggers.notify_provider_switched",
                        lambda db, **kw: calls.append(kw))
    err = VendorFatalError("HTTP 402", status=402)
    mark_vendor_cooldown(err, name="moark_jev", db=db_session, peers=("moark",))
    assert cooldown_remaining("moark_jev") > 0
    assert cooldown_remaining("moark") > 0
    assert len(calls) == 1 and calls[0]["name"] == "moark_jev"

    # 主名已冷却（并集边沿已过）：再标不重发
    calls.clear()
    mark_vendor_cooldown(err, name="moark_jev", db=db_session, peers=("moark",))
    assert calls == []

    # TTL=0：mark no-op，冷却未发生则不发通知
    resolve_mod._reset_for_tests()
    monkeypatch.setattr(cfg, "LLM_PROVIDER_COOLDOWN_SECONDS", 0)
    mark_vendor_cooldown(err, name="moark_jev", db=db_session, peers=("moark",))
    assert cooldown_remaining("moark_jev") == 0.0
    assert cooldown_remaining("moark") == 0.0
    assert calls == []


# ---------- AC-3：jev_prefilter 单元 ----------


def _setup_direction_item(db):
    """方向+单条候选（FETCHED/PASSED/非判重——score_round 选取口径）。"""
    from app.models import Direction, Item, Source

    d = Direction(name="预筛方向", prompt="关注 AI 基础设施", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url="https://example.com/rss")
    db.add(src)
    db.commit()
    item = Item(source_id=src.id, guid="g1", url="https://example.com/a1",
                title="AI 数据中心扩建", content_text="正文" * 50,
                fetch_status="FETCHED", direction_id=d.id,
                sanitize_status="PASSED")
    db.add(item)
    db.commit()
    return d, item


def _stub_jev_body(choice: str, confidence: float):
    """decide 桩（实例级 _post_json 打桩——走生产 _call 计量面）。"""
    body = {
        "answers": {"keep": {"choice": choice, "confidence": confidence,
                             "probabilities": {choice: confidence}}},
        "usage": {"input_tokens": 120, "output_tokens": 2, "billing_units": 1},
        "model": "APUS-OpenJev-v1-9B",
    }

    class _FakeResp:
        def json(self):
            return body

    def fake_post_json(self, path, payload):
        return _FakeResp()

    return fake_post_json


def test_jev_prefilter_reject_high_confidence(db_session, monkeypatch):
    from app.scoring.prefilter import jev_prefilter

    d, item = _setup_direction_item(db_session)
    monkeypatch.setattr(MoarkJevProvider, "_post_json",
                        _stub_jev_body("REJECT", 0.93))
    out = jev_prefilter(db_session, item, d)
    assert out is not None
    assert out["verdict"] == "REJECT"
    assert out["confidence"] == pytest.approx(0.93)
    assert out["reason"]
    assert out["model"]  # 回显实况口径


def test_jev_prefilter_keep_high_confidence(db_session, monkeypatch):
    from app.scoring.prefilter import jev_prefilter

    d, item = _setup_direction_item(db_session)
    monkeypatch.setattr(MoarkJevProvider, "_post_json", _stub_jev_body("KEEP", 0.9))
    out = jev_prefilter(db_session, item, d)
    assert out is not None and out["verdict"] == "KEEP"


def test_jev_prefilter_cooldown_returns_none_without_call(db_session, monkeypatch):
    """jev 冷却中 → None 且不发起 decide（防故障期逐条烧注定失败的调用）。"""
    from app.providers import resolve as resolve_mod
    from app.scoring.prefilter import jev_prefilter

    d, item = _setup_direction_item(db_session)
    resolve_mod.mark_cooldown("moark_jev")

    def _must_not_call(self, path, payload):
        raise AssertionError("冷却中不应发起 jev 调用")

    monkeypatch.setattr(MoarkJevProvider, "_post_json", _must_not_call)
    assert jev_prefilter(db_session, item, d) is None


def test_jev_prefilter_failure_returns_none(db_session, monkeypatch):
    """调用异常（非 2xx 入错/网络）→ None 不抛（初筛失败=不可用语义）。"""
    from app.scoring.prefilter import jev_prefilter

    d, item = _setup_direction_item(db_session)

    def _boom(self, path, payload):
        raise transport_http._non_2xx_error(httpx.Response(500, text="boom"))

    monkeypatch.setattr(MoarkJevProvider, "_post_json", _boom)
    assert jev_prefilter(db_session, item, d) is None


def test_jev_prefilter_usage_recorded_score_prefilter(db_session, monkeypatch):
    """jev 用量落账：decide→_call→record_usage，call_point=score_prefilter
    （ev7 先例形态；打桩经生产计量面）。"""
    from app.models import UsageLog
    from app.scoring.prefilter import jev_prefilter

    d, item = _setup_direction_item(db_session)
    monkeypatch.setattr(MoarkJevProvider, "_post_json", _stub_jev_body("KEEP", 0.9))
    out = jev_prefilter(db_session, item, d)
    assert out is not None
    row = (db_session.query(UsageLog)
           .filter(UsageLog.call_point == "score_prefilter",
                   UsageLog.provider == "moark_jev", UsageLog.ok.is_(True))
           .order_by(UsageLog.id.desc()).first())
    assert row is not None
    assert row.prompt_tokens == 120
    assert row.completion_tokens == 2


def test_score_item_provider_name_routes_explicit_deepseek(db_session, monkeypatch):
    """score_item(provider_name=...) 显式选源（不走候选链）：升级复核用，
    payload model=显式模型名（避免链上 moark 收到 deepseek 官方名 400）。"""
    from app.providers.deepseek import DeepSeekProvider
    from app.scoring.service import score_item

    d, item = _setup_direction_item(db_session)
    recorded = []

    class _FakeResp:
        def json(self):
            return {"choices": [{"message": {"content": '{"quality": 70, "relevance": 80,'
                                             '"band": "high", "reason": "r"}',
                                                "finish_reason": "stop"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                    "model": cfg.DEEPSEEK_MODEL}

    def fake_post_json(self, path, payload, **kw):
        recorded.append(payload)
        return _FakeResp()

    monkeypatch.setattr(DeepSeekProvider, "_post_json", fake_post_json)
    sr = score_item(db_session, item, d, model=cfg.DEEPSEEK_MODEL,
                    provider_name="deepseek")
    assert sr.status == "OK"
    assert sr.model == cfg.DEEPSEEK_MODEL
    assert recorded[0]["model"] == cfg.DEEPSEEK_MODEL


# ---------- AC-3：score_round 三路路由 ----------


def _route_stubs(monkeypatch):
    """检索路由双桩（既有 score_round 测试同款姿势）。"""
    monkeypatch.setattr("app.retrieval.embedder.ensure_item_vectors",
                        lambda db, its, **kw: None)
    monkeypatch.setattr("app.retrieval.query.ensure_direction_query_vec",
                        lambda db, direction, **kw: False)


def _fake_score_recorder(rows):
    def fake_score(db, item, direction, *, model=None, provider_name=None):
        rows.append({"item_id": item.id, "model": model,
                     "provider_name": provider_name})
        return ScoreResult(item_id=item.id, direction_id=direction.id,
                           model=model or "chain-default", status="OK",
                           passed=True, relevance_score=80, quality_score=80,
                           band="high")
    return fake_score


def _verdict_stub(monkeypatch, verdict):
    monkeypatch.setattr("app.scoring.prefilter.jev_prefilter",
                        lambda db, item, direction: verdict)


def test_score_round_reject_high_confidence_terminal(db_session, monkeypatch):
    """高置信 REJECT → ScoreResult 终态（status=OK/passed=False/reason 含
    「初筛」与置信/quality+relevance+band 可空列取 NULL/model=jev 模型），
    不触 score_item；stats 增 prefiltered_rejected。"""
    from app.siteconfig import set_config

    d, item = _setup_direction_item(db_session)
    set_config(db_session, "jev_upgrade_confidence", 0.8)
    _route_stubs(monkeypatch)
    _verdict_stub(monkeypatch, {"verdict": "REJECT", "confidence": 0.93,
                                "reason": "choice=REJECT",
                                "model": "APUS-OpenJev-v1-9B"})
    scored_rows: list = []
    monkeypatch.setattr("app.scoring.service.score_item",
                        _fake_score_recorder(scored_rows))

    summary = score_round(db_session, triggered_by="test")
    assert scored_rows == []  # REJECT 终态不经 chat
    row = (db_session.query(ScoreResult).filter_by(item_id=item.id).one())
    assert row.status == "OK"
    assert row.passed is False
    assert "初筛" in row.reason and "0.93" in row.reason
    assert row.quality_score is None and row.relevance_score is None
    assert row.band is None
    assert row.model == "APUS-OpenJev-v1-9B"
    assert summary["directions"][0]["prefiltered_rejected"] == 1
    # 终态 OK 行：下轮不再选取
    summary2 = score_round(db_session, triggered_by="test")
    assert summary2["directions"][0]["candidates_total"] == 0


def test_score_round_keep_high_confidence_chat_chain(db_session, monkeypatch):
    """高置信 KEEP → 照常 score_item 走 chat 候选链（model=None 断言）。"""
    d, item = _setup_direction_item(db_session)
    _route_stubs(monkeypatch)
    _verdict_stub(monkeypatch, {"verdict": "KEEP", "confidence": 0.95,
                                "reason": "choice=KEEP"})
    scored_rows: list = []
    monkeypatch.setattr("app.scoring.service.score_item",
                        _fake_score_recorder(scored_rows))

    summary = score_round(db_session, triggered_by="test")
    assert scored_rows == [{"item_id": item.id, "model": None,
                            "provider_name": None}]
    assert summary["directions"][0]["scored"] == 1
    assert summary["directions"][0]["prefiltered_rejected"] == 0


def test_score_round_low_confidence_upgrades_explicit_deepseek(db_session,
                                                               monkeypatch):
    """低置信（任意 verdict）→ 显式 deepseek 复核（不走链：provider_name=
    deepseek + model=DEEPSEEK_MODEL 断言）；stats 增 upgraded。"""
    d, item = _setup_direction_item(db_session)
    _route_stubs(monkeypatch)
    _verdict_stub(monkeypatch, {"verdict": "REJECT", "confidence": 0.4,
                                "reason": "choice=REJECT"})
    scored_rows: list = []
    monkeypatch.setattr("app.scoring.service.score_item",
                        _fake_score_recorder(scored_rows))

    summary = score_round(db_session, triggered_by="test")
    assert scored_rows == [{"item_id": item.id, "model": cfg.DEEPSEEK_MODEL,
                            "provider_name": "deepseek"}]
    assert summary["directions"][0]["upgraded"] == 1
    assert summary["directions"][0]["prefiltered_rejected"] == 0


def test_score_round_prefilter_unavailable_failed_rerun(db_session, monkeypatch):
    """jev 不可用（None）→ 条目落 FAILED（error 注明下轮续跑），不触
    score_item（不自动回退 chat——成本失控防线）；stats 增 prefilter_unavailable；
    FAILED 行不挡下轮续跑。"""
    d, item = _setup_direction_item(db_session)
    _route_stubs(monkeypatch)
    _verdict_stub(monkeypatch, None)
    scored_rows: list = []
    monkeypatch.setattr("app.scoring.service.score_item",
                        _fake_score_recorder(scored_rows))

    summary = score_round(db_session, triggered_by="test")
    assert scored_rows == []  # 不自动回退 chat
    row = (db_session.query(ScoreResult).filter_by(item_id=item.id).one())
    assert row.status == "FAILED"
    assert "jev 初筛不可用" in (row.error or "")
    assert "下轮续跑" in (row.error or "")
    assert summary["directions"][0]["prefilter_unavailable"] == 1
    assert summary["directions"][0]["status"] == "FAILED"

    # FAILED 不挡下轮：恢复后（预筛 KEEP）同条目重新进入打分
    _verdict_stub(monkeypatch, {"verdict": "KEEP", "confidence": 0.95,
                                "reason": "choice=KEEP"})
    summary2 = score_round(db_session, triggered_by="test")
    assert summary2["directions"][0]["candidates_total"] == 1
    assert len(scored_rows) == 1


def test_upgrade_threshold_site_config_override(db_session, monkeypatch):
    """升级阈值 site_config 可调：调低后原会升级的 REJECT 变终态预筛。"""
    from app.siteconfig import set_config

    d, item = _setup_direction_item(db_session)
    set_config(db_session, "jev_upgrade_confidence", 0.3)
    _route_stubs(monkeypatch)
    _verdict_stub(monkeypatch, {"verdict": "REJECT", "confidence": 0.4,
                                "reason": "choice=REJECT"})
    scored_rows: list = []
    monkeypatch.setattr("app.scoring.service.score_item",
                        _fake_score_recorder(scored_rows))

    summary = score_round(db_session, triggered_by="test")
    assert scored_rows == []
    assert summary["directions"][0]["prefiltered_rejected"] == 1

