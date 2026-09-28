"""通用相关性排序底座（能力⑤）：抽象 + 三实现 + 注册，与 search/LLM provider 同纪律。

分工口径（与既有打分的关系，防重复烧钱）：
- 方向打分主链路（app/scoring）：LLM 一次调用带理由，是 5.7.5 可解释性的载体——保持不变；
- 本底座服务两类场景：
  1. 已打分候选的"注入模型上下文前"的预排序/排除（阅读集 top-K 前、热点风向候选筛选）；
  2. 尚无分数的候选（榜单条目、搜索结果）的轻量预筛。
- V11 只收集排序与打分的一致率数据，不做替换决策。

归一化口径（实现内换算并在此声明）：
- score：全部归一化到 0-100（Bocha reranker 0-1 ×100；Jev score 索引/满档 ×100；LLM 直接 0-100）；
- band：三档（high/mid/low）；各家分界在子类声明；
- confidence：可空（LLM 排序为 None）。
单次调用候选数上限与候选文本截断为配置项（config.RANK_MAX_CANDIDATES / RANK_TEXT_MAX_CHARS）。

计费归因：Jev/LLM 排序走 provider 层计量（call_point=rank_jev/rank_llm，usage_log 归因）；
Bocha reranker 非 LLM，调用落 rank_call_log（选独立表的理由见表注释）；全部受额度闸约束
（provider 名即额度键，SEARCH_QUOTA_<PROVIDER>_* 可配）。
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from .. import config
from ..models import RankCallLog

log = logging.getLogger("newswright.rerank")


@dataclass
class RankCandidate:
    id: Any
    text: str


@dataclass
class RankedResult:
    id: Any
    score: float  # 0-100
    band: str  # high / mid / low
    confidence: float | None
    provider: str
    raw: dict[str, Any] = field(default_factory=dict)


class RankError(Exception):
    """排序调用失败（message 不得含 Key）。"""


class RankProvider(ABC):
    """同步排序 provider。子类实现 _rank；基类负责截断/分批/计量落库/额度。"""

    name: str = "base"

    def __init__(self, db: Session) -> None:
        self.db = db

    @abstractmethod
    def _rank(self, criteria: str, candidates: list[RankCandidate]) -> list[RankedResult]:
        """单批真实调用（候选已截断）。失败抛 RankError。"""

    def rank(self, criteria: str, candidates: list[RankCandidate],
             *, criteria_key: str | None = None) -> list[RankedResult]:
        """额度闸 → 截断 → 分批调用 → rank_call_log 落库。"""
        from ..search.quota import check_and_count

        allowed, state = check_and_count(self.db, self.name)
        if not allowed:
            self._log(criteria_key, 0, 0, ok=False, status="blocked", error="SKIPPED_QUOTA")
            log.info("排序 %s 超出额度（SKIPPED_QUOTA）", self.name)
            return []
        if not candidates:
            return []

        capped = candidates[: config.RANK_MAX_CANDIDATES]
        truncated = [
            RankCandidate(id=c.id, text=(c.text or "").strip()[: config.RANK_TEXT_MAX_CHARS])
            for c in capped
        ]
        t0 = time.monotonic()
        try:
            results = self._rank(criteria, truncated)
        except RankError as e:
            latency = int((time.monotonic() - t0) * 1000)
            self._log(criteria_key, len(truncated), latency, ok=False, status="error", error=str(e)[:500])
            raise
        latency = int((time.monotonic() - t0) * 1000)
        self._log(criteria_key, len(truncated), latency, ok=True, status="ok")
        return results

    def _log(self, criteria_key: str | None, n: int, latency_ms: int, *, ok: bool,
             status: str, error: str | None = None) -> None:
        self.db.add(RankCallLog(provider=self.name, candidate_count=n,
                                criteria_key=(criteria_key or "")[:200] or None,
                                latency_ms=latency_ms, ok=ok, status=status, error=error))
        self.db.commit()


class HTTPRankProvider(RankProvider):
    """Jev 排序通用基类：systemone 协议（moark / bocha 两套配置复用同一代码路径）。

    分批：每请求问题数上限按服务端配置（moark 实测 16 问、bocha 32 问，超过 422），
    超限候选自动分批请求后合并。"""

    max_questions_per_request = 16

    def __init__(self, db: Session, *, base_url: str, api_key: str, model: str) -> None:
        super().__init__(db)
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    def _rank(self, criteria: str, candidates: list[RankCandidate]) -> list[RankedResult]:
        results: list[RankedResult] = []
        chunk = self.max_questions_per_request
        for i in range(0, len(candidates), chunk):
            results.extend(self._rank_chunk(criteria, candidates[i : i + chunk]))
        return results

    def _rank_chunk(self, criteria: str, candidates: list[RankCandidate]) -> list[RankedResult]:
        """Jev 批量排序：state=方向 criteria（共享上下文），每个候选一个 score 型问题。
        分数换算：索引 0-2 → 0-100；band：≥75 high / ≥25 mid / <25 low。"""
        import httpx

        from ..providers.base import RETRYABLE_STATUS, _scrub

        questions: dict[str, dict[str, Any]] = {}
        for i, c in enumerate(candidates):
            questions[f"c{i}"] = {
                "type": "score",
                "instructions": (
                    f"【候选内容】\n{c.text}\n\n该内容与方向的相关程度？（无关/间接相关/直接相关）"
                ),
                "criteria": ["无关", "间接相关", "直接相关"],
            }
        payload = {"model": self._model, "state": {"direction": criteria}, "questions": questions}
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{self._base_url}/v1/systemone",
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
        answers = body.get("answers") or {}
        usage = body.get("usage") or {}

        # Jev/LLM 排序走 provider 层计量纪律：usage_log 归因（call_point=rank_jev）
        from ..providers.base import record_usage

        record_usage(
            self.db, provider=self.name, model=body.get("model", self._model),
            call_point="rank_jev",
            prompt_tokens=int(usage.get("input_tokens") or 0),
            completion_tokens=int(usage.get("output_tokens") or 0),
            billing_units=int(usage.get("billing_units") or 0),
            latency_ms=0, ok=True,
        )

        out: list[RankedResult] = []
        for i, c in enumerate(candidates):
            a = answers.get(f"c{i}")
            if not a:
                continue
            score_idx = float(a.get("score") or 0)
            norm = score_idx / 2 * 100
            band = "high" if norm >= 75 else ("mid" if norm >= 25 else "low")
            out.append(RankedResult(id=c.id, score=round(norm, 1), band=band,
                                    confidence=a.get("confidence"),
                                    provider=self.name, raw=a))
        return out
