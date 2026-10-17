"""moark 重排适配器归一化与转译契约（rerank.moark_reranker）：band 分档 + 会话透传 + llm 工厂组装。

四面（能力域治理条款补面——重排适配器的子类声明域）：
- 归一化分档按子类声明执行：relevance_score ×100 计分，band 阈值
  ≥0.75=high / ≥0.20=mid / 其余 low（边界值含 0.75 与 0.20 本身），
  三档枚举值恰为 high/mid/low——分档错位即归一化口径破坏；
- 传输类错误转译为 RankError 时 retryable / retry_after 结构化字段随转译
  保留（退避协商输入面不得在转译边界丢失）；
- 出网调用的 db 实参透传（db=出网 UA 策略读取面，随调用方会话传递）；
- llm 排序工厂在注册处组装：get_provider("llm", db) 构造的排序器携带
  同一会话，且选源调用以同一会话进行（计量归属随调用方会话刷新）。
设计依据见 docs/design-index.md「LR-2」「TR-4」「TR-6」。
"""
import pytest

import app.rerank.moark_reranker as moark_rank
import app.rerank.registry as rank_registry
from app.rerank.base import RankCandidate, RankError
from app.transport.errors import TransportError


class _StubResp:
    def __init__(self, body):
        self._body = body
        self.status_code = 200

    def json(self):
        return self._body


class _FakeDB:
    def add(self, obj):
        pass

    def commit(self):
        pass


def _provider():
    return moark_rank.MoarkRerankerProvider(
        _FakeDB(), base_url="https://api.test", api_key="k-test", model="m-test")


def test_band_thresholds_and_values_follow_declared_scale(monkeypatch):
    """归一化分档按子类声明：0.80/0.75 → high；0.30/0.20 → mid；0.10 → low
    （阈值边界含端点；分值=relevance_score×100 一位小数）。"""
    scores = [0.80, 0.75, 0.30, 0.20, 0.10]

    def _ok(url, payload, **kwargs):
        return _StubResp({
            "results": [{"index": i, "relevance_score": s}
                        for i, s in enumerate(scores)],
            "model": "m-test", "usage": {"promptTokens": 5, "totalTokens": 7},
        })

    monkeypatch.setattr(moark_rank, "post_json", _ok)
    out = _provider()._rank_chunk(
        "方向", [RankCandidate(id=i, text=f"c{i}") for i in range(len(scores))])
    assert [r.band for r in out] == ["high", "high", "mid", "mid", "low"]
    assert [r.score for r in out] == [80.0, 75.0, 30.0, 20.0, 10.0]


def test_transport_error_translates_with_retryable_and_retry_after(monkeypatch):
    """传输类错误转译保留协商字段：TransportError(429, Retry-After=30s)
    转译为 RankError 后 retryable=True 且 retry_after=30.0。"""
    def _raise(url, payload, **kwargs):
        raise TransportError("HTTP 429: slow down", status=429,
                             retry_after=30.0, retryable=True)

    monkeypatch.setattr(moark_rank, "post_json", _raise)
    with pytest.raises(RankError) as ei:
        _provider()._rank_chunk("方向", [RankCandidate(id=1, text="c")])
    assert ei.value.retryable is True
    assert ei.value.retry_after == 30.0


def test_post_json_receives_session_db_for_user_agent(db_session, monkeypatch):
    """出网 db 实参透传：适配器出网时把调用方会话传给传输脊（db=生效 UA
    策略读取面，出网不得退化为无会话形态）。"""
    captured: dict = {}

    def _capture(url, payload, **kwargs):
        captured.update(kwargs)
        # usage 按协议正常形态给全 camelCase 两键（本测试目标是 db 实参，
        # 不触碰缺键防御面）
        return _StubResp({"results": [], "usage": {"promptTokens": 0,
                                                   "totalTokens": 0}})

    monkeypatch.setattr(moark_rank, "post_json", _capture)
    provider = moark_rank.MoarkRerankerProvider(db_session)
    provider._rank_chunk("方向", [RankCandidate(id=1, text="c")])
    assert captured.get("db") is db_session


def test_llm_factory_passes_session_to_provider_and_resolver(db_session, monkeypatch):
    """llm 排序注册处组装：工厂构造的 LLMRankProvider 携带当前会话
    （排序落账/额度闸归属），且选源调用以同一会话进行（计量归属随
    调用方会话刷新——缓存命中实例的 db 不串台）。"""
    import app.providers.resolve as resolve_mod

    resolver_args: list = []

    class _FakeChat:
        pass

    def _fake_resolve_chat(db):
        resolver_args.append(db)
        return _FakeChat()

    monkeypatch.setattr(resolve_mod, "resolve_chat", _fake_resolve_chat)
    provider = rank_registry.get_provider("llm", db_session)
    assert provider.db is db_session
    assert resolver_args and resolver_args[0] is db_session
