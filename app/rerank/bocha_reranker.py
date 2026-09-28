"""Bocha Semantic Reranker（api.bocha.cn/v1/rerank，非 LLM）。

口径声明：rerankScore 0-1 ×100 归一化；band 采用官方四段含义并成三档：
≥0.75 high（高度相关并完全回答）、≥0.20 mid（相关但缺细节/部分回答）、<0.20 low。
模型：gte-rerank（已开放）；bocha-semantic-reranker-cn/en 邀测中（记遗留）。

实测教训（V11）：reranker 的 query 语义是"短查询"——直接拿 500 字方向提示词当 query
会全档 low（语义不匹配，30 候选 max 0.149）。本实现取 criteria 前 100 字作 query
（探针验证区分度恢复：相关文档 0.17-0.31 vs 无关 0.006）。正式系统应为方向维护
专用短查询字段（记遗留）。
调用落 rank_call_log + 额度闸（provider 名 bocha_reranker）；不进 usage_log（非 LLM）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .. import config
from .base import HTTPRankProvider  # noqa: F401  保持模块结构一致
from .base import RankCandidate, RankError, RankProvider, RankedResult

ENDPOINT = "https://api.bocha.cn/v1/rerank"


class BochaRerankerProvider(RankProvider):
    name = "bocha_reranker"

    def __init__(self, db: Session, *, api_key: str | None = None,
                 model: str = "gte-rerank") -> None:
        super().__init__(db)
        self._api_key = api_key or config.BOCHA_API_KEY
        self._model = model
        if not self._api_key:
            raise RankError("bocha_reranker 缺少 API Key（.env bochaaiAPIKey）")

    def _rank(self, criteria: str, candidates: list[RankCandidate]) -> list[RankedResult]:
        import httpx

        from ..providers.base import RETRYABLE_STATUS, _scrub

        payload = {
            "model": self._model,
            "query": criteria[:100],  # reranker 需要"短查询"语义（见模块教训说明）
            "documents": [c.text for c in candidates],
            "return_documents": False,
        }
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(ENDPOINT, json=payload, headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            })
        if resp.status_code in RETRYABLE_STATUS:
            e = RankError(f"HTTP {resp.status_code}: {_scrub(resp.text[:300])}")
            e.retryable = True  # type: ignore[attr-defined]
            raise e
        if resp.status_code >= 400:
            raise RankError(f"HTTP {resp.status_code}: {_scrub(resp.text[:300])}")
        body = resp.json()
        data = body.get("data") or {}
        out: list[RankedResult] = []
        for r in data.get("results") or []:
            idx = r.get("index")
            if idx is None or idx >= len(candidates):
                continue
            raw_score = float(r.get("relevance_score") or 0)
            norm = raw_score * 100
            band = "high" if raw_score >= 0.75 else ("mid" if raw_score >= 0.20 else "low")
            out.append(RankedResult(id=candidates[idx].id, score=round(norm, 1), band=band,
                                    confidence=None, provider=self.name,
                                    raw={"relevance_score": raw_score, "model": data.get("model")}))
        return out
