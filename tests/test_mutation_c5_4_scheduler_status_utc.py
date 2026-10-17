"""调度器状态时间戳的 aware-UTC 输出契约（no-tests 转幸存老族分诊补面）。

覆盖：status() 输出的时间戳（checked_at 值）必为 aware-UTC 形态
（isoformat 含 +00:00 时区后缀）——后端时间取值与输出一律 aware-UTC
（时区双层口径：timezone 键职责=日切口径与用户侧呈现，不涉后端输出）。
断言只钉值语义不钉键名（响应键契约不在本断言射程）。
设计依据见 docs/design-index.md「D16」。
"""
import app.scheduler as scheduler_mod


def test_status_timestamp_is_aware_utc():
    st = scheduler_mod.status()
    ts_values = [v for v in st.values() if isinstance(v, str) and "T" in v]
    assert ts_values, "status() 应含 ISO 时间戳输出"
    assert all(v.endswith("+00:00") for v in ts_values), \
        "后端时间输出必须为 aware-UTC（含 +00:00 后缀）"
