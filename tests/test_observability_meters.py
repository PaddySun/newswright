"""可观测计量单元测试：db_size_mb/disk_free_mb/minutes_ago/llm_error_rate_24h/
db_writable/last_successful_task 的计量公式与字段值语义。

设计依据见 docs/design-index.md「AC-19.4」「AC-18.3」「AC-18.4」。
"""
from datetime import datetime, timedelta, timezone

from app.models import PipelineTask, UsageLog
from app.observability import (
    _db_size_mb,
    _db_writable,
    _disk_free_mb,
    _last_successful_task,
    _llm_error_rate_24h,
    _minutes_ago,
)


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _FakeDB:
    """按调用次序回放 PRAGMA 标量结果的桩（page_count → page_size）。"""

    def __init__(self, values):
        self._values = list(values)
        self.queries = []

    def execute(self, query):
        self.queries.append(str(query))
        return _FakeResult(self._values[len(self.queries) - 1])


def test_db_size_mb_computed_from_pragma_pages():
    """db_size_mb = page_count × page_size / 1MB，保留 2 位（计量本体）。"""
    db = _FakeDB([1000, 4096])
    assert _db_size_mb(db) == 3.91


def test_db_size_mb_empty_database_reports_zero():
    """空库（page_count=0）哨兵为 0.0（计量本体空库域）。"""
    db = _FakeDB([0, 4096])
    assert _db_size_mb(db) == 0.0


def test_disk_free_mb_reports_engine_volume_free_space(tmp_path, monkeypatch):
    """disk_free_mb = 引擎库文件所在卷剩余字节 / 1MB，保留 2 位；探测路径取
    当前 engine 的库文件（计量本体）。"""
    import shutil as _shutil

    import app.observability as obs

    db_file = tmp_path / "newswright.db"
    db_file.write_bytes(b"")

    recorded = {}

    class _FakeUsage:
        free = 3 * 1024 * 1024 + 700_000  # 3.67 MB

    def fake_disk_usage(path):
        recorded["path"] = path
        return _FakeUsage()

    class _FakeURL:
        database = str(db_file)

    class _FakeEngine:
        url = _FakeURL()

    monkeypatch.setattr(_shutil, "disk_usage", fake_disk_usage)
    monkeypatch.setattr(obs, "_current_engine", lambda: _FakeEngine())
    assert _disk_free_mb(None) == 3.67
    assert recorded["path"] == str(db_file)


def test_minutes_ago_value_semantics():
    """分钟差计量：整分钟与亚分钟舍入形态（1 位小数）。"""
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert _minutes_ago(base - timedelta(minutes=60), base) == 60.0
    assert _minutes_ago(base - timedelta(seconds=15), base) == 0.2
    assert _minutes_ago(base - timedelta(seconds=90), base) == 1.5


def test_minutes_ago_future_and_none():
    """未来时间戳钳制为 0.0；None 输入返回 None。"""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert _minutes_ago(now + timedelta(minutes=10), now) == 0.0
    assert _minutes_ago(None, now) is None


def _add_usage(db, *, ok, age_minutes, now):
    db.add(UsageLog(provider="p", model="m", call_point="scoring",
                    prompt_tokens=1, completion_tokens=1, ok=ok,
                    created_at=now - timedelta(minutes=age_minutes)))


def test_llm_error_rate_24h_ratio_within_window(db_session):
    """错误率 = 窗内失败行 / 窗内全部行，4 位舍入（AC-18.3 计量本体）。"""
    now = datetime.now(timezone.utc)
    _add_usage(db_session, ok=True, age_minutes=60, now=now)
    for _ in range(3):
        _add_usage(db_session, ok=False, age_minutes=120, now=now)
    db_session.commit()
    assert _llm_error_rate_24h(db_session, now) == 0.75


def test_llm_error_rate_24h_rounding_precision(db_session):
    now = datetime.now(timezone.utc)
    _add_usage(db_session, ok=True, age_minutes=60, now=now)
    _add_usage(db_session, ok=True, age_minutes=90, now=now)
    _add_usage(db_session, ok=False, age_minutes=120, now=now)
    db_session.commit()
    assert _llm_error_rate_24h(db_session, now) == 0.3333


def test_llm_error_rate_24h_empty_window_zero(db_session):
    """空窗（无任何调用）错误率为 0.0 而非虚警值。"""
    now = datetime.now(timezone.utc)
    assert _llm_error_rate_24h(db_session, now) == 0.0


def test_llm_error_rate_24h_excludes_out_of_window(db_session):
    """窗外（25h 前）失败不计入分子分母；窗内成功失败混排按窗内口径。"""
    now = datetime.now(timezone.utc)
    _add_usage(db_session, ok=False, age_minutes=25 * 60, now=now)
    db_session.commit()
    assert _llm_error_rate_24h(db_session, now) == 0.0
    _add_usage(db_session, ok=True, age_minutes=60, now=now)
    db_session.commit()
    assert _llm_error_rate_24h(db_session, now) == 0.0


def test_llm_error_rate_24h_no_failures_zero(db_session):
    """窗内只有成功行时错误率为 0.0。"""
    now = datetime.now(timezone.utc)
    _add_usage(db_session, ok=True, age_minutes=60, now=now)
    db_session.commit()
    assert _llm_error_rate_24h(db_session, now) == 0.0


def test_db_writable_probe_false_on_engine_failure(monkeypatch):
    """写探针在引擎故障时返回 False（AC-18.4 db 不可写→503 的探测承载）。"""
    import app.observability as obs

    class _BoomEngine:
        def connect(self):
            raise RuntimeError("engine down")

    monkeypatch.setattr(obs, "_current_engine", lambda: _BoomEngine())
    assert _db_writable(None) is False


def test_last_successful_task_latest_done_per_kind(db_session):
    """最近一次成功任务：同 kind 取最新 DONE（跨 kind/RUNNING 不混入）。"""
    now = datetime.now(timezone.utc)

    def _task(kind, status, age_minutes):
        db_session.add(PipelineTask(kind=kind, status=status, payload={},
                                    created_at=now - timedelta(minutes=age_minutes),
                                    updated_at=now - timedelta(minutes=age_minutes)))

    _task("fetch", "DONE", 120)   # 最早：rowid 序最先插入
    _task("fetch", "DONE", 8)     # 该 kind 最新 DONE
    _task("score", "DONE", 3)     # 跨 kind 最新（不得混入 fetch 维度）
    _task("fetch", "RUNNING", 2)  # 非 DONE 终态（不得计入成功）
    db_session.commit()
    result = _last_successful_task(db_session, "fetch")
    age = (now - result.replace(tzinfo=timezone.utc)).total_seconds() / 60
    assert 5 <= age <= 12
