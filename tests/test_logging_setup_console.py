"""结构化日志 console 输出面测试：默认安装 console handler、console 行为统一
JSON formatter 且携带 contextvars 注入上下文。

设计依据见 docs/design-index.md「ADR-12」。
"""
import io
import json
import logging


def test_console_handler_installed_by_default(monkeypatch):
    """未设任何日志环境变量时 console handler 默认安装（NEWSWRIGHT_LOG_FILE
    未设=仅 console 追认形态的承载面）。断言以模块安装清单为锚——root 上可能
    存在测试基础设施自有 StreamHandler，不能作为安装证据。"""
    from logging.handlers import RotatingFileHandler

    import app.logging_setup as logging_setup

    monkeypatch.delenv("NEWSWRIGHT_LOG_FILE", raising=False)
    monkeypatch.delenv("NEWSWRIGHT_LOG_CONSOLE", raising=False)
    logging_setup.setup_logging()
    try:
        console = [h for h in logging_setup._installed
                   if isinstance(h, logging.StreamHandler)
                   and not isinstance(h, RotatingFileHandler)]
        assert console
    finally:
        logging_setup.teardown_logging()


def test_console_line_is_json_with_context(monkeypatch):
    """console 行经统一 JSON formatter 输出且注入 contextvars 上下文
    （ADR-12① JSON 行 + ⑤ 上下文注入纪律对全部输出面生效）。"""
    from app.logging_setup import (
        reset_log_context,
        set_log_context,
        setup_logging,
        teardown_logging,
    )

    buf = io.StringIO()
    monkeypatch.setattr("sys.stderr", buf)
    setup_logging(force_console=True)
    token = set_log_context(call_point="ctx_probe", task_id=42)
    try:
        logging.getLogger("newswright.test.console").info("console 探针行")
    finally:
        reset_log_context(token)
        teardown_logging()
    line = buf.getvalue().strip().splitlines()[0]
    row = json.loads(line)  # console 行必须可解析为 JSON
    assert row["call_point"] == "ctx_probe"
    assert row["task_id"] == 42
    assert row["message"] == "console 探针行"
