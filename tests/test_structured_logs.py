"""结构化日志测试：JSON 行可解析、必填字段、认领点/中间件上下文注入、错误行 ref。

soak 口径：测试内跑多轮真实任务（全 mock）后逐行 json.loads 校验——完整
≥2 小时 soak 为部署验证项，本批以分钟级 soak 测试代偿。
设计依据见 docs/design-index.md「ADR-12」。
"""
import json
import logging

from app.logging_setup import (
    current_log_context,
    setup_logging,
    teardown_logging,
)
from app.models import PipelineTask
from app.pipeline.runner import _claim, _finish, _new_task, score_round


def _read_lines(path):
    with open(path, encoding="utf-8") as f:
        return [line for line in f.read().splitlines() if line.strip()]


def _setup_tmp_log(tmp_path, monkeypatch):
    log_file = tmp_path / "soak.log"
    monkeypatch.setenv("NEWSWRIGHT_LOG_FILE", str(log_file))
    monkeypatch.setenv("NEWSWRIGHT_LOG_CONSOLE", "0")
    setup_logging()
    return log_file


REQUIRED = ("ts", "level", "call_point", "task_id", "site", "route", "actor")


def test_soak_every_line_json_with_required_fields(tmp_path, monkeypatch,
                                                   db_session, auth_client):
    log_file = _setup_tmp_log(tmp_path, monkeypatch)
    score_task_id = None
    try:
        # 多轮真实任务（全 mock）：打分轮走真实 score_round 代码路径（单条异常
        # 落 WARN 日志——真实处理路径的日志留痕）+ HTTP 请求 + 错误行
        from app.models import Direction, Item, Source

        d = Direction(name=" soak方向", prompt="p", threshold=60)
        db_session.add(d)
        db_session.commit()
        src = Source(direction_id=d.id, url="https://x.com/rss")
        db_session.add(src)
        db_session.commit()
        db_session.add(Item(source_id=src.id, guid="s1", url="https://x.com/1",
                            title="t", content_text="正文", fetch_status="FETCHED",
                            direction_id=d.id, sanitize_status="PASSED"))
        db_session.commit()

        def llm_down(db, item, direction):
            raise RuntimeError("LLM down")

        monkeypatch.setattr("app.scoring.service.score_item", llm_down)
        summary = score_round(db_session, triggered_by="soak")
        score_task_id = summary["directions"][0]["task_id"]
        auth_client.get("/healthz")
        # 错误行：stack_id = 错误详情落库行 id（task.last_error 即详情，ref=task.id）
        failed_task = (db_session.query(PipelineTask)
                       .filter_by(kind="score", status="FAILED").first())
        logging.getLogger("newswright.test.soak").error(
            "任务终态失败", extra={"error_code": "TASK_FAILED",
                                  "stack_id": failed_task.id})
    finally:
        teardown_logging()

    lines = _read_lines(log_file)
    assert len(lines) > 3  # 打分 WARN 行 + HTTP 行 + 错误行均有留痕
    parsed = []
    for line in lines:
        row = json.loads(line)  # 每行必须可解析
        parsed.append(row)
        for field in REQUIRED:
            assert field in row, f"缺必填字段 {field}: {line}"
        assert row["site"] == "newswright"
    # 任务认领点注入：score 处理路径的日志行携带 task_id 与 call_point
    assert any(r["call_point"] == "score" and r["task_id"] == score_task_id
               for r in parsed)
    # 中间件注入：HTTP 行带 route + actor（已登录会话身份）
    assert any(r["route"] == "/healthz" and r["actor"] == "admin"
               for r in parsed)
    # 错误行三件套
    err = [r for r in parsed if r["level"] == "ERROR"
           and r["error_code"] == "TASK_FAILED"]
    assert err and err[0]["stack_id"] == failed_task.id
    assert err[0]["error_msg"]


def test_claim_point_context_write_and_clear(db_session):
    task = _new_task(db_session, kind="fetch", payload={"source_id": 1})
    ctx = current_log_context()
    assert ctx["task_id"] == task.id and ctx["call_point"] == "fetch"
    assert _claim(db_session, task) is True
    _finish(db_session, task, status="DONE")
    ctx = current_log_context()
    assert ctx["task_id"] is None and ctx["call_point"] is None


def test_error_line_without_extra_has_null_ref_fields(tmp_path, monkeypatch):
    log_file = _setup_tmp_log(tmp_path, monkeypatch)
    try:
        logging.getLogger("newswright.test.bare").error("裸错误行")
    finally:
        teardown_logging()
    rows = [json.loads(l) for l in _read_lines(log_file)]
    err = [r for r in rows if r["level"] == "ERROR"
           and r["logger"] == "newswright.test.bare"]
    assert err
    assert {"error_code", "error_msg", "stack_id"} <= set(err[0].keys())
    assert err[0]["stack_id"] is None


def test_rotation_parameters_pinned(tmp_path, monkeypatch):
    """轮转按大小 10MB×5（参数钉死，创建 handler 验证）。"""
    from logging.handlers import RotatingFileHandler

    from app.logging_setup import LOG_BACKUP_COUNT, LOG_MAX_BYTES

    assert LOG_MAX_BYTES == 10 * 1024 * 1024
    assert LOG_BACKUP_COUNT == 5
    log_file = tmp_path / "rot.log"
    monkeypatch.setenv("NEWSWRIGHT_LOG_FILE", str(log_file))
    setup_logging()
    try:
        root_handlers = [h for h in logging.getLogger().handlers
                         if isinstance(h, RotatingFileHandler)]
        assert root_handlers
        assert root_handlers[0].maxBytes == LOG_MAX_BYTES
        assert root_handlers[0].backupCount == LOG_BACKUP_COUNT
    finally:
        teardown_logging()
