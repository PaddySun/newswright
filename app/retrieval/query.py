"""方向查询向量：从方向提示词提炼 rubric 摘要式检索查询并嵌入落库（版本缓存）。

要点：
- 查询形态为 rubric 摘要式而非主题式——实测教训：主题式查询与方向的接纳式
  标注（rubric）存在语义落差，摘要式把"什么内容该被接纳"编进查询文本。
- 生成提示词为版本化常量：改提示词必须升 QUERY_GEN_PROMPT_VERSION。
- 缓存键 = (direction_id, prompt_version)：方向提示词升版即失效重生成；
  失败（LLM 或嵌入）不缓存，该方向本轮全部按未命中处理，下轮重试。
- 外部调用（LLM + 嵌入）一律在 DB 事务之外，仅最终落列走一次短事务。
设计依据见 docs/design-index.md「AC-08.2」；查询形态依据见检索层选型实测
（EV2 教训：主题式查询与 rubric 接纳式标注的语义落差）。
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .. import config
from ..embedding.base import EmbeddingError
from ..models import Direction
from ..providers.base import ProviderError
from ..providers.deepseek import DeepSeekProvider
from .embedder import blob_to_vec, default_provider, embed_enabled, vec_to_blob

log = logging.getLogger("newswright.retrieval")

QUERY_GEN_PROMPT_VERSION = 1

QUERY_GEN_PROMPT = """你将为一条内容评审方向构造检索查询。下面是方向的评分提示词，
它以接纳式标准（rubric）描述了什么样的内容应当被纳入。请把它提炼成一段
200 字以内的"检索查询"文本：描述该方向想接纳的内容主题、题材与质量特征，
使一段正文与这段查询在语义向量空间中的相似度能反映"该内容符合方向评分标准"。
只输出查询文本本身，不要任何解释、引号或前缀。

【方向评分提示词】
{direction_prompt}"""


def ensure_direction_query_vec(
    db: Session,
    direction: Direction,
    *,
    llm: DeepSeekProvider | None = None,
    embed_provider=None,
    expected_dims: int | None = None,
) -> bool:
    """方向查询向量就绪检查与生成（缓存命中返回 True；失败返回 False 不抛出）。

    就绪判定：query_vec 已落列且 query_vec_version == 当前 prompt_version。
    版本不一致即失效重生成；生成或嵌入任一步失败按未就绪处理（调用方全量慢速）。
    """
    if not embed_enabled():
        return False
    if direction.query_vec is not None and int(direction.query_vec_version or 0) == int(
        direction.prompt_version
    ):
        return True
    try:
        llm = llm or DeepSeekProvider(db)
        text, _model = llm.chat(
            [
                {"role": "system", "content": "你是检索查询构造器。"},
                {"role": "user", "content": QUERY_GEN_PROMPT.format(
                    direction_prompt=direction.prompt)},
            ],
            call_point="query_gen",
            ref_type="direction",
            ref_id=direction.id,
            max_tokens=500,
        )
        query_text = text.strip()
        if not query_text:
            raise ProviderError("查询生成返回空文本")
        embed_provider = embed_provider or default_provider(db)
        if embed_provider is None:
            return False
        dims = expected_dims if expected_dims is not None else config.EMBED_DIMENSIONS
        vec = embed_provider.embed(
            [query_text], expected_dims=dims, call_point="embed_query",
        )[0]
    except (ProviderError, EmbeddingError, IndexError) as e:
        log.warning("方向 %s 查询向量生成失败（本轮按未命中处理，下轮重试）: %s",
                    direction.id, e)
        return False
    direction.query_vec = vec_to_blob(vec)
    direction.query_vec_version = int(direction.prompt_version)
    db.commit()
    return True


def direction_query_vector(direction: Direction) -> "object | None":
    """读取方向已缓存的查询向量（未就绪返回 None）。"""
    if direction.query_vec is None:
        return None
    return blob_to_vec(direction.query_vec)
