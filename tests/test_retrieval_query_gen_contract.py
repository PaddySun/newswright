"""方向查询向量生成契约测试：生成调用组装（rubric 摘要式提示词注入）、
计量与护栏 kwarg 口径、嵌入维度护栏传递、查询向量落库。

覆盖口径：
- 未注入 llm 时经 DeepSeekProvider(db) 构造（db 归因随构造传递，AC-08.2
  查询生成调用链）；
- 生成提示词 = 版本化常量 QUERY_GEN_PROMPT 且方向 prompt 经 format 注入
  （rubric 摘要式查询形态——EV2 教训条款面：非主题式；G3 裁定④版本缓存）；
- messages 协议形态：system + user 两条、role/content 键完整；
- 嵌入调用携带 expected_dims=config.EMBED_DIMENSIONS 与 call_point="embed_query"
  （生产配置表计量口径；ADR-3 expected_dims 护栏）；
- 生成成功后查询向量落列（direction.query_vec BLOB，G3 裁定④双列承载）。
设计依据见 docs/design-index.md「AC-08.2」。
"""
import numpy as np

import app.config as cfg
from app.models import Direction, Source
from app.retrieval.embedder import blob_to_vec
from app.retrieval.query import QUERY_GEN_PROMPT, ensure_direction_query_vec


class RecordingLLM:
    """查询生成 LLM 打桩：记录构造参数与每次调用的 messages/kwargs。"""

    instances = []

    def __init__(self, db, *, text="检索查询文本", fail=False):
        self.ctor_args = (db,)
        self.text = text
        self.fail = fail
        self.calls = []
        RecordingLLM.instances.append(self)

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": [dict(m) for m in messages], "kwargs": kwargs})
        if self.fail:
            from app.providers.base import ProviderError

            raise ProviderError("stub: LLM 不可用")
        return self.text, "stub-model"


class RecordingEmbed:
    """嵌入打桩：记录每次调用 kwargs，返回可识别向量。"""

    def __init__(self, db):
        self.db = db
        self.calls = []

    @property
    def model_name(self):
        return "stub-embed-model"

    def embed(self, texts, **kwargs):
        self.calls.append({"texts": list(texts), "kwargs": dict(kwargs)})
        return [[1.0] + [0.0] * 15 for _ in texts]


def _mk_direction(db):
    d = Direction(name="查询方向", prompt="接纳 AI 治理深度报道", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url="https://example.com/rss")
    db.add(src)
    db.commit()
    return d


def test_query_gen_constructs_llm_with_db_and_generates(db_session, monkeypatch):
    """未注入 llm：经 DeepSeekProvider(db) 构造并完成生成（生产调用形态）。"""
    d = _mk_direction(db_session)
    RecordingLLM.instances = []
    monkeypatch.setattr("app.retrieval.query.DeepSeekProvider", RecordingLLM)
    assert ensure_direction_query_vec(db_session, d, embed_provider=RecordingEmbed(db_session)) is True
    assert RecordingLLM.instances[0].ctor_args == (db_session,)


def test_query_gen_resolves_embed_provider_with_db_when_not_injected(db_session,
                                                                     monkeypatch):
    """未注入 embed_provider：经 default_provider(db) 解析（会话归因随解析传递，
    AC-08.2 查询向量生成的嵌入调用链）。"""
    d = _mk_direction(db_session)
    resolved = {}

    def fake_default_provider(db):
        resolved["db"] = db
        return RecordingEmbed(db_session)

    monkeypatch.setattr("app.retrieval.query.default_provider", fake_default_provider)
    assert ensure_direction_query_vec(db_session, d, llm=RecordingLLM(db_session)) is True
    assert resolved["db"] is db_session


def test_query_gen_prompt_assembly_is_versioned_constant(db_session, monkeypatch):
    """生成提示词组装：messages 为 system+user 两条、user 内容=版本化常量
    QUERY_GEN_PROMPT 注入方向 prompt 后的产物（rubric 摘要式查询形态）。"""
    d = _mk_direction(db_session)
    llm = RecordingLLM(db_session)
    assert ensure_direction_query_vec(db_session, d, llm=llm,
                                      embed_provider=RecordingEmbed(db_session)) is True
    messages = llm.calls[0]["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "content" in messages[0]
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == QUERY_GEN_PROMPT.format(direction_prompt=d.prompt)
    # 调用归因参数存在性：真实 provider 的 chat 以 call_point 为必需 kwarg
    assert "call_point" in llm.calls[0]["kwargs"]


def test_query_gen_embed_guard_kwargs_and_metering_point(db_session, monkeypatch):
    """嵌入护栏与计量：expected_dims=config.EMBED_DIMENSIONS、
    call_point="embed_query"（生产配置表计量口径）随嵌入调用传递。"""
    d = _mk_direction(db_session)
    emb = RecordingEmbed(db_session)
    assert ensure_direction_query_vec(db_session, d, llm=RecordingLLM(db_session),
                                      embed_provider=emb) is True
    assert len(emb.calls) == 1
    kw = emb.calls[0]["kwargs"]
    assert "expected_dims" in kw
    assert kw["expected_dims"] == cfg.EMBED_DIMENSIONS
    assert kw["call_point"] == "embed_query"


def test_query_gen_persists_query_vec_blob(db_session, monkeypatch):
    """生成成功：查询向量以 BLOB 落列且可还原（G3 裁定④ query_vec 双列承载）。"""
    d = _mk_direction(db_session)
    assert ensure_direction_query_vec(db_session, d, llm=RecordingLLM(db_session),
                                      embed_provider=RecordingEmbed(db_session)) is True
    assert d.query_vec is not None
    restored = blob_to_vec(d.query_vec)
    assert np.allclose(restored, np.asarray([1.0] + [0.0] * 15, dtype=np.float32), atol=1e-6)
