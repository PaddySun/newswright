"""moark Jev 决策适配器的计量落账与协议响应契约（no-tests 转幸存老族分诊补面）。

覆盖：decide 全链（经 _call）落 usage_log 行的计量归因字段（call_point
缺省 prefilter / ref_type 缺省 item / ref_id）与三计费字段
（prompt_tokens/completion_tokens/billing_units 逐字段——ADR-8 外部调用
计量落账）；_post 传输脊出口的 Authorization 头构造（ADR-8 Bearer 构造）；
构造期校验（criteria 空拦下不触网——LR-7 防线前移）；协议载荷键
（state 唯一内容通道）；decide 返回形态（answers[qid] 三键与 usage 三键
——协议文档钉死的响应映射）；错误响应/answers 缺键/choice 越界均抛
JevAdapterError（键完整性+枚举校验）；域级重试上限 2（ADR-8 重试 ≤2——
耗尽时 ok=False 落账恰 3 行）。
设计依据见 docs/design-index.md「LR-7」「ADR-8」。
"""
import httpx
import pytest

import app.config as config
from app.models import UsageLog
from app.providers.base import RetryExhausted
from app.providers.moark_jev import JevAdapterError, MoarkJevProvider


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


QUESTIONS = {
    "fresh": {
        "type": "choice",
        "criteria": {"fresh": 1, "stale": 0},
        "instructions": "判断内容是否为新近事件",
    },
}


def _jev_body():
    return {
        "answers": {"fresh": {"choice": "fresh", "confidence": 0.9,
                              "probabilities": {"fresh": 0.9, "stale": 0.1}}},
        "usage": {"input_tokens": 11, "output_tokens": 4, "billing_units": 1},
        "model": "APUS-OpenJev-v1-9B",
    }


def _usage_rows(db):
    return (db.query(UsageLog).filter(UsageLog.provider == "moark_jev")
            .order_by(UsageLog.id).all())


def test_decide_metering_row_full_attribution(db_session, monkeypatch):
    """decide 经 _call 落账：缺省 call_point=prefilter / ref_type=item /
    显式 ref_id 透传 / 三计费字段逐字段（协议 usage 三键 → usage_log）。"""
    p = MoarkJevProvider(db_session)
    monkeypatch.setattr(p, "_post_json", lambda path, payload: _FakeResp(_jev_body()))
    p.decide(state="今日热点简报", questions=QUESTIONS, ref_id=42)
    rows = _usage_rows(db_session)
    assert len(rows) == 1
    row = rows[0]
    assert row.call_point == "prefilter"
    assert row.ref_type == "item"
    assert row.ref_id == 42
    assert row.prompt_tokens == 11
    assert row.completion_tokens == 4
    assert row.billing_units == 1
    assert row.ok is True


def test_decide_response_shape_answers_and_usage(db_session, monkeypatch):
    """decide 返回形态：answers[qid] 恰为 choice/confidence/probabilities 三键
    （协议文档 answers[qid] 映射），usage 恰为 input/output/billing 三键。"""
    p = MoarkJevProvider(db_session)
    monkeypatch.setattr(p, "_post_json", lambda path, payload: _FakeResp(_jev_body()))
    out = p.decide(state="s", questions=QUESTIONS)
    assert out["answers"]["fresh"] == {
        "choice": "fresh", "confidence": 0.9,
        "probabilities": {"fresh": 0.9, "stale": 0.1},
    }
    assert out["usage"] == {"input_tokens": 11, "output_tokens": 4,
                            "billing_units": 1}


def test_decide_error_body_raises_jev_adapter_error(db_session, monkeypatch):
    """systemone error 响应：抛 JevAdapterError（域错误类型，错误体回显面）。"""
    p = MoarkJevProvider(db_session)
    monkeypatch.setattr(p, "_post_json", lambda path, payload: _FakeResp({"error": "boom"}))
    with pytest.raises(JevAdapterError):
        p.decide(state="s", questions=QUESTIONS)


def test_decide_missing_answer_key_raises(db_session, monkeypatch):
    """answers 键完整性：响应缺 qid 抛 JevAdapterError（不裸 KeyError/TypeError）。"""
    p = MoarkJevProvider(db_session)
    body = _jev_body()
    body["answers"] = {}
    monkeypatch.setattr(p, "_post_json", lambda path, payload: _FakeResp(body))
    with pytest.raises(JevAdapterError):
        p.decide(state="s", questions=QUESTIONS)


def test_decide_choice_outside_criteria_raises(db_session, monkeypatch):
    """choice 枚举校验：越界 choice 抛 JevAdapterError（不裸 TypeError）。"""
    p = MoarkJevProvider(db_session)
    body = _jev_body()
    body["answers"]["fresh"]["choice"] = "unknown"
    monkeypatch.setattr(p, "_post_json", lambda path, payload: _FakeResp(body))
    with pytest.raises(JevAdapterError):
        p.decide(state="s", questions=QUESTIONS)


def test_decide_empty_criteria_rejected_before_network(db_session, monkeypatch):
    """构造期校验带：criteria 空（type 合法）即抛 JevAdapterError，
    不触网（防线前移——不烧注定失败的请求）。"""
    p = MoarkJevProvider(db_session)

    def _no_network(path, payload):
        raise AssertionError("结构非法请求不应触网")

    monkeypatch.setattr(p, "_post_json", _no_network)
    questions = {"fresh": {"type": "choice", "criteria": {},
                           "instructions": "x"}}
    with pytest.raises(JevAdapterError):
        p.decide(state="s", questions=questions)


def test_decide_payload_carries_state_channel(db_session, monkeypatch):
    """协议载荷键：state 是 systemone 唯一内容通道，payload 必含原样 state。"""
    p = MoarkJevProvider(db_session)
    recorded = []
    monkeypatch.setattr(
        p, "_post_json",
        lambda path, payload: (recorded.append(payload), _FakeResp(_jev_body()))[1])
    p.decide(state="今日热点简报", questions=QUESTIONS)
    assert recorded[0]["state"] == "今日热点简报"


def test_provider_sends_bearer_authorization_header(db_session, monkeypatch):
    """出网鉴权头：Authorization 恰为 Bearer + 配置密钥（ADR-8 Bearer 构造）。"""
    captured = {}

    def fake_post_json(url, payload, *, headers=None, timeout=None, db=None):
        captured["headers"] = headers
        return _FakeResp(_jev_body())

    monkeypatch.setattr("app.providers.base.post_json", fake_post_json)
    p = MoarkJevProvider(db_session)
    p.decide(state="s", questions=QUESTIONS)
    assert captured["headers"]["Authorization"] == f"Bearer {config.MOARK_API_KEY}"


def test_decide_retry_cap_two_attempts_three_fail_rows(db_session, monkeypatch):
    """域级重试上限：恒败网络错误下重试恰 2 次（共 3 次尝试，3 行 ok=False
    落账）后抛 RetryExhausted——ADR-8 重试 ≤2。"""
    p = MoarkJevProvider(db_session)
    monkeypatch.setattr(
        p, "_post_json",
        lambda path, payload: (_ for _ in ()).throw(httpx.ConnectError("net down")))
    with pytest.raises(RetryExhausted):
        p.decide(state="s", questions=QUESTIONS)
    rows = _usage_rows(db_session)
    assert len(rows) == 3
    assert all(r.ok is False for r in rows)
