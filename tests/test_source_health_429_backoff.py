"""源健康 429 退避边界测试：限流轮不参与退避计数（不清零不递增）。

覆盖口径（D13 动态降频 + 技术书 §4.2 退避纪律，设计依据见
docs/design-index.md「D13」）：
- 已有连续失败计数的源遇到 429 轮：计数保持原值（限流信号「不计成功也不计
  失败退避」——清零=误判恢复、递增=误判恶化，双向都破坏退避节奏）。
"""
from types import SimpleNamespace

from app.models import Direction, Source
from app.pipeline.runner import _update_source_health


def _seed_source(db):
    d = Direction(name="限流边界方向", prompt="p", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, type="rss", url="https://example.com/rss")
    db.add(src)
    db.commit()
    return src


def _rate_limited_stats(**kw):
    base = dict(error=None, feed_entries=0, inserted=0, not_modified=False,
                rate_limited=True, retry_after="60", extra={})
    base.update(kw)
    return SimpleNamespace(**base)


def test_429_round_preserves_backoff_failures(db_session):
    """退避计数 1 的源过一轮 429：计数仍为 1（既不清零也不递增）。"""
    src = _seed_source(db_session)
    src.backoff_failures = 1  # 此前一轮网络失败
    db_session.commit()
    _update_source_health(db_session, src, _rate_limited_stats())
    db_session.refresh(src)
    assert src.backoff_failures == 1
    assert src.rate_level == 1  # 限流档位照常 +1（D13 档位域不受影响）
