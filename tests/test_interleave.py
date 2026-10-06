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


def test_interleave_same_seed_reproducible():
    """同 seed 两次调用结果完全一致——seed 的存在意义即确定性复现（穿插函数
    契约：seed 供测试确定性复现）。随机源丢失 seed 时两次调用必然分歧。
    设计依据见 docs/design-index.md「OV2 防蒙蔽穿插（模块说明：seed 确定性）」。
    """
    args = dict(probability=0.6, enabled=True, seed=7)
    out1, meta1 = interleave_low_score(_ranked(30), _low(8), **args)
    out2, meta2 = interleave_low_score(_ranked(30), _low(8), **args)
    assert out1 == out2
    assert meta1 == meta2
