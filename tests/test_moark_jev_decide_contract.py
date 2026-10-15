"""moark Jev 决策适配器 decide() 的请求构造契约（防线前移）。

覆盖：questions 缺 instructions 必填字段在客户端构造期即抛 JevAdapterError
（消息含字段名——服务端对该缺失回 400 的实测教训，不烧一次网络） /
完整 payload 经 Fake 传输零 400 且请求形态正确 / 经 providers registry
注册可达（resolve 可解析）。设计依据见 docs/design-index.md「LR-7」。
"""
import pytest

from app.providers.moark_jev import JevAdapterError, MoarkJevProvider


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


QUESTIONS_COMPLETE = {
    "fresh": {
        "type": "choice",
        "criteria": {"fresh": 1, "stale": 0},
        "instructions": "判断内容是否为新近事件",
        "options": {"fresh": "新近", "stale": "陈旧"},
    },
}


def _jev_body():
    return {
        "answers": {"fresh": {"choice": "fresh", "confidence": 0.9,
                              "probabilities": {"fresh": 0.9, "stale": 0.1}}},
        "usage": {"input_tokens": 11, "output_tokens": 4, "billing_units": 1},
        "model": "APUS-OpenJev-v1-9B",
    }


def test_decide_requires_instructions_per_question(db_session):
    """缺 instructions：构造期抛错（消息含字段名），不触网。"""
    p = MoarkJevProvider(db_session)
    questions = {"fresh": {"type": "choice", "criteria": {"fresh": 1, "stale": 0}}}
    with pytest.raises(JevAdapterError, match="instructions") as ei:
        p.decide(state="s", questions=questions)
    assert "fresh" in str(ei.value)  # 可归因到具体 question


def test_decide_blank_instructions_also_rejected(db_session):
    p = MoarkJevProvider(db_session)
    questions = {"fresh": {"type": "choice", "criteria": {"a": 1},
                           "instructions": "   "}}
    with pytest.raises(JevAdapterError, match="instructions"):
        p.decide(state="s", questions=questions)


def test_decide_complete_payload_zero_400(db_session, monkeypatch):
    """完整 payload（含 instructions）经 Fake 传输：请求形态正确、解析零异常。"""
    p = MoarkJevProvider(db_session)
    recorded = []

    def fake_post_json(path, payload):
        recorded.append((path, payload))
        return _FakeResp(_jev_body())

    monkeypatch.setattr(p, "_post_json", fake_post_json)
    out = p.decide(state="今日热点简报", questions=QUESTIONS_COMPLETE,
                   call_point="prefilter", ref_id=42)
    path, payload = recorded[0]
    assert path.endswith("/v1/systemone")
    assert payload["questions"]["fresh"]["instructions"] == "判断内容是否为新近事件"
    assert payload["model"]  # 计量归因的 model 必在请求内
    assert out["answers"]["fresh"]["choice"] == "fresh"
    assert out["model"] == "APUS-OpenJev-v1-9B"  # 回显实况口径
    assert out["usage"]["billing_units"] == 1


def test_jev_registered_in_providers_registry(db_session):
    from app.providers import registry
    from app.providers.resolve import resolve
    assert "moark_jev" in registry.available()
    p = resolve("moark_jev", db_session)
    assert isinstance(p, MoarkJevProvider)
