"""moark（模力方舟）/v1/rerank 重排适配器（EV6 实测用，注册不接线）。

协议要点（项目文档（外层）API文档/模力-综合模型提供商/句子重排.txt + 2026-10-01 连通实测）：
- POST /v1/rerank {model, query, documents: string[], top_n}；
  **top_n 必须显式设为候选数**（官方默认 3，只回 top3）。
- 响应 results[] = {index, document{text}, relevance_score}（0-1，已按分数降序），
  usage 为 camelCase {promptTokens, totalTokens}。
- 归一化口径与 bocha_reranker 一致：relevance_score ×100；band ≥0.75 high / ≥0.20 mid / low。
- 8K 上下文（Qwen3-Reranker 系 / bge-reranker-v2-m3）——V11 发现的 bocha_reranker
  "短查询"问题能否被长查询直吃，是本适配器实测的核心问题（EV6）。
- 计量：非 LLM，落 rank_call_log + 额度闸（provider 名即额度键）；token 用量记入 raw。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .. import config
from .base import RankCandidate, RankError, RankProvider, RankedResult


class MoarkRerankerProvider(RankProvider):
    name = "moark_reranker"
    # 实测限制（2026-10-01）：documents 上限 25 条/请求（26 → 400 明示 '1' 到 '25'）
    max_documents_per_request = 25

    def __init__(
        self,
        db: Session,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
        query_max_chars: int | None = None,
    ) -> None:
        super().__init__(db)
        self._base_url = (base_url or config.MOARK_BASE_URL).rstrip("/")
        self._api_key = api_key or config.MOARK_API_KEY
        self._model = model or config.MOARK_RERANK_MODEL
        self._timeout = timeout
        # None=不截断（8K 上下文直吃长查询的原样口径）；整数=截到 N 字符（对照实验用）
        self._query_max_chars = query_max_chars

    def _rank(self, criteria: str, candidates: list[RankCandidate]) -> list[RankedResult]:
        out: list[RankedResult] = []
        for i in range(0, len(candidates), self.max_documents_per_request):
            out.extend(
                self._rank_chunk(criteria, candidates[i : i + self.max_documents_per_request])
            )
        return out

    def _rank_chunk(self, criteria: str, candidates: list[RankCandidate]) -> list[RankedResult]:
        import httpx

        from ..providers.base import RETRYABLE_STATUS, _scrub

        query = criteria if self._query_max_chars is None else criteria[: self._query_max_chars]
        payload = {
            "model": self._model,
            "query": query,
            "documents": [c.text for c in candidates],
            "top_n": len(candidates),
        }
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                f"{self._base_url}/v1/rerank",
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}",
                         "Content-Type": "application/json"},
            )
        if resp.status_code in RETRYABLE_STATUS:
            e = RankError(f"HTTP {resp.status_code}: {_scrub(resp.text[:300])}")
            e.retryable = True  # type: ignore[attr-defined]
            raise e
        if resp.status_code >= 400:
            raise RankError(f"HTTP {resp.status_code}: {_scrub(resp.text[:300])}")
        body = resp.json()
        usage = body.get("usage") or {}
        usage_flat = {
            "prompt_tokens": int(usage.get("promptTokens") or 0),
            "total_tokens": int(usage.get("totalTokens") or 0),
        }
        out: list[RankedResult] = []
        for r in body.get("results") or []:
            idx = r.get("index")
            if idx is None or idx >= len(candidates):
                continue
            raw_score = float(r.get("relevance_score") or 0)
            norm = raw_score * 100
            band = "high" if raw_score >= 0.75 else ("mid" if raw_score >= 0.20 else "low")
            out.append(
                RankedResult(
                    id=candidates[idx].id,
                    score=round(norm, 1),
                    band=band,
                    confidence=None,
                    provider=self.name,
                    raw={"relevance_score": raw_score, "model": body.get("model"), **usage_flat},
                )
            )
        return out
