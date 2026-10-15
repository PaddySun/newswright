"""搜索额度闸——实现已上提至 app/transport/quota.py（传输脊中立化批）。

本模块保留薄 re-export 层：既有 import 面（pipeline/registry/测试，含
config 归因与内部判定函数的观测面）零改动；新增代码请直接
`from ..transport.quota import ...`（额度闸语义与归属见
docs/design-index.md「TR-1」）。
"""
from __future__ import annotations

from datetime import datetime  # noqa: F401  既有消费者的窗口翻页观测面

from .. import config  # noqa: F401  既有消费者的 config 归因/打桩面
from ..transport.quota import (
    _count,
    _provider_limits,
    check_and_count,
    quota_state,
)

__all__ = ["check_and_count", "quota_state"]
