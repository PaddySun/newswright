"""LLM 排序底座的 chat 提供方构造注入（组合实现漏点修复）。

覆盖：LLMRankProvider 接受注入的 chat provider（Fake 可替换） /
排序实现自身零具体厂商 import（选源经注入或选源层） /
注册处（rerank/registry）完成 chat 提供方组装。设计依据见
docs/design-index.md「LR-2」。
"""
import app.config as cfg
from app.rerank.base import RankCandidate, RankProvider
from app.rerank.llm_rank import LLMRankProvider


class FakeChatProvider:
    """chat_json 桩：按 id 顺序回固定分。"""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def chat_json(self, messages, **kw):
        self.calls.append((messages, kw))
        return {"results": self.result}, "fake-chat-model"


def test_llm_rank_accepts_injected_chat_provider(db_session):
    fake = FakeChatProvider([
        {"id": "a", "score": 90, "band": "high"},
        {"id": "b", "score": 20, "band": "low"},
    ])
    p = LLMRankProvider(db_session, chat_provider=fake)
    out = p.rank("方向标准", [RankCandidate(id="a", text="甲"), RankCandidate(id="b", text="乙")])
    assert [r.id for r in out] == ["a", "b"]
    assert out[0].score == 90.0 and out[0].band == "high"
    assert len(fake.calls) == 1
    assert fake.calls[0][1]["call_point"] == "rank_llm"


def test_llm_rank_has_no_concrete_vendor_import():
    """排序实现零具体厂商：模块源不出现 DeepSeekProvider 形态。"""
    import inspect
    src = inspect.getsource(LLMRankProvider)
    assert "DeepSeekProvider" not in src


def test_registry_wires_chat_provider_at_registration(db_session):
    """注册处组装：rank registry 取 "llm" 时 chat 提供方已经选源层绑定。"""
    from app.rerank import registry as rank_registry
    p = rank_registry.get_provider("llm", db_session)
    assert isinstance(p, LLMRankProvider) and isinstance(p, RankProvider)
    assert p.chat_provider.name == cfg.LLM_PROVIDER


def test_llm_rank_degrades_when_no_provider_available(db_session, monkeypatch):
    """无可用 chat 提供方：抛 RankError（排序域既有失败语义，调用方按现有链路降级）。"""
    from app.rerank.base import RankError
    import app.rerank.llm_rank as lr
    monkeypatch.setattr(lr, "resolve_chat", lambda db: None)
    p = LLMRankProvider(db_session)
    try:
        p.rank("方向标准", [RankCandidate(id="a", text="甲")])
        raised = False
    except RankError as e:
        raised = "无可用" in str(e)
    assert raised
