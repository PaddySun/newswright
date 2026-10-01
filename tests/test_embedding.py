"""M18 测试：向量生成底座——分批、计量落账（call_point=embed + item_count）、
dimensions 透传、维度校验、注册表。真实 HTTP 不出网（_embed_request 打桩）。"""
import pytest

from app.embedding import registry as embed_registry
from app.embedding.base import EmbeddingError, EmbeddingProvider
from app.embedding.moark import MoarkEmbeddingProvider
from app.models import UsageLog


class FakeEmbedProvider(EmbeddingProvider):
    name = "fake_embed"
    model_name = "fake-model"

    def __init__(self, db, *, fail_times=0, wrong_dims=False, drop_one=False):
        super().__init__(db)
        self.calls: list[dict] = []
        self.fail_times = fail_times
        self.wrong_dims = wrong_dims
        self.drop_one = drop_one

    def _embed_request(self, inputs, dimensions):
        self.calls.append({"inputs": list(inputs), "dimensions": dimensions})
        if self.fail_times > 0:
            self.fail_times -= 1
            raise EmbeddingError("HTTP 500: boom")
        import httpx

        raise_for_test = getattr(self, "_transient", 0)
        if raise_for_test > 0:
            self._transient -= 1
            e = EmbeddingError("HTTP 503: transient")
            e.retryable = True  # type: ignore[attr-defined]
            raise e
        dim = 4 if not self.wrong_dims else 3
        vecs = [[0.1 * (j + 1)] * dim for j in range(len(inputs))]
        if self.drop_one and vecs:
            vecs = vecs[:-1]
        return vecs, {"prompt_tokens": 10 * len(inputs)}


def test_batching_and_order(db_session):
    p = FakeEmbedProvider(db_session, )
    texts = [f"t{i}" for i in range(70)]
    vecs = p.embed(texts, batch_size=32)
    assert len(vecs) == 70
    # 70 条按 32/32/6 三批
    assert [len(c["inputs"]) for c in p.calls] == [32, 32, 6]
    assert p.calls[0]["inputs"][0] == "t0"
    assert p.calls[2]["inputs"][-1] == "t69"


def test_metering_records_item_count_and_call_point(db_session):
    p = FakeEmbedProvider(db_session)
    p.embed(["a", "b", "c"], batch_size=2, call_point="embed")
    rows = db_session.query(UsageLog).filter_by(provider="fake_embed").all()
    assert len(rows) == 2
    assert all(r.call_point == "embed" for r in rows)
    assert sorted(r.item_count for r in rows) == [1, 2]
    assert sum(r.prompt_tokens for r in rows) == 30
    assert all(r.ok for r in rows)


def test_empty_input_no_call(db_session):
    p = FakeEmbedProvider(db_session)
    assert p.embed([]) == []
    assert p.calls == []


def test_expected_dims_mismatch_raises_no_retry(db_session):
    p = FakeEmbedProvider(db_session, wrong_dims=True)
    with pytest.raises(EmbeddingError, match="不一致"):
        p.embed(["a"], expected_dims=4)
    # 校验失败不重试：只有一次尝试、一条失败账
    rows = db_session.query(UsageLog).all()
    assert len(rows) == 0  # 校验异常在落账前抛出


def test_count_mismatch_raises(db_session):
    p = FakeEmbedProvider(db_session, drop_one=True)
    with pytest.raises(EmbeddingError, match="不一致"):
        p.embed(["a", "b"])


def test_transient_failure_retries_then_records_error(db_session):
    p = FakeEmbedProvider(db_session)
    p._transient = 1
    import app.embedding.base as base_mod

    orig_sleep = base_mod.time.sleep
    base_mod.time.sleep = lambda s: None
    try:
        vecs = p.embed(["a", "b"])
    finally:
        base_mod.time.sleep = orig_sleep
    assert len(vecs) == 2
    rows = db_session.query(UsageLog).filter_by(provider="fake_embed").all()
    assert len(rows) == 2  # 1 失败 + 1 成功
    assert sorted(r.ok for r in rows) == [False, True]


def test_registry_get_with_model_param(db_session):
    # 注册名 moark 存在；model 参数化出实例
    names = embed_registry.available()
    assert "moark" in names
    p = embed_registry.get_provider("moark", db_session, model="bge-m3")
    assert isinstance(p, MoarkEmbeddingProvider)
    assert p.model_name == "bge-m3"
    p2 = embed_registry.get_provider("moark", db_session)
    assert p2.model_name  # 默认模型名非空


def test_dimensions_passthrough(db_session):
    p = FakeEmbedProvider(db_session)
    p.embed(["a"], dimensions=256)
    assert p.calls[0]["dimensions"] == 256
    p.embed(["a"])
    assert p.calls[1]["dimensions"] is None
