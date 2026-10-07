"""打分输出契约与解析校验测试：strict JSON 字段提取、分数域边界、band 域、
reason 非空、一次解析失败重试（附违规说明）、结果字段落库与失败原因落库。

覆盖口径（设计书条款面）：
- _validate：quality/relevance 提取链、分数域 0-100 双闭区间、band ∈ {high,mid,low}
  （大小写归一）、reason 非空——任一不合规抛 JSONParseError（AC-07.1 打分输出
  契约：quality/relevance/band/reason/prompt_version/model 六字段）；
- score_item：方向提示词注入组装（{{direction_prompt}} 占位替换）、messages 协议
  形态（role=system 在首位）、prompt_version/model 随行落库（D19 int 纪律）、
  解析失败重试恰一次且第二次附加违规说明、ProviderError 不重试直接落 FAILED、
  失败行 error 载体非空（DT-5：FAILED+原因）、passed = relevance ≥ 方向阈值
  （DT-5：仅 relevance 低于阈值才 false，等值通过）。
设计依据见 docs/design-index.md「AC-07.1」「AC-06.4」「DT-2」「DT-5」。
"""
import pytest

import app.config as cfg
import app.scoring.service as svc
from app.models import Direction, Item, ScoreResult, Source
from app.providers.base import JSONParseError, ProviderError
from app.scoring.service import DOCUMENT_DELIMITER_DECLARATION, _validate, score_item


def _good_data():
    return {"quality": 80, "relevance": 66, "band": "HIGH", "reason": "  相关报道  "}


def _mk_item(db, *, published=True, prompt_version=1):
    d = Direction(name="契约方向", prompt="关注 AI 治理", prompt_version=prompt_version,
                  threshold=66)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url="https://ex.com/rss")
    db.add(src)
    db.commit()
    from datetime import datetime

    item = Item(source_id=src.id, guid="g1", url="https://ex.com/a",
                title="某报道", content_text="正文内容足够长。" * 30,
                fetch_status="FETCHED", direction_id=d.id,
                published_at=datetime(2026, 10, 1) if published else None)
    db.add(item)
    db.commit()
    return d, item


# ---------- _validate：字段提取与分数域 ----------


def test_validate_normalizes_and_returns_fields():
    out = _validate(_good_data())
    assert out == {"quality": 80, "relevance": 66, "band": "high", "reason": "相关报道"}


def test_validate_rejects_missing_or_nonint_scores():
    with pytest.raises(JSONParseError):
        _validate({"relevance": 50, "band": "high", "reason": "r"})  # 缺 quality
    with pytest.raises(JSONParseError):
        _validate({"quality": 50, "band": "high", "reason": "r"})  # 缺 relevance
    with pytest.raises(JSONParseError):
        _validate({"quality": "abc", "relevance": 50, "band": "high", "reason": "r"})


def test_validate_score_domain_is_closed_0_100():
    # 0 与 100 是合法分数（双闭区间），-1 与 101 越界
    for q in (0, 100):
        out = _validate({"quality": q, "relevance": 50, "band": "high", "reason": "r"})
        assert out["quality"] == q
    for r in (0, 100):
        out = _validate({"quality": 50, "relevance": r, "band": "high", "reason": "r"})
        assert out["relevance"] == r
    with pytest.raises(JSONParseError):
        _validate({"quality": -1, "relevance": 50, "band": "high", "reason": "r"})
    with pytest.raises(JSONParseError):
        _validate({"quality": 101, "relevance": 50, "band": "high", "reason": "r"})
    # 越界判定对两分独立成立：quality 合法而 relevance 越界仍须拒绝
    with pytest.raises(JSONParseError):
        _validate({"quality": 50, "relevance": 101, "band": "high", "reason": "r"})
    with pytest.raises(JSONParseError):
        _validate({"quality": 50, "relevance": -1, "band": "high", "reason": "r"})


def test_validate_band_domain_and_reason_required():
    with pytest.raises(JSONParseError):
        _validate({"quality": 50, "relevance": 50, "band": "bogus", "reason": "r"})
    with pytest.raises(JSONParseError):
        _validate({"quality": 50, "relevance": 50, "band": "high", "reason": ""})
    with pytest.raises(JSONParseError):
        _validate({"quality": 50, "relevance": 50, "band": "high", "reason": "   "})


# ---------- score_item：组装、协议、落库、重试、失败落库 ----------


class RecordingProvider:
    """score_item 的打桩 provider：记录构造参数、每次调用的 messages 与 kwargs，
    按脚本依次返回或抛错。"""

    name = "stub"

    def __init__(self, db, *, script=None):
        self.ctor_args = (db,)
        self.script = list(script or [])
        self.calls = []

    def chat_json(self, messages, **kwargs):
        self.calls.append({"messages": [dict(m) for m in messages], "kwargs": kwargs})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step, "stub-model-x"


def _patch_provider(monkeypatch, provider):
    def factory(db):
        provider.ctor_args = (db,)  # 记录真实构造实参（ctor 会话归因断言面）
        return provider

    monkeypatch.setattr(svc, "DeepSeekProvider", factory)
    return provider


