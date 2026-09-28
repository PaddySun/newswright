"""OV2 单测：防蒙蔽穿插概率语义与开关行为（拍板④）。"""
from app.api.routes import interleave_low_score


def _ranked(n):
    return [{"id": i, "relevance": 90, "band": "high"} for i in range(100, 100 + n)]


def _low(n):
    return [{"id": 1000 + i, "relevance": 45, "band": "medium"} for i in range(n)]


def test_interleave_off_returns_unchanged():
    ranked = _ranked(5)
    out, meta = interleave_low_score(ranked, _low(5), probability=0.9, enabled=False)
    assert out == ranked and meta["inserted"] == 0 and meta["enabled"] is False


def test_interleave_probability_semantics_seed_fixed():
    """固定 seed：插入条目来自低分池、顺序保持、带 low_interleaved 标记。"""
    ranked, low = _ranked(10), _low(5)
    out, meta = interleave_low_score(ranked, low, probability=1.0, enabled=True, seed=42)
    assert meta["inserted"] == 5  # 概率 1.0 → 每个空位都插（池 5 条用尽）
    assert out[:2] == [out[0], out[1]]
    low_ids = [x["id"] for x in out if x["band"] == "low_interleaved"]
    assert low_ids == [1000, 1001, 1002, 1003, 1004]
    # 高分条目相对顺序不变（穿插不重排）
    hi = [x["id"] for x in out if x["band"] != "low_interleaved"]
    assert hi == [i for i in range(100, 110)]


def test_interleave_zero_probability_noop():
    ranked, low = _ranked(5), _low(3)
    out, meta = interleave_low_score(ranked, low, probability=0.0, seed=1)
    assert [x["id"] for x in out] == [x["id"] for x in ranked] and meta["inserted"] == 0


def test_interleave_empty_pool_noop():
    ranked = _ranked(5)
    out, meta = interleave_low_score(ranked, [], probability=0.9, seed=1)
    assert out == ranked and meta["inserted"] == 0
