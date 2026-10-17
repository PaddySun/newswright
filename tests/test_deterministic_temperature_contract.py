"""判定类 chat 调用的确定性温度契约（LR-8）。

打分（scoring）与检索查询生成（query_gen）两类判定/结构化输出调用的
temperature=0 为契约：打分显式传 0.0 不得漂移；chat 模板温度缺省 0.0
不得漂移（缺省的唯一生产消费方=检索查询生成，其调用不传温度）。
测试形态=桩捕获请求侧参数断言 temperature==0.0——杀灭把 0.0 改 1.0
的常量变异（temperature 缺省值/显式实参两处）。
设计依据见 docs/design-index.md「LR-8」。
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.providers.base import LLMProvider


class _PayloadCapturingChat(LLMProvider):
    """真 chat 模板 + 桩传输：捕获发往 _post 的 payload（温度缺省在真模板里生效；
    计量走注入的内存会话——真模板成功路径会落一条 usage_log 行）。"""

    name = "capture"

    def __init__(self, db):
        super().__init__(db)
        self.payloads: list[dict] = []

    def _default_model(self) -> str:
        return "stub-model"

    def _post(self, payload):
        self.payloads.append(payload)
        body = {"choices": [{"message": {"content": "检索查询文本"}, "finish_reason": "stop"}],
                "model": "stub-model", "usage": {}}
        return body, {}


def test_query_generation_uses_deterministic_default_temperature(monkeypatch, db_session):
    """query_gen 不传温度 → 走 chat 模板缺省 0.0（缺省唯一消费方，缺省漂移即违约）。"""
    from app.retrieval import query as query_module

    capture = _PayloadCapturingChat(db_session)
    monkeypatch.setattr(query_module, "resolve_chat", lambda db: capture)

    class _Direction:
        id = 1
        prompt = "某方向的评分提示词"
        prompt_version = 1
        query_vec = None
        query_vec_version = None

    class _Embed:
        def embed(self, texts, **kw):
            return [[0.0, 1.0]]

    ok = query_module.ensure_direction_query_vec(
        db_session, _Direction(), embed_provider=_Embed())
    assert ok is True
    assert capture.payloads, "query_gen 未发起 chat 调用"
    temperatures = [p.get("temperature") for p in capture.payloads]
    assert temperatures == [0.0]


def test_scoring_passes_explicit_zero_temperature(monkeypatch, db_session: Session):
    """打分调用显式 temperature=0.0 不得漂移（判定输出的确定性要求）。"""
    from app.scoring import service as scoring_module

    captured: dict = {}

    class _FakeScoringChat:
        name = "fake"

        def chat_json(self, messages, **kwargs):
            captured.update(kwargs)
            return {"quality": 50, "relevance": 50, "band": "mid", "reason": "判定理由"}, "stub-model"

    monkeypatch.setattr(scoring_module, "resolve_chat", lambda db: _FakeScoringChat())

    class _Item:
        id = 7
        title = "标题"
        content_text = "正文内容"
        url = "https://example.com/a"
        published_at = None

    class _Direction:
        id = 2
        name = "方向"
        prompt = "提示词"
        prompt_version = 1
        threshold = 60

    result = scoring_module.score_item(db_session, _Item(), _Direction())
    assert result.status == "OK"
    assert captured.get("temperature") == 0.0


@pytest.fixture
def db_session():
    """独立内存库会话（score_item 落 ScoreResult 行所需）。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
