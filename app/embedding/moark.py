"""moark（模力方舟）/v1/embeddings 向量生成适配器。

协议要点（项目文档（外层）API文档/模力-综合模型提供商/向量生成.txt）：
- OpenAI 兼容：POST /v1/embeddings {model, input: string[], encoding_format="float", dimensions?}；
  dimensions 留空用模型默认值（Qwen3-Embedding 系支持 MRL 自定义维度；
  不支持的模型传 dimensions 的报错行为在 EV1 实测记录）。
- 模型名大小写不敏感、支持命名空间（bge-m3 = BAAI/bge-m3）。
- 响应 data[].embedding 按 index 排序还原输入顺序；usage.prompt_tokens 计量。
- 鉴权同其他 moark 端点：Bearer MOARK_API_KEY。

出网经传输脊 app/transport/（非 2xx 全入错、客户端池复用——此前自建
httpx.Client 与状态码判定的复制份已收敛）。设计依据见
docs/design-index.md「TR-1」「TR-2」。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .. import config
from ..transport.errors import ProviderError
from ..transport.http import post_json
from .base import EmbeddingError, EmbeddingProvider


class MoarkEmbeddingProvider(EmbeddingProvider):
    name = "moark_embed"

    def __init__(
        self,
        db: Session,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(db)
        self._base_url = (base_url or config.MOARK_BASE_URL).rstrip("/")
        self._api_key = api_key or config.MOARK_API_KEY
        self._model = model or config.MOARK_EMBED_MODEL
        self._timeout = timeout

    @property
    def model_name(self) -> str:
        return self._model

    def _embed_request(
        self, inputs: list[str], dimensions: int | None
    ) -> tuple[list[list[float]], dict[str, Any]]:
        payload: dict[str, Any] = {
            "model": self._model,
            "input": inputs,
            "encoding_format": "float",
        }
        if dimensions is not None:
            payload["dimensions"] = dimensions
        try:
            resp = post_json(
                f"{self._base_url}/v1/embeddings",
                payload,
                headers={"Authorization": f"Bearer {self._api_key}",
                         "Content-Type": "application/json"},
                timeout=self._timeout,
                db=self.db,
            )
        except ProviderError as e:
            ee = EmbeddingError(str(e))
            ee.retryable = getattr(e, "retryable", False)  # type: ignore[attr-defined]
            ra = getattr(e, "retry_after", None)
            if ra is not None:
                ee.retry_after = ra  # type: ignore[attr-defined]
            raise ee from e
        body = resp.json()
        data = body.get("data")
        if not isinstance(data, list) or not data:
            raise EmbeddingError(f"响应缺少 data 数组: {body!r:.200}")
        # 按 index 还原输入顺序（协议允许乱序返回）
        ordered = sorted(data, key=lambda d: d.get("index", 0))
        vectors = [d.get("embedding") for d in ordered]
        if any(not isinstance(v, list) or not v for v in vectors):
            raise EmbeddingError("响应存在空/非法 embedding 向量")
        usage = body.get("usage") or {}
        meter = {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "item_count": len(inputs),
        }
        return vectors, meter
