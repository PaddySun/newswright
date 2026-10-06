"""向量落库基座测试：批量嵌入补齐、按批计量、护栏失败不落错向量、禁用与失败回退。

覆盖口径：
- 计量按批落行：usage_log 行数 = ceil(条数/批上限)、item_count 总和 = 条数、
  模型名随行落账（产品书 US-08 打分前嵌入计量钉死口径）；
- 数量/维度护栏失败：不落错误向量、不向上抛入打分轮；
- model_version 纪律：模型版本不匹配视同无向量（换模型场景渐进补齐的依据）；
- 旧库升级：item_vec 为新表，init_db 对既有库补建（create_all 语义）。
设计依据见 docs/design-index.md「AC-08.1」「AC-08.5」。
"""
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine, inspect

import app.config as cfg
import app.db as appdb
from app.embedding.base import EmbeddingProvider
from app.models import Direction, Item, ItemVec, Source, UsageLog
from app.retrieval.embedder import (
    blob_to_vec,
    embed_input_text,
    ensure_item_vectors,
    vec_to_blob,
)


class StubEmbedProvider(EmbeddingProvider):
    """ensure_item_vectors 的打桩 provider：记录每批输入，可注入失败与错误形状。"""

    name = "stub_embed"

    def __init__(self, db, *, model="stub-model-v1", fail_batches=0,
                 fail_from_batch=None, drop_one=False, wrong_dims=False, dims=1024):
        super().__init__(db)
        self._model = model
        self.fail_batches = fail_batches
        self.fail_from_batch = fail_from_batch
        self.drop_one = drop_one
        self.wrong_dims = wrong_dims
        self.dims = dims
        self.batches: list[list[str]] = []

    @property
    def model_name(self) -> str:
        return self._model

    def _embed_request(self, inputs, dimensions):
        from app.embedding.base import EmbeddingError

        self.batches.append(list(inputs))
        if self.fail_batches > 0:
            self.fail_batches -= 1
            raise EmbeddingError("stub: 嵌入调用失败")
        if self.fail_from_batch is not None and len(self.batches) - 1 >= self.fail_from_batch:
            raise EmbeddingError("stub: 该批嵌入调用失败")
        vecs = [[0.1] * self.dims for _ in inputs]
        if self.drop_one and vecs:
            vecs = vecs[:-1]
        if self.wrong_dims:
            vecs = [v[:-1] for v in vecs]
        return vecs, {}


def _mk_item(db, *, guid="g1", title="标题", body="正文内容"):
    d = db.query(Direction).first()
    if d is None:
        d = Direction(name="方向", prompt="p", threshold=60)
        db.add(d)
        db.commit()
    src = Source(direction_id=d.id, url="https://example.com/rss")
    db.add(src)
    db.commit()
    item = Item(source_id=src.id, guid=guid, url="https://example.com/a",
                title=title, content_text=body, fetch_status="FETCHED",
                direction_id=d.id, sanitize_status="PASSED")
    db.add(item)
    db.commit()
    return item


# ---------- 纯函数 ----------


def test_vec_blob_roundtrip_preserves_values():
    vec = [0.25, -1.5, 3.0, 0.0]
    restored = blob_to_vec(vec_to_blob(vec))
    assert restored.dtype == np.float32
    assert np.allclose(restored, np.asarray(vec), atol=1e-6)


def test_embed_input_text_keeps_title_and_truncates_body():
    item = Item(title="标题文字", content_text="x" * 3000)
    text = embed_input_text(item, truncate_chars=2000)
    assert text.startswith("标题文字")
    body_part = text[len("标题文字\n"):]
    assert len(body_part) == 2000


# ---------- ensure_item_vectors ----------


def test_batch_metering_65_items_three_rows(db_session):
    items = [_mk_item(db_session, guid=f"g{i}") for i in range(65)]
    provider = StubEmbedProvider(db_session, model="Qwen3-Embedding-0.6B")
    stats = ensure_item_vectors(db_session, items, provider=provider, batch_size=32)
    assert stats["embedded"] == 65
    rows = db_session.query(UsageLog).filter_by(provider="stub_embed").all()
    assert len(rows) == 3  # ceil(65/32)
    assert sum(r.item_count for r in rows) == 65
    assert all(r.model == "Qwen3-Embedding-0.6B" for r in rows)
    assert len(provider.batches) == 3


