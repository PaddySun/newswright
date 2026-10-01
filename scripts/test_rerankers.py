"""reranker 四配置实测（EV6）：moark /v1/rerank vs 既有打分底座，协议同 V11。

用法：.venv/Scripts/python scripts/test_rerankers.py <cmd>
  build-pool   构造 30 候选分层池（G1 金标：自身 brief 标签 15高/10中/5低）
  run          四配置 × {长查询=briefing 原文, 短查询=LLM 生成} 全量实测
  report       汇总 verify/EV6_*.json → 总表（含换血率）

重点回答（任务书）：8K 上下文能否直吃长方向提示词——V11 发现的 bocha_reranker
"短查询"问题是否被结构性解决；rerank 后 top-K 与纯向量检索 top-K 的换血率。
协议（V11）：band 一致率 / Spearman ρ vs 金标分（此处金标 = G1 自评分，非
news_items.score——morningdeck 原生分仅 19 条，见搭建记录偏离说明）。
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# 评测需要连发：额度闸按 provider 名放开（免费档实测限流单独做，见 EV8）。
# 四个 _fixed 子类继承 name="moark_reranker"，额度键同名——放开该键即可。
os.environ.setdefault("SEARCH_QUOTA_MOARK_RERANKER_MINUTE", "1000")
os.environ.setdefault("SEARCH_QUOTA_MOARK_RERANKER_DAY", "100000")

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import RankCallLog  # noqa: E402
from app.rerank import registry as rank_registry  # noqa: E402
from app.rerank.base import RankCandidate  # noqa: E402

from build_vector_gold import load_corpus  # noqa: E402

GOLD_DIR = PROJECT_ROOT / "verify/gold"
VERIFY = PROJECT_ROOT / "verify"
POOL_PATH = VERIFY / "gold/EV6_pool.json"

CONFIGS = ["moark_reranker_qwen3_06b", "moark_reranker_qwen3_4b",
           "moark_reranker_qwen3_8b", "moark_reranker_bge_v2_m3"]

# 候选文本口径：标题 + 正文 500 字符（与 RANK_TEXT_MAX_CHARS 一致）
TEXT_MAX = 500


def spearman(a: list[float], b: list[float]) -> float:
    def ranks(x):
        order = np.argsort(np.asarray(x))
        r = np.empty(len(x))
        r[order] = np.arange(1, len(x) + 1)
        return r
    ra, rb = ranks(a), ranks(b)
    if len(a) < 2:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def build_pool() -> None:
    """V11 协议池：每个 brief 内部 30 候选分层（15高/10中/5低，按自身 brief 自评分；
    某层不足则全量取——News 正例仅 7，如实记录池大小）。"""
    corpus = load_corpus()
    by_id = {c["id"]: c for c in corpus}
    gold = json.loads((GOLD_DIR / "G1_routing.json").read_text(encoding="utf-8"))
    rng = np.random.default_rng(20261005)
    pool = []
    for bid in sorted({it["brief_owner"] for it in gold["items"]}):
        buckets = {"high": [], "mid": [], "low": []}
        for it in gold["items"]:
            if it["brief_owner"] != bid:
                continue
            s = it["scores"].get(bid)
            if s is None:
                continue
            b = "high" if s >= 60 else ("mid" if s >= 31 else "low")
            buckets[b].append(it["item_id"])
        for b, want in [("high", 15), ("mid", 10), ("low", 5)]:
            ids = list(buckets[b])
            rng.shuffle(ids)
            for iid in ids[:want]:
                c = by_id[iid]
                pool.append({
                    "item_id": iid, "brief_owner": bid,
                    "gold_score": it_score(gold, iid, bid),
                    "text": f"{c['title']}\n{c['text'][len(c['title']):].strip()[:TEXT_MAX]}",
                    "title": c["title"][:80],
                })
    POOL_PATH.parent.mkdir(parents=True, exist_ok=True)
    POOL_PATH.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter

    cnt = Counter()
    for p in pool:
        s = p["gold_score"]
        cnt[(p["brief_owner"][:8], "high" if s >= 60 else ("mid" if s >= 31 else "low"))] += 1
    print("pool per brief:", dict(cnt), "total:", len(pool))


def it_score(gold: dict, iid: str, bid: str) -> int:
    for it in gold["items"]:
        if it["item_id"] == iid:
            return it["scores"].get(bid) or 0
    return 0


def gold_score(gold: dict, iid: str) -> int:
    for it in gold["items"]:
        if it["item_id"] == iid:
            return it["scores"].get(it["brief_owner"]) or 0
    return 0


def it_brief(gold: dict, iid: str) -> str:
    for it in gold["items"]:
        if it["item_id"] == iid:
            return it["brief_owner"]
    return ""


def run() -> None:
    init_db()
    pool = json.loads(POOL_PATH.read_text(encoding="utf-8"))
    gold = json.loads((GOLD_DIR / "G1_routing.json").read_text(encoding="utf-8"))
    briefings = {b["brief_id"]: b["briefing"] for b in gold["briefs"]}
    queries = json.loads((GOLD_DIR / "G1_queries.json").read_text(encoding="utf-8"))
    # 每个候选以其"自身 brief"为方向：criteria 用该 brief 的 briefing（长）
    # 与其第一条 en 短查询（短）。池中混合三 brief 候选——逐候选用各自 brief 的查询
    # 会让每次调用只有一个候选项的"正确方向"。协议改为：按 brief 分组分别 rank。
    results = []
    brief_ids = sorted({p["brief_owner"] for p in pool})
    for cfg in CONFIGS:
        for bid in brief_ids:
            cands = [p for p in pool if p["brief_owner"] == bid]
            if not cands:
                continue
            short_q = next(q["query"] for q in queries if q["brief_id"] == bid)
            long_q = briefings[bid]
            for mode, criteria in [("long_briefing", long_q), ("short_query", short_q)]:
                s = SessionLocal()
                try:
                    prov = rank_registry.get_provider(cfg, s)
                    ranked = prov.rank(
                        criteria,
                        [RankCandidate(id=p["item_id"], text=p["text"]) for p in cands],
                        criteria_key=f"{cfg}:{mode}:{bid[:8]}",
                    )
                finally:
                    s.close()
                if not ranked:
                    results.append({"config": cfg, "brief": bid, "mode": mode, "error": "no results"})
                    continue
                score_by_id = {r.id: r.score for r in ranked}
                band_by_id = {r.id: r.band for r in ranked}
                golds = [p["gold_score"] for p in cands if p["item_id"] in score_by_id]
                preds = [score_by_id[p["item_id"]] for p in cands if p["item_id"] in score_by_id]
                gold_band = ["high" if g >= 60 else ("mid" if g >= 25 else "low") for g in golds]
                agree = statistics.mean([1 if gb == band_by_id[p["item_id"]] else 0
                                         for gb, p in zip(gold_band, cands)
                                         if p["item_id"] in band_by_id])
                rho = spearman(golds, preds)
                # rank_call_log 聚合延迟（四配置类名同为 moark_reranker，按 criteria_key 区分）
                s = SessionLocal()
                rows = (s.query(RankCallLog)
                        .filter_by(criteria_key=f"{cfg}:{mode}:{bid[:8]}", ok=True).all())
                lat = [r.latency_ms for r in rows] or [0]
                s.close()
                usage_prompt = sum(
                    (r.raw or {}).get("prompt_tokens", 0) for r in ranked
                )
                results.append({
                    "config": cfg, "brief": bid, "mode": mode,
                    "n_cands": len(cands),
                    "band_agree": round(agree, 3),
                    "spearman": round(rho, 3),
                    "latency_ms_median": int(statistics.median(lat)),
                    "prompt_tokens_sum": usage_prompt,
                    "provider_scores": score_by_id,
                })
                print(f"{cfg} {mode} {bid[:8]}: agree={agree:.3f} rho={rho:.3f} "
                      f"lat={int(statistics.median(lat))}ms")
    (VERIFY / "EV6_rerank_detail.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def report() -> None:
    detail = json.loads((VERIFY / "EV6_rerank_detail.json").read_text(encoding="utf-8"))
    rows = {}
    for r in detail:
        if r.get("error"):
            continue
        key = (r["config"], r["mode"])
        rows.setdefault(key, []).append(r)
    table = []
    for (cfg, mode), rs in sorted(rows.items()):
        table.append({
            "config": cfg, "mode": mode,
            "band_agree": round(statistics.mean([r["band_agree"] for r in rs]), 3),
            "spearman": round(statistics.mean([r["spearman"] for r in rs]), 3),
            "spearman_per_brief": {r["brief"][:8]: r["spearman"] for r in rs},
            "latency_ms_median": int(statistics.median([r["latency_ms_median"] for r in rs])),
            "prompt_tokens_per_call": round(statistics.mean([r.get("prompt_tokens_sum", 0) for r in rs])),
        })
    (VERIFY / "EV6_rerank_summary.json").write_text(
        json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(table, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "build-pool":
        build_pool()
    elif cmd == "run":
        run()
    elif cmd == "report":
        report()
    else:
        print(__doc__)
