"""C1-9b 收官补测（统筹亲执）：interleave_low_score 全合同测试。

> 追溯注记：本文件原名 tests/test_mutation_c1_9b.py（原批次代号见文件名），按对象重命名于 F1⑫治理批。

种子：doc/CI0/C1-9b-种子.jsonl（8 条幸存，app.api.routes 唯一漏扫函数）。
条款依据：产品书 v1.6 DT-3「拍板④穿插」（rel<方向阈值且≥最低阈值、概率 p、
真实分数原样、low_interleaved 标记）+ AC-14.1（阈值过滤限定常规条目——穿插条目
独立于阈值过滤）+ 函数 docstring（meta 三键/池尽即止/seed 确定性）。
杀死目标：8 条幸存变异（合同断言面）；408-409 死代码行的等价变异由收官 dispatch
权威对账归类（预计 A）。
"""
import random

from app.api.routes import interleave_low_score


def _items(*names):
    return [{"id": i, "title": n} for i, n in enumerate(names, start=1)]


def test_fixed_seed_full_probability_interleaves_all_slots():
    """DT-3 拍板④：p=1.0 时每个空位插入一条低分条目，池尽即止。

    Given ranked=[a,b,c]、low_pool=[l1,l2]、probability=1.0、seed 固定；
    When 穿插；Then 输出 [l1,a,l2,b,c]——低分条目带 band=low_interleaved
    且其余字段保真，ranked 条目原样（真实评分/字段不变），inserted==2。
    """
    ranked = _items("a", "b", "c")
    low = _items("l1", "l2")
    out, meta = interleave_low_score(ranked, low, probability=1.0, seed=7)
    assert [x["title"] for x in out] == ["l1", "a", "l2", "b", "c"]
    interleaved = [x for x in out if x.get("band") == "low_interleaved"]
    assert [x["title"] for x in interleaved] == ["l1", "l2"]
    # 低分条目原字段保真（DT-3：真实内容展示，仅加标记）
    assert interleaved[0]["id"] == 1 and interleaved[1]["id"] == 2
    # ranked 条目不被加 band（诚实展示原条目）
    assert all("band" not in x for x in out if x["title"] in {"a", "b", "c"})
    assert meta == {"enabled": True, "probability": 1.0, "inserted": 2}


def test_pool_exhaustion_stops_inserting_and_preserves_ranked_order():
    """DT-3：低分池用尽即止；ranked 子序列顺序不变（真实评分排序不被打乱）。"""
    ranked = _items("a", "b", "c", "d")
    low = _items("l1")
    out, meta = interleave_low_score(ranked, low, probability=1.0, seed=42)
    assert [x["title"] for x in out] == ["l1", "a", "b", "c", "d"]
    assert meta["inserted"] == 1
    # ranked 相对顺序保持
    seq = [x["title"] for x in out if x["title"] in {"a", "b", "c", "d"}]
    assert seq == ["a", "b", "c", "d"]


def test_meta_echoes_enabled_false_and_probability():
    """docstring 合同：meta 回显 enabled/probability，插入计数为 0。"""
    out, meta = interleave_low_score(_items("a"), _items("l1"), probability=0.5,
                                     enabled=False, seed=1)
    assert out == [{"id": 1, "title": "a"}]
    assert meta == {"enabled": False, "probability": 0.5, "inserted": 0}


def test_seed_determinism_repeats_identically():
    """docstring：seed 供确定性复现——同 seed 两次调用输出逐项一致。"""
    args = (_items("a", "b", "c", "d"), _items("l1", "l2"))
    out1, m1 = interleave_low_score(*args, probability=0.6, seed=99)
    out2, m2 = interleave_low_score(*args, probability=0.6, seed=99)
    assert out1 == out2 and m1 == m2
    # 与裸 random.Random(99) 的判定序列一致（p=0.6；插入数=触发数截断于池容量 2）
    rng = random.Random(99)
    expected = [rng.random() < 0.6 for _ in range(4)]
    assert m1["inserted"] == min(sum(expected), 2)


def test_boundary_probability_zero_returns_ranked_with_zero_meta():
    """DT-3 边界：p=0 时零插入（与既有 zero-probability 测试互补，补 meta 全量）。"""
    out, meta = interleave_low_score(_items("a", "b"), _items("l1"), probability=0.0,
                                     seed=3)
    assert [x["title"] for x in out] == ["a", "b"]
    assert meta == {"enabled": True, "probability": 0.0, "inserted": 0}
