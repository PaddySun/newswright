"""LLM 排序的分档声明优先、回退推导边界与 0-100 钳制契约
（no-tests 转幸存老族分诊补面）。

覆盖：模型声明的 band 优先（仅无效 band 才走回退推导——band_map 组装
与读取面）；回退档位边界恰为 ≥75 high / ≥25 mid / 其余 low（子类声明
形态：LLM 直接 0-100 分 + 三档 band 口径）；score 钳制界恰 0.0-100.0；
候选缺 id 跳过语义（缺失继续处理后续候选）；判定类调用温度 0
（LR-8 确定性温度契约的 rank_llm 调用面）；未注入 chat 提供方时选源
层收到当前调用方会话（LR-2 经选源层的组装半边）。
设计依据见 docs/design-index.md「LR-2」「LR-8」。
"""
import app.rerank.llm_rank as lr
from app.rerank.base import RankCandidate
from app.rerank.llm_rank import LLMRankProvider


class FakeChatProvider:
    """chat_json 桩：回固定 results 并记录调用实参。"""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def chat_json(self, messages, **kw):
        self.calls.append((messages, kw))
        return {"results": self.result}, "fake-chat-model"


def _rank(db_session, result, candidates):
    fake = FakeChatProvider(result)
    p = LLMRankProvider(db_session, chat_provider=fake)
    return p.rank("方向标准", candidates), fake


def test_model_declared_band_survives_over_fallback(db_session):
    """band 声明优先：三档有效声明均直出（80/mid、60/low、60/high——分数
    均不在声明档的回推区间），声明有效则不走回退推导。"""
    out, _ = _rank(
        db_session,
        [{"id": "a", "score": 80, "band": "mid"},
         {"id": "b", "score": 60, "band": "low"},
         {"id": "c", "score": 60, "band": "high"}],
        [RankCandidate(id="a", text="甲"), RankCandidate(id="b", text="乙"),
         RankCandidate(id="c", text="丙")])
    assert [r.band for r in out] == ["mid", "low", "high"]


def test_invalid_band_falls_back_to_declared_tiers(db_session):
    """无效 band 的回退推导边界：75→high（≥75 含端点）、25→mid（≥25 含端点）、
    24→low（三档恰为 high/mid/low）。"""
    out, _ = _rank(
        db_session,
        [{"id": "a", "score": 75, "band": "?"},
         {"id": "b", "score": 25, "band": "?"},
         {"id": "c", "score": 24, "band": "?"}],
        [RankCandidate(id="a", text="甲"), RankCandidate(id="b", text="乙"),
         RankCandidate(id="c", text="丙")])
    assert [r.band for r in out] == ["high", "mid", "low"]


def test_score_clamped_to_zero_hundred(db_session):
    """0-100 钳制界：越界 100.5→100.0、低界 0→0.0（归一化量纲钉死界值）。"""
    out, _ = _rank(
        db_session,
        [{"id": "a", "score": 100.5, "band": "high"},
         {"id": "b", "score": 0, "band": "low"}],
        [RankCandidate(id="a", text="甲"), RankCandidate(id="b", text="乙")])
    assert out[0].score == 100.0
    assert out[1].score == 0.0


def test_missing_id_candidates_skipped_but_rest_kept(db_session):
    """缺 id 容错：results 未覆盖的候选跳过，其后候选照常输出（跳过语义）。"""
    out, _ = _rank(
        db_session,
        [{"id": "a", "score": 80, "band": "high"},
         {"id": "c", "score": 30, "band": "mid"}],
        [RankCandidate(id="a", text="甲"), RankCandidate(id="b", text="乙"),
         RankCandidate(id="c", text="丙")])
    assert [r.id for r in out] == ["a", "c"]


def test_judgment_call_temperature_zero(db_session):
    """判定类调用温度 0：rank_llm 的 chat 调用显式 temperature=0.0
    （排序判定确定性）。"""
    _, fake = _rank(db_session, [{"id": "a", "score": 50, "band": "mid"}],
                    [RankCandidate(id="a", text="甲")])
    assert fake.calls[0][1]["temperature"] == 0.0


def test_resolve_chat_receives_caller_session(db_session, monkeypatch):
    """未注入 chat 提供方：选源层收到当前调用方会话（计量归属刷新面）。"""
    seen = {}

    def fake_resolve(db):
        seen["db"] = db
        return FakeChatProvider([{"id": "a", "score": 90, "band": "high"}])

    monkeypatch.setattr(lr, "resolve_chat", fake_resolve)
    p = LLMRankProvider(db_session)
    out = p.rank("方向标准", [RankCandidate(id="a", text="甲")])
    assert seen["db"] is db_session
    assert out[0].score == 90.0
