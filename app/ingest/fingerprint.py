"""URL 指纹（G1/W4 P1-2，AC-05.2；D15 作用域=方向内）。

指纹 = sha256(归一化 URL)；归一化最小集：scheme/host 小写、去 fragment、
剔常见跟踪参数（复用 rss.normalize_url，路径大小写保留）。
边界：语义近重复（0.92）属检索层后续批次；web 监测单页版本条目不参与指纹链
（同 URL 新版本=新条目，全量保存语义优先，见 db/web 与 G1 汇报偏离记录）。

指纹退化链（RSS 加固批）：feed 条目缺可用链接 URL 时按
「归一化 link → URL 型 guid → 归一化标题兜底」逐级退化取指纹；标题兜底指纹
以 ttl: 前缀留痕低置信（与 URL 指纹域隔离，避免同文本 URL 与标题互相碰撞）。
"""
from __future__ import annotations

import hashlib
import html
import unicodedata
from urllib.parse import urlparse, urlunparse

from sqlalchemy.orm import Session

from ..models import Item, Source

# 标题兜底指纹前缀：低置信留痕（前缀 + sha256 前 60 位 = 64 字符，贴合列宽）
_TITLE_FP_PREFIX = "ttl:"


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


def _normalize_title(title: str) -> str:
    """标题归一化：先解码 HTML 实体再做 NFKC + 空白折叠。

    实体必须先解码（&#8217; 类写法不解码则同一标题分裂为两条不同指纹），
    NFKC 收敛全角/半角等兼容写法。
    """
    text = html.unescape(title or "")
    text = unicodedata.normalize("NFKC", text)
    return " ".join(text.split()).strip()


def title_fingerprint(title: str) -> str | None:
    """标题兜底指纹（低置信，ttl: 前缀留痕）；空标题返回 None。"""
    normalized = _normalize_title(title)
    if not normalized:
        return None
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{_TITLE_FP_PREFIX}{digest[:len(digest) - len(_TITLE_FP_PREFIX)]}"


def is_url_like(value: str) -> bool:
    """URL 型判定（scheme 大小写不敏感）；tag:/urn: 等非 URL 形式返回 False。"""
    return bool(value) and value.lower().startswith(("http://", "https://"))


def entry_fingerprint(url: str, guid: str, title: str) -> tuple[str | None, bool]:
    """feed 条目指纹退化链：归一化 link → URL 型 guid → 归一化标题兜底。

    link 与 guid 都要求 URL 型（http/https）才取 URL 指纹——feedparser 会把
    非 isPermaLink 的 tag:/urn: 型 guid 复制进 link，伪链不得进 URL 指纹域。
    返回 (指纹, 是否低置信)。三级皆不可得时返回 (None, False)（不参与去重）。
    """
    fp = url_fingerprint(url) if is_url_like(url) else None
    if fp:
        return fp, False
    if is_url_like(guid):
        fp = url_fingerprint(guid)
        if fp:
            return fp, False
    fp = title_fingerprint(title)
    if fp:
        return fp, True
    return None, False


def find_fingerprint_origin(db: Session, direction_id: int, fingerprint: str) -> Item | None:
    """方向内指纹命中（D15：比对分母=方向内，跨方向同 URL 各自独立）。"""
    return (
        db.query(Item)
        .join(Source, Item.source_id == Source.id)
        .filter(Source.direction_id == direction_id, Item.fingerprint == fingerprint)
        .order_by(Item.id)
        .first()
    )
