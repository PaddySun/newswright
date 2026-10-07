"""嵌入基座护栏与计量口径测试：余弦相似度数学语义、provider 解析链、
嵌入输入截断配置语义、批量与计量 kwarg 护栏。

覆盖口径：
- cosine_similarity：非单位长向量对返回标准余弦值（分子点积 / 分母范数积）——
  相似度阈值语义（AC-08.3 达阈值判重、DT-2 命中排序）依赖该数学语义；
- default_provider：启用态解析 moark provider（db 归因参数随构造传递），
  禁用态返回 None（G3 裁定②：嵌入禁用=整体回退全量慢速的回退件）；
- embed_input_text：不显式覆写截断时按 config.EMBED_TRUNCATE_CHARS 截正文、
  标题恒保留（生产配置表：正文截断 2000，M18-M20 实测锚）；
- ensure_item_vectors：未注入 provider 时经注册表按 moark 解析（AC-08.1 计量
  口径的调用链）；批量上限 batch_size 与计量口径 call_point="embed" 随调用
  传递（ADR-3 批量 ≤32 护栏 + 生产配置表 call_point=embed 计量）。
设计依据见 docs/design-index.md「AC-08.1」「AC-08.5」「ADR-3」。
"""
import numpy as np
import pytest

import app.config as cfg
from app.embedding.base import EmbeddingProvider
from app.models import Direction, Item, ItemVec, Source, UsageLog
from app.retrieval.embedder import (
    blob_to_vec,
    cosine_similarity,
    default_provider,
    embed_input_text,
    ensure_item_vectors,
)


def _vec2(x, y):
    v = np.array([x, y], dtype=np.float32)
    return v


# ---------- cosine_similarity ----------


def test_cosine_similarity_non_unit_vectors_exact_value():
    a = _vec2(1.0, 0.0)
    b = _vec2(2.0, 0.0)  # 同向但非单位长：余弦=1
    assert cosine_similarity(a, b) == pytest.approx(1.0)
    c = _vec2(0.0, 3.0)  # 正交：余弦=0
    assert cosine_similarity(a, c) == pytest.approx(0.0)
    d = _vec2(0.5, 0.5)
    assert cosine_similarity(a, d) == pytest.approx(np.sqrt(0.5), rel=1e-5)


# ---------- default_provider ----------


class RegistryStub:
    """registry.get_provider 打桩：记录调用参数，返回可识别的 stub provider。"""

    last_args = None
    provider = None

    @classmethod
    def reset(cls, provider):
        cls.last_args = None
        cls.provider = provider

    @classmethod
    def get_provider(cls, name, db, *, model=None):
        cls.last_args = (name, db)
        return cls.provider


class _StubProvider(EmbeddingProvider):
    name = "stub"

    def __init__(self, db):
        super().__init__(db)

    @property
    def model_name(self):
        return "stub-model"

    def _embed_request(self, inputs, dimensions):
        return [[0.1] * (dimensions or 8) for _ in inputs], {}


def test_default_provider_resolves_moark_with_db_when_enabled(db_session, monkeypatch):
    RegistryStub.reset(_StubProvider(db_session))
    monkeypatch.setattr("app.retrieval.embedder.registry", RegistryStub)
    p = default_provider(db_session)
    assert p is RegistryStub.provider
    assert RegistryStub.last_args == ("moark", db_session)


def test_default_provider_returns_none_when_disabled(db_session, monkeypatch):
    monkeypatch.setattr(cfg, "MOARK_EMBED_MODEL", "none")
    assert default_provider(db_session) is None


# ---------- embed_input_text：配置截断语义 ----------


def test_embed_input_text_default_truncation_from_config(db_session):
    """生产调用形态（不覆写截断参数）：正文按 config.EMBED_TRUNCATE_CHARS 截断、
    标题恒保留（生产配置表实测锚：截 2000 与全文差 ≤5pp）。"""
    item = Item(title="标题恒保留", content_text="x" * (cfg.EMBED_TRUNCATE_CHARS + 500))
    text = embed_input_text(item)
    assert text.startswith("标题恒保留")
    body_part = text[len("标题恒保留\n"):]
    assert len(body_part) == cfg.EMBED_TRUNCATE_CHARS


