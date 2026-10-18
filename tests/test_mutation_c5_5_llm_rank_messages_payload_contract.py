"""chat_json 载荷结构契约——rank_llm 组装面（C5-4 D 类 messages 结构面
16 条站长裁定转 C 的组杀断言；锚=技术书 v2.4 §6.13 LR-9）。

覆盖：LLM 排序发往 chat 提供方的 messages 载荷结构——逐条恰含 role 与
content 二键、content 为 str、role 取值在协议枚举（system/user）内；
载荷为定长两条（system 提示词 + user 方向标准与候选）且以同一 list 对象
送出。任一结构破坏（键漂移/值域漂移/None 化/实参丢失）在真实协议下即
400 形态，属协议契约面而非文案域。
设计依据见 docs/design-index.md「LR-9」。
"""
from app.rerank.base import RankCandidate
from app.rerank.llm_rank import LLMRankProvider


class StructureCheckingChatProvider:
    """chat_json 桩：校验收到的 messages 载荷结构（LR-9 组杀面）。"""

    def __init__(self):
        self.seen = None

    def chat_json(self, messages, **kw):
        assert isinstance(messages, list), \
            f"messages 须为 list，实得 {type(messages).__name__}"
        assert len(messages) == 2, f"载荷须为 system+user 两条，实得 {len(messages)}"
        for i, m in enumerate(messages):
            assert isinstance(m, dict), \
                f"messages[{i}] 须为 dict，实得 {type(m).__name__}"
            assert set(m.keys()) == {"role", "content"}, \
                f"messages[{i}] 须恰含 role/content 二键，实得 {sorted(m.keys())}"
            assert isinstance(m["content"], str), \
                f"messages[{i}].content 须为 str，实得 {type(m['content']).__name__}"
            assert m["role"] in ("system", "user"), \
                f"messages[{i}].role 取值漂移出协议枚举: {m['role']!r}"
        assert [m["role"] for m in messages] == ["system", "user"], \
            "载荷须为 system 在前、user 在后的定长两条"
        self.seen = messages
        return {"results": [{"id": "a", "score": 80, "band": "high"}]}, \
            "fake-chat-model"


def test_rank_llm_messages_payload_structure(db_session):
    """rank_llm 的 chat 载荷结构：逐条恰含 role/content 二键、content 为
    str、role 在协议枚举内（LR-9 载荷结构契约——桩内校验组杀）。"""
    fake = StructureCheckingChatProvider()
    p = LLMRankProvider(db_session, chat_provider=fake)
    out = p.rank("方向标准", [RankCandidate(id="a", text="甲")])
    assert out and out[0].score == 80.0
    assert fake.seen is not None  # 桩确实收到载荷（校验全过）
