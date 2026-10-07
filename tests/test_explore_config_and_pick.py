"""探索层参数合成与选样边界测试：site_config 读取与方向级覆盖、质量地板
等值边界、配额语义、MMR 选样方向语义。

覆盖口径：
- explore_params：site_config 显式配置值生效（AC-08.4「以配置注入非硬编码」，
  全部参数可配）；方向级 explore_config 对 floor/percentile/quota 逐键覆盖
  （DT-3：总开关+方向级）、显式 null 值不覆盖回退全局、覆盖值为 int 归一；
- explore_pick：quota=1 有效（配额语义非零一开关）、质量分恰等于地板的候选
  入选（DT-3「质量分 ≥ 地板」）、MMR 在候选与方向相似度参差时优先选与方向
  最不相似者（探索语义：「离方向更远」主导——MMR 形态追认面的方向语义）。
设计依据见 docs/design-index.md「AC-08.4」「AC-14.3」「DT-3」。
"""
import numpy as np

from app.retrieval.explore import explore_params, explore_pick


def _axis(axis, dims=8):
    v = np.zeros(dims, dtype=np.float32)
    v[axis] = 1.0
    return v


def _tilted(cos_x):
    return np.asarray([cos_x, (1 - cos_x ** 2) ** 0.5], dtype=np.float32)


class ConfigStub:
    """get_config 打桩：按键值表回答（未登记键返回 None，模拟无缺省回退的
    读取面）。"""

    def __init__(self, values):
        self.values = values

    def __call__(self, db, key):
        return self.values.get(key)


class _Direction:
    """direction 参数替身：仅携带 explore_config 属性。"""

    def __init__(self, explore_config=None):
        self.explore_config = explore_config


def test_explore_params_reads_explicit_site_config_values():
    """site_config 显式配置值（非缺省）逐键生效：floor/percentile/quota 取配置值
    （AC-08.4 参数可配条款）。"""
    get_config = ConfigStub({
        "explore_quality_floor": 70,
        "explore_distance_percentile": 8,
        "explore_quota_per_page": 2,
    })
    params = explore_params(object(), None, get_config=get_config)
    assert params["floor"] == 70
    assert params["percentile"] == 8
    assert params["quota"] == 2


def test_explore_params_direction_overrides_each_key():
    """方向级 explore_config 逐键覆盖全局（DT-3 方向级开关与参数覆盖）。"""
    get_config = ConfigStub({
        "explore_quality_floor": 50,
        "explore_distance_percentile": 5,
        "explore_quota_per_page": 3,
    })
    d = _Direction({"floor": 30, "percentile": 9, "quota": 2})
    params = explore_params(object(), d, get_config=get_config)
    assert params["floor"] == 30
    assert params["percentile"] == 9
    assert params["quota"] == 2


def test_explore_params_null_override_value_falls_back_to_global():
    """方向级显式 null 值不覆盖、回退全局值（覆盖语义：None=未设置）。"""
    get_config = ConfigStub({"explore_quality_floor": 50, "explore_quota_per_page": 3})
    d = _Direction({"floor": None, "quota": 2})
    params = explore_params(object(), d, get_config=get_config)
    assert params["floor"] == 50
    assert params["quota"] == 2


# ---------- explore_pick：边界与方向语义 ----------


def _cand(i, quality, vec, passed=False):
    return {"id": i, "quality": quality, "relevance": 30, "passed": passed, "vec": vec}


def test_explore_pick_quota_of_one_picks_one():
    d = _axis(0, dims=8)
    items = [_cand(1, 72, _axis(5, dims=8)), _cand(2, 72, _axis(6, dims=8))]
    picked = explore_pick(items, d, floor=50, percentile=100, quota=1)
    assert len(picked) == 1


def test_explore_pick_quality_equal_to_floor_is_eligible():
    """质量分恰等于地板：入选（DT-3 候选条件「质量分 ≥ 地板」）。"""
    d = _axis(0, dims=8)
    items = [_cand(1, 50, _axis(5, dims=8))]
    picked = explore_pick(items, d, floor=50, percentile=100, quota=3)
    assert [p["id"] for p in picked] == [1]


def test_explore_pick_prefers_farthest_from_direction():
    """MMR 首选：候选与方向相似度参差时优先选与方向最不相似者（探索语义——
    「离方向更远」主导）。"""
    d = _axis(0, dims=2)
    near = _cand(1, 72, _tilted(0.9))
    far = _cand(2, 72, _tilted(0.1))
    picked = explore_pick([near, far], d, floor=50, percentile=100, quota=1)
    assert [p["id"] for p in picked] == [2]