def test_score_item_constructs_provider_with_session(db_session, monkeypatch):
    """生产调用形态：provider 以 (db,) 构造（会话归因随构造传递——C1-8 构造全参
    透传先例）。"""
    d, item = _mk_item(db_session)
    p = _patch_provider(monkeypatch, RecordingProvider(db_session, script=[_good_data()]))
    score_item(db_session, item, d)
    assert p.ctor_args == (db_session,)


def test_score_item_injects_direction_prompt_and_message_roles(db_session, monkeypatch):
    """组装契约：方向提示词经 {{direction_prompt}} 占位注入 system（占位符不残留）、
    messages 首位为 system 消息、第二位为 user 消息（AC-06.4 定界声明的载体形态）。"""
    d, item = _mk_item(db_session)
    p = _patch_provider(monkeypatch, RecordingProvider(db_session, script=[_good_data()]))
    result = score_item(db_session, item, d)
    assert result.status == "OK"
    messages = p.calls[0]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    system = messages[0]["content"]
    assert d.prompt in system
    assert "{{direction_prompt}}" not in system
    assert system.splitlines()[0] == DOCUMENT_DELIMITER_DECLARATION


def test_score_item_persists_contract_fields_and_version(db_session, monkeypatch):
    """输出契约六字段：quality/relevance/band/reason 随解析值落库，
    prompt_version 取自方向（D19 int 纪律——以非缺省版本 2 钉死落列值，排除
    列 default=1 的等价假象），passed 以 relevance == 阈值即过（DT-5）。"""
    d, item = _mk_item(db_session, prompt_version=2)  # threshold=66，relevance=66 等值通过
    monkeypatch.setattr(svc, "load_prompt_template",
                        lambda version: "模板 {{direction_prompt}} 正文")
    _patch_provider(monkeypatch, RecordingProvider(db_session, script=[_good_data()]))
    result = score_item(db_session, item, d)
    assert result.status == "OK"
    assert result.quality_score == 80
    assert result.relevance_score == 66
    assert result.band == "high"
    assert result.reason == "相关报道"
    assert result.prompt_version == 2
    assert result.prompt_version == d.prompt_version
    assert result.passed is True
    assert result.model == "stub-model-x"


def test_score_item_retry_exactly_once_with_violation_note(db_session, monkeypatch):
    """解析失败重试恰一次（同条内容共两次调用），第二次调用在原 messages 后追加
    违规说明（assistant+user 两条，协议形态完整）——重试不改变调用总量契约。"""
    d, item = _mk_item(db_session)
    p = _patch_provider(monkeypatch, RecordingProvider(db_session, script=[
        JSONParseError("band 非法"),
        _good_data(),
    ]))
    result = score_item(db_session, item, d)
    assert result.status == "OK"
    assert len(p.calls) == 2
    second = p.calls[1]["messages"]
    assert len(second) == 4  # 原 2 条 + 违规说明 assistant + user
    assert second[2]["role"] == "assistant"
    assert second[3]["role"] == "user"
    assert second[2]["content"]
    assert second[3]["content"]


def test_score_item_call_metering_kwargs(db_session, monkeypatch):
    """调用计量契约：chat_json 收到 call_point="scoring"（AC-08.2 的 usage_log
    计量证明依赖该口径）。"""
    d, item = _mk_item(db_session)
    p = _patch_provider(monkeypatch, RecordingProvider(db_session, script=[_good_data()]))
    score_item(db_session, item, d)
    kwargs = p.calls[0]["kwargs"]
    assert "call_point" in kwargs
    assert kwargs["call_point"] == "scoring"


def test_score_item_provider_error_no_retry_fails_with_reason(db_session, monkeypatch):
    """ProviderError（网络层已重试耗尽）不重试：恰一次调用、落 FAILED 终态、
    error 载体非空、初始 model/prompt_version 契约保持（AC-07.1/DT-5）。"""
    d, item = _mk_item(db_session)
    p = _patch_provider(monkeypatch, RecordingProvider(db_session, script=[
        ProviderError("stub: 网络耗尽"),
    ]))
    result = score_item(db_session, item, d)
    assert len(p.calls) == 1
    assert result.status == "FAILED"
    assert result.error
    assert result.model == cfg.DEEPSEEK_MODEL
    assert result.prompt_version == d.prompt_version
    rows = db_session.query(ScoreResult).all()
    assert len(rows) == 1 and rows[0].status == "FAILED"


def test_score_item_parse_exhaustion_keeps_error_reason(db_session, monkeypatch):
    """解析失败重试后仍失败：落 FAILED 且 error 载体保留（FAILED+原因——DT-5
    的载体语义：error 非空即原因在位，措辞为自由域）。"""
    d, item = _mk_item(db_session)
    p = _patch_provider(monkeypatch, RecordingProvider(db_session, script=[
        JSONParseError("第一次不合规"),
        JSONParseError("第二次仍不合规"),
    ]))
    result = score_item(db_session, item, d)
    assert len(p.calls) == 2
    assert result.status == "FAILED"
    assert result.error


def test_score_item_explicit_model_kept_on_failure(db_session, monkeypatch):
    """显式指定 model 时失败行 model 契约=显式值（初始 model 不被默认值吞没）。"""
    d, item = _mk_item(db_session)
    _patch_provider(monkeypatch, RecordingProvider(db_session, script=[
        ProviderError("stub: 失败"),
    ]))
    result = score_item(db_session, item, d, model="explicit-model")
    assert result.status == "FAILED"
    assert result.model == "explicit-model"