def test_count_mismatch_stores_no_vectors_and_no_raise(db_session):
    items = [_mk_item(db_session, guid="a"), _mk_item(db_session, guid="b")]
    provider = StubEmbedProvider(db_session, drop_one=True)
    stats = ensure_item_vectors(db_session, items, provider=provider, batch_size=32)
    assert stats["embedded"] == 0
    assert db_session.query(ItemVec).count() == 0


def test_dims_mismatch_stores_no_vectors_and_no_raise(db_session):
    items = [_mk_item(db_session, guid="a")]
    provider = StubEmbedProvider(db_session, wrong_dims=True)
    stats = ensure_item_vectors(db_session, items, provider=provider)
    assert stats["embedded"] == 0
    assert db_session.query(ItemVec).count() == 0


def test_model_version_mismatch_treated_as_missing(db_session):
    item = _mk_item(db_session, guid="a")
    db_session.add(ItemVec(item_id=item.id, model_version="old-model",
                           vec=vec_to_blob([0.1] * 1024)))
    db_session.commit()
    provider = StubEmbedProvider(db_session, model="new-model")
    stats = ensure_item_vectors(db_session, [item], provider=provider)
    assert stats["missing"] == 1 and stats["embedded"] == 1
    versions = {v.model_version for v in db_session.query(ItemVec).all()}
    assert versions == {"old-model", "new-model"}


def test_same_model_version_not_reembedded(db_session):
    item = _mk_item(db_session, guid="a")
    provider = StubEmbedProvider(db_session, model="m1")
    ensure_item_vectors(db_session, [item], provider=provider)
    stats = ensure_item_vectors(db_session, [item], provider=provider)
    assert stats["missing"] == 0 and stats["embedded"] == 0
    assert len(provider.batches) == 1  # 第二轮零调用


def test_embed_failure_swallowed_not_raised(db_session):
    items = [_mk_item(db_session, guid=f"g{i}") for i in range(3)]
    provider = StubEmbedProvider(db_session, fail_batches=1)
    stats = ensure_item_vectors(db_session, items, provider=provider)
    assert stats["embedded"] == 0 and stats["failed"] == 3
    assert db_session.query(ItemVec).count() == 0


def test_disabled_model_key_skips_everything(db_session, monkeypatch):
    items = [_mk_item(db_session, guid="a")]
    monkeypatch.setattr(cfg, "MOARK_EMBED_MODEL", "none")
    provider = StubEmbedProvider(db_session)
    stats = ensure_item_vectors(db_session, items, provider=provider)
    assert stats["disabled"] is True
    assert provider.batches == []  # 禁用态不产生任何嵌入调用
    assert db_session.query(ItemVec).count() == 0


def test_per_batch_short_commit_visible_midway(db_session):
    """逐批短事务：首批已提交落库后，后续批失败不影响已落库部分。"""
    items = [_mk_item(db_session, guid=f"g{i}") for i in range(4)]
    provider = StubEmbedProvider(db_session, fail_from_batch=1)  # 首批成功、次批起失败
    stats = ensure_item_vectors(db_session, items, provider=provider, batch_size=2)
    assert stats["embedded"] == 2
    assert db_session.query(ItemVec).count() == 2


# ---------- 旧库升级：item_vec 新表补建 ----------


@pytest.fixture()
def pre_vec_db():
    import tempfile

    tmpdir = Path(tempfile.mkdtemp())
    tmp = tmpdir / "legacy.db"
    url = f"sqlite:///{tmp.as_posix()}"
    engine = create_engine(url, future=True)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE direction (id INTEGER PRIMARY KEY, name VARCHAR(200), enabled BOOLEAN DEFAULT 1)")
        conn.exec_driver_sql("CREATE TABLE item (id INTEGER PRIMARY KEY, source_id INTEGER, guid VARCHAR(1000))")
    yield url, engine
    engine.dispose()
    import shutil

    shutil.rmtree(tmpdir, ignore_errors=True)


def test_init_db_creates_item_vec_on_legacy_db(pre_vec_db, monkeypatch):
    url, old_engine = pre_vec_db
    monkeypatch.setattr(appdb, "engine", old_engine)
    from app.db import init_db

    init_db()
    insp = inspect(old_engine)
    assert insp.has_table("item_vec")
    cols = {c["name"] for c in insp.get_columns("item_vec")}
    assert {"item_id", "model_version", "vec"} <= cols
    uniques = insp.get_unique_constraints("item_vec")
    assert any(u["column_names"] == ["item_id", "model_version"] for u in uniques)
