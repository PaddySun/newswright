"""结构化系统日志：单文件 JSON 行 + contextvars 上下文注入 + 大小轮转。

纪律：
- 全部日志经统一 JSON formatter 输出，必含字段 ts/level/call_point/task_id/
  site/route/actor；ERROR 行必含 error_code/error_msg/stack_id。
- 上下文（task_id/call_point 由任务认领点写入；route/actor 由请求中间件写入）
  经 contextvars + logging.Filter 注入——业务代码禁止手工拼日志字段，现有
  log 调用保持 message 原样。
- stack_id = 错误详情落库后的引用 id（大文本引 ref 规则）：日志行只带 id 不带
  堆栈，错误方通过 extra={"stack_id": <落库行 id>} 关联。
- 轮转按大小（10MB×5）；日志文件路径经 NEWSWRIGHT_LOG_FILE 启用与配置（部署
  环境显式开启），未设置时仅 console 输出；NEWSWRIGHT_LOG_CONSOLE=0 关闭 console。
设计依据见 docs/design-index.md「ADR-12」。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

SITE_NAME = os.environ.get("NEWSWRIGHT_SITE") or "newswright"
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

REQUIRED_FIELDS = ("ts", "level", "call_point", "task_id", "site", "route", "actor")

_ctx: ContextVar[dict | None] = ContextVar("newswright_log_context", default=None)

_installed: list[logging.Handler] = []


def set_log_context(**fields) -> object:
    """合并写入日志上下文（返回 token 供精确还原）。"""
    merged = {**(_ctx.get() or {}), **fields}
    return _ctx.set(merged)


def reset_log_context(token) -> None:
    _ctx.reset(token)


def current_log_context() -> dict:
    return dict(_ctx.get() or {})


class ContextFilter(logging.Filter):
    """把 contextvars 中的上下文字段注入每条记录（缺失字段置 None，保证行形一致）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _ctx.get() or {}
        for name in ("call_point", "task_id", "site", "route", "actor"):
            setattr(record, name, ctx.get(name))
        record.stack_id = getattr(record, "stack_id", None)
        record.error_code = getattr(record, "error_code", None)
        return True


class JsonLineFormatter(logging.Formatter):
    """JSON 行 formatter：错误行（ERROR+）补 error_code/error_msg/stack_id。"""

    def format(self, record: logging.LogRecord) -> str:
        line = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "call_point": getattr(record, "call_point", None),
            "task_id": getattr(record, "task_id", None),
            "site": getattr(record, "site", None) or SITE_NAME,
            "route": getattr(record, "route", None),
            "actor": getattr(record, "actor", None),
        }
        if record.levelno >= logging.ERROR:
            line["error_code"] = getattr(record, "error_code", None)
            line["error_msg"] = record.getMessage()
            line["stack_id"] = getattr(record, "stack_id", None)
        if record.exc_info:
            line["error_msg"] = f"{line.get('error_msg') or ''} {record.exc_text or ''}".strip()
        return json.dumps(line, ensure_ascii=False, default=str)


def setup_logging(*, force_console: bool | None = None) -> None:
    """安装 JSON 行 handler（幂等：重复调用先卸载旧 handler）。

    文件 handler：NEWSWRIGHT_LOG_FILE 指向日志文件（部署显式开启，RotatingFile
    10MB×5）；console handler：默认开启，NEWSWRIGHT_LOG_CONSOLE=0/off 关闭。
    """
    teardown_logging()
    root = logging.getLogger()
    filt = ContextFilter()
    fmt = JsonLineFormatter()
    console = force_console if force_console is not None else not (
        os.environ.get("NEWSWRIGHT_LOG_CONSOLE", "1").strip().lower()
        in ("0", "false", "off"))
    if console:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(fmt)
        handler.addFilter(filt)
        root.addHandler(handler)
        _installed.append(handler)
    log_file = os.environ.get("NEWSWRIGHT_LOG_FILE")
    if log_file:
        path = _ensure_parent(log_file)
        fh = RotatingFileHandler(path, maxBytes=LOG_MAX_BYTES,
                                 backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
        fh.setFormatter(fmt)
        fh.addFilter(filt)
        root.addHandler(fh)
        _installed.append(fh)
    root.setLevel(logging.INFO)


def teardown_logging() -> None:
    for h in _installed:
        logging.getLogger().removeHandler(h)
        h.close()
    _installed.clear()


def _ensure_parent(path: str) -> str:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path
