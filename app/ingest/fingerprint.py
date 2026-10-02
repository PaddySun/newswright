"""URL 指纹（G1/W4 P1-2，AC-05.2；D15 作用域=方向内）。

指纹 = sha256(归一化 URL)；归一化最小集：scheme/host 小写、去 fragment、
剔常见跟踪参数（复用 rss.normalize_url，路径大小写保留）。
边界：标题兜底指纹链（B4）与语义近重复（0.92）不在本里程碑（属 RSS 加固与
检索层后续批次）；web 监测单页版本条目不参与指纹链（同 URL 新版本=新条目，
设计书 B7 全量保存语义优先，见 db/web 与 G1 汇报偏离记录）。
"""
from __future__ import annotations

import hashlib
from urllib.parse import urlparse, urlunparse

from sqlalchemy.orm import Session

from ..models import Item, Source


def canonical_url(url: str) -> str:
    """归一化：scheme/host 小写 → 去 fragment/跟踪参数（normalize_url）。"""
    if not url:
        return url
    from .rss import normalize_url  # 局部导入防循环（rss 亦引用本模块）

    stripped = url.strip()
    p = urlparse(stripped)
    if not p.scheme:
        return normalize_url(stripped)
    return normalize_url(urlunparse((p.scheme.lower(), p.netloc.lower(), p.path,
                                     p.params, p.query, "")))


def url_fingerprint(url: str) -> str | None:
    """sha256 指纹；空 URL 返回 None（不参与去重）。"""
    if not url:
        return None
    return hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()


def find_fingerprint_origin(db: Session, direction_id: int, fingerprint: str) -> Item | None:
    """方向内指纹命中（D15：比对分母=方向内，跨方向同 URL 各自独立）。"""
    return (
        db.query(Item)
        .join(Source, Item.source_id == Source.id)
        .filter(Source.direction_id == direction_id, Item.fingerprint == fingerprint)
        .order_by(Item.id)
        .first()
    )