# ---------- ensure_item_vectors：provider 解析链与护栏 kwarg ----------


class KwargRecordingProvider(EmbeddingProvider):
    """记录 embed 收到的 kwargs 与逐批输入，用于护栏 kwarg 断言。"""

    name = "stub_kw"

    def __init__(self, db, *, dims=None):
        super().__init__(db)
        self.dims = dims if dims is not None else cfg.EMBED_DIMENSIONS
        self.embed_kwargs = []
        self.batches = []

    @property
    def model_name(self):
        return "kw-stub-model"

    def _embed_request(self, inputs, dimensions):
        self.batches.append(list(inputs))
        return [[0.1] * self.dims for _ in inputs], {}

    def embed(self, texts, **kwargs):
        self.embed_kwargs.append(dict(kwargs))
        return super().embed(texts, **kwargs)


def _mk_items(db, n):
    d = db.query(Direction).first()
    if d is None:
        d = Direction(name="方向", prompt="p", threshold=60)
        db.add(d)
        db.commit()
    src = Source(direction_id=d.id, url="https://example.com/rss")
    db.add(src)
    db.commit()
    items = []
    for i in range(n):
        item = Item(source_id=src.id, guid=f"g{i}", url=f"https://example.com/{i}",
                    title=f"标题{i}", content_text="正文", fetch_status="FETCHED",
                    direction_id=d.id, sanitize_status="PASSED")
        db.add(item)
        items.append(item)
    db.commit()
    return items


def test_ensure_item_vectors_resolves_provider_via_registry(db_session, monkeypatch):
    """未注入 provider：经注册表按配置解析（moark + db 归因），向量照常落库——
    生产 runner 调用形态（AC-08.1 嵌入补齐链路）。落库向量值须为真实嵌入产物
    （AC-08.5 不落错误向量：NaN 占位不可入库）。"""
    items = _mk_items(db_session, 2)
    RegistryStub.reset(KwargRecordingProvider(db_session))
    monkeypatch.setattr("app.retrieval.embedder.registry", RegistryStub)
    stats = ensure_item_vectors(db_session, items)
    assert stats["embedded"] == 2
    assert RegistryStub.last_args == ("moark", db_session)
    rows = db_session.query(ItemVec).all()
    assert len(rows) == 2
    for row in rows:
        restored = blob_to_vec(row.vec)
        assert np.isfinite(restored).all()
        assert np.allclose(restored, 0.1, atol=1e-6)


def test_ensure_item_vectors_passes_batch_guard_and_metering_point(db_session):
    """批量护栏与计量口径随调用传递：batch_size=注入值、计量口径值=embed（ADR-3
    批量 ≤32 + 生产配置表 call_point=embed 计量口径——口径值以 provider 实际
    收到的效果值为准，显式 kwarg 或基类缺省均满足）。"""
    items = _mk_items(db_session, 3)
    stub = KwargRecordingProvider(db_session)
    stats = ensure_item_vectors(db_session, items, provider=stub, batch_size=2)
    assert stats["embedded"] == 3
    assert len(stub.embed_kwargs) == 2  # ceil(3/2)
    for kw in stub.embed_kwargs:
        assert kw.get("batch_size") == 2
        assert kw.get("call_point", "embed") == "embed"


def test_ensure_item_vectors_default_batch_from_config(db_session):
    """不覆写批量：batch_size 取 config.EMBED_BATCH_SIZE 随调用传递（护栏缺省口径）。"""
    items = _mk_items(db_session, 1)
    stub = KwargRecordingProvider(db_session)
    stats = ensure_item_vectors(db_session, items, provider=stub)
    assert stats["embedded"] == 1
    assert stub.embed_kwargs[0].get("batch_size") == cfg.EMBED_BATCH_SIZE
    assert stub.embed_kwargs[0].get("call_point", "embed") == "embed"
