"""向量落库与批量嵌入补齐：item_vec 行的写入端与嵌入调用编排。

纪律：
- 外部嵌入调用一律在 DB 事务之外；向量行按批短事务落库、每批一提交
  （SQLite 单写者约束下的调用约定）。
- 嵌入失败不向上抛入打分轮：本轮放弃补齐并记日志，无向量条目在路由时按
  未命中处理（慢速队列），下轮随新条目渐进补齐。
- 嵌入禁用（嵌入模型键置空/none）时整体跳过，路由侧自动走全量慢速路径。
设计依据见 docs/design-index.md「AC-08.1」「AC-08.5」。
"""
from __future__ import annotations

import logging

import numpy as np
from sqlalchemy.orm import Session

from .. import config
from ..embedding.base import EmbeddingError, EmbeddingProvider
from ..embedding import registry
from ..models import Item, ItemVec

log = logging.getLogger("newswright.retrieval")

# 嵌入模型键的禁用哨兵值（环境变量置空/none 时 config 归一为该值）
EMBED_DISABLED_SENTINEL = "none"


def embed_enabled() -> bool:
    """嵌入功能是否启用：模型键为空哨兵即禁用（整体回退全量慢速的回退件）。"""
    return bool(config.MOARK_EMBED_MODEL) and config.MOARK_EMBED_MODEL != EMBED_DISABLED_SENTINEL


def vec_to_blob(vec: list[float] | np.ndarray) -> bytes:
    """向量序列化：float32 小端字节串（存储口径固定，跨模型版本互不兼容由
    model_version 列隔离）。"""
    return np.asarray(vec, dtype="<f4").tobytes()


def blob_to_vec(blob: bytes) -> np.ndarray:
    """向量反序列化：小端 float32 一维数组。"""
    return np.frombuffer(blob, dtype="<f4")


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度（零向量按 0.0 处理——嵌入护栏保证非零，此处仅防御性兜底）。"""
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def embed_input_text(item: Item, *, truncate_chars: int | None = None) -> str:
    """嵌入输入文本：标题恒保留 + 正文截断（长文信息损失控制在实测可接受范围）。"""
    limit = truncate_chars if truncate_chars is not None else config.EMBED_TRUNCATE_CHARS
    title = (item.title or "").strip()
    body = (item.content_text or "")[:limit]
    return f"{title}\n{body}" if title else body


def default_provider(db: Session) -> EmbeddingProvider | None:
    """按配置解析嵌入 provider；禁用态返回 None（调用方按未嵌入处理）。"""
    if not embed_enabled():
        return None
    return registry.get_provider("moark", db)


def missing_vector_items(db: Session, items: list[Item], *,
                         model_version: str) -> list[Item]:
    """过滤出尚无「同 model_version」向量的条目：model_version 不匹配视同无向量。"""
    if not items:
        return []
    ids = [i.id for i in items]
    have = {
        row[0]
        for row in db.query(ItemVec.item_id).filter(
            ItemVec.item_id.in_(ids), ItemVec.model_version == model_version
        ).all()
    }
    return [i for i in items if i.id not in have]


def ensure_item_vectors(
    db: Session,
    items: list[Item],
    *,
    provider: EmbeddingProvider | None = None,
    batch_size: int | None = None,
    expected_dims: int | None = None,
    truncate_chars: int | None = None,
) -> dict:
    """为缺失向量的条目批量嵌入并落库（渐进补齐：历史存量不要求全量重嵌）。

    返回统计 {model_version, missing, embedded, failed}：
    - 逐批调用嵌入（外部调用在事务外），每批向量行短事务提交一次；
    - 任一批嵌入失败（含数量/维度校验错）即中止剩余批次并记 WARN，不抛异常；
    - 嵌入禁用或无缺失条目时直接返回，不产生任何调用。
    """
    bs = batch_size or config.EMBED_BATCH_SIZE
    dims = expected_dims if expected_dims is not None else config.EMBED_DIMENSIONS
    if not embed_enabled():
        return {"model_version": None, "missing": 0, "embedded": 0,
                "failed": 0, "disabled": True}
    if provider is None:
        provider = default_provider(db)
    if provider is None or not items:
        return {"model_version": None, "missing": 0, "embedded": 0,
                "failed": 0, "disabled": provider is None}
    model_version = provider.model_name
    missing = missing_vector_items(db, items, model_version=model_version)
    stats = {"model_version": model_version, "missing": len(missing),
             "embedded": 0, "failed": 0, "disabled": False}
    for start in range(0, len(missing), bs):
        batch = missing[start : start + bs]
        texts = [embed_input_text(i, truncate_chars=truncate_chars) for i in batch]
        try:
            vectors = provider.embed(
                texts, batch_size=bs, expected_dims=dims, call_point="embed",
            )
        except EmbeddingError as e:
            stats["failed"] = len(missing) - stats["embedded"]
            log.warning("嵌入补齐中止（本批失败，剩余条目下轮重试）: %s", e)
            return stats
        db.add_all(
            ItemVec(item_id=item.id, model_version=model_version, vec=vec_to_blob(vec))
            for item, vec in zip(batch, vectors)
        )
        db.commit()
        stats["embedded"] += len(batch)
    return stats
