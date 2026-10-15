"""计量落账（usage_log 写入）——自 providers/base.py 平移（签名零变）。

外部调用计量是跨域横切面（LLM/向量化/重排序共用），归宿传输层；各域计量
语义差异（call_point 口径、meter 字段组装）保留在域内。
设计依据见 docs/design-index.md「TR-1」「ADR-8」。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import UsageLog
from .http import _scrub


def record_usage(
    db: Session,
    *,
    provider: str,
    model: str,
    call_point: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    billing_units: int = 0,
    cache_hit_tokens: int = 0,
    reasoning_tokens: int = 0,
    finish_reason: str | None = None,
    item_count: int | None = None,
    latency_ms: int = 0,
    ok: bool = True,
    error: str | None = None,
    ref_type: str | None = None,
    ref_id: int | None = None,
) -> None:
    """落一条 usage_log（error 字段脱敏；未计量列缺省 0——账本不得虚增）。"""
    db.add(
        UsageLog(
            provider=provider,
            model=model,
            call_point=call_point,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            billing_units=billing_units,
            cache_hit_tokens=cache_hit_tokens,
            reasoning_tokens=reasoning_tokens,
            finish_reason=finish_reason,
            item_count=item_count,
            latency_ms=latency_ms,
            ok=ok,
            error=_scrub(error)[:2000] if error else None,
            ref_type=ref_type,
            ref_id=ref_id,
        )
    )
    db.commit()
