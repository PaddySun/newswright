"""向量生成底座（能力⑥）：与 search/rerank/LLM provider 同构的"抽象 + 子类 + 注册"。

纪律（选型草稿 §3.2.8，EmbeddingProvider 为第三种 provider 类型，用户已拍板）：
- 所有 embedding 调用统一经此层：批量输入、dimensions 透传、重试（≤2 次指数退避）、
  计量落 usage_log（call_point=embed：模型名/token/条数 item_count/延迟/成败），免费也记账。
- 服务定位：注册不接线——本阶段不进抓取/打分/写作生产路径（接线属正式版决策）。
- 日志与报错绝不携带 Key。
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx
from sqlalchemy.orm import Session

from .. import config
from ..providers.base import ProviderError, record_usage

log = logging.getLogger("newswright.embedding")


class EmbeddingError(ProviderError):
    """向量生成调用失败（message 不得含 Key）。"""


class EmbeddingValidationError(EmbeddingError):
    """响应校验失败（向量数/维度与请求不符）——请求构造或服务端错配，不重试。"""


class EmbeddingProvider(ABC):
    """同步向量 provider。子类实现 _embed_request；基类负责分批/重试/计量。"""

    name: str = "base"

    def __init__(self, db: Session) -> None:
        self.db = db

    @abstractmethod
    def _embed_request(
        self, inputs: list[str], dimensions: int | None
    ) -> tuple[list[list[float]], dict[str, Any]]:
        """单批真实调用（输入条数已按 batch_size 切好）。返回 (向量列表[与 inputs 对齐],
        计量信息 prompt_tokens/item_count)。失败抛 EmbeddingError。"""

    def embed(
        self,
        texts: list[str],
        *,
        dimensions: int | None = None,
        call_point: str = "embed",
        batch_size: int | None = None,
        expected_dims: int | None = None,
        ref_type: str | None = None,
        ref_id: int | None = None,
        max_retries: int = 2,
    ) -> list[list[float]]:
        """批量向量化：切批 → 逐批重试调用 → usage_log 落账 → 返回与输入对齐的向量。

        expected_dims 传入时做返回维度校验（不一致抛 EmbeddingError——防下游静默错位）。
        """
        if not texts:
            return []
        bs = batch_size or config.EMBED_BATCH_SIZE
        out: list[list[float]] = []
        for i in range(0, len(texts), bs):
            out.extend(
                self._embed_batch(
                    texts[i : i + bs],
                    dimensions=dimensions,
                    call_point=call_point,
                    expected_dims=expected_dims,
                    ref_type=ref_type,
                    ref_id=ref_id,
                    max_retries=max_retries,
                )
            )
        return out

    def _embed_batch(
        self,
        inputs: list[str],
        *,
        dimensions: int | None,
        call_point: str,
        expected_dims: int | None,
        ref_type: str | None,
        ref_id: int | None,
        max_retries: int,
    ) -> list[list[float]]:
        attempt = 0
        last_err: Exception | None = None
        while attempt <= max_retries:
            t0 = time.monotonic()
            try:
                vectors, meter = self._embed_request(inputs, dimensions)
                latency_ms = int((time.monotonic() - t0) * 1000)
                if len(vectors) != len(inputs):
                    raise EmbeddingValidationError(
                        f"返回向量数 {len(vectors)} 与输入条数 {len(inputs)} 不一致"
                    )
                if expected_dims is not None:
                    bad = [i for i, v in enumerate(vectors) if len(v) != expected_dims]
                    if bad:
                        raise EmbeddingValidationError(
                            f"返回维度 {len(vectors[bad[0]])} 与期望 {expected_dims} 不一致"
                            f"（{len(bad)} 条错位）"
                        )
                record_usage(
                    self.db,
                    provider=self.name,
                    model=self.model_name,
                    call_point=call_point,
                    prompt_tokens=int(meter.get("prompt_tokens", 0)),
                    completion_tokens=0,
                    billing_units=int(meter.get("billing_units", 0)),
                    item_count=len(inputs),
                    latency_ms=latency_ms,
                    ok=True,
                    ref_type=ref_type,
                    ref_id=ref_id,
                )
                return vectors
            except EmbeddingValidationError:
                raise  # 维度/数量校验失败属请求构造或服务端错配，不重试
            except (httpx.HTTPError, ProviderError) as e:
                latency_ms = int((time.monotonic() - t0) * 1000)
                last_err = e
                retryable = isinstance(e, httpx.HTTPError) or getattr(e, "retryable", False)
                record_usage(
                    self.db,
                    provider=self.name,
                    model=self.model_name,
                    call_point=call_point,
                    item_count=len(inputs),
                    latency_ms=latency_ms,
                    ok=False,
                    error=f"{type(e).__name__}: {e}",
                    ref_type=ref_type,
                    ref_id=ref_id,
                )
                if not retryable or attempt == max_retries:
                    break
                delay = 2**attempt
                log.warning("embedding 调用失败（第 %d 次，%.1fs 后重试）: %s", attempt + 1, delay, e)
                time.sleep(delay)
                attempt += 1
        raise EmbeddingError(f"{self.name} embedding 失败（重试 {attempt} 次后放弃）: {last_err}")

    @property
    @abstractmethod
    def model_name(self) -> str:
        """当前模型名（计量落账用）。"""
