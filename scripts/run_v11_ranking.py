"""V11：相关性排序底座验证脚本（能力⑤）。

①三实现真实连通（bocha_reranker / bocha_jev / moark_jev / llm）记录延迟与成本；
②同一批候选（≥20 条已打分 item）各 provider 排序 vs score_result.relevance：
  band 一致率（三档，按 60/30 分界归一化 relevance 口径）+ 秩序相关（Spearman ρ）；
③阅读集排除效果：rank_provider=none vs 各 provider 的 top-K 差异与被排除条目特征；
④成本：token/billing/免费期标注。
结果写 verify/V11_ranking_results.json。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

POOL = 30  # 已打分候选数（V11 要求 ≥20）


def band_of(relevance: int) -> str:
    return "high" if relevance >= 75 else ("mid" if relevance >= 25 else "low")


def spearman(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")

    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        for rank, idx in enumerate(order):
            r[idx] = rank + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else float("nan")


def main() -> int:
    from app.db import SessionLocal, init_db
    from app.models import Direction, Item, ScoreResult
    from app.rerank import registry as rank_registry
    from app.rerank.base import RankCandidate, RankError

    init_db()
    with SessionLocal() as db:
        d = db.query(Direction).filter_by(enabled=True).first()
        # 分层抽样：高/中/低分段都有，检验区分度（纯 top-30 会同质化全 high）
        base_q = (
            db.query(Item, ScoreResult)
            .join(ScoreResult, ScoreResult.item_id == Item.id)
            .filter(ScoreResult.status == "OK", ScoreResult.direction_id == d.id,
                    Item.fetch_status == "FETCHED", Item.sanitize_status == "PASSED")
            .order_by(ScoreResult.relevance_score.desc())
        )
        rows = base_q.all()
        hi = [r for r in rows if r[1].relevance_score >= 75][:15]
        mid = [r for r in rows if 40 <= r[1].relevance_score < 75][:10]
        lo = [r for r in rows if r[1].relevance_score < 40][-5:]
        items = list(dict.fromkeys(hi + mid + lo))[:POOL]
        print(f"候选 {len(items)} 条（分层：高{len(hi)}/中{len(mid)}/低{len(lo)}），方向：{d.name}")

        candidates = [RankCandidate(id=it.id, text=f"{it.title}\n{(it.content_text or '')[:400]}")
                      for it, _ in items]
        gold_relevance = [sr.relevance_score for _, sr in items]
        gold_band = [band_of(r) for r in gold_relevance]

        report = {
            "candidates": len(items),
            "direction": d.name,
            "gold_band_distribution": {b: gold_band.count(b) for b in ("high", "mid", "low")},
            "providers": {},
            "reading_set_diff": {},
        }

        for name in ("bocha_reranker", "bocha_jev", "moark_jev", "llm"):
            entry: dict = {"provider": name}
            try:
                import time

                provider = rank_registry.get_provider(name, db)
                t0 = time.monotonic()
                results = provider.rank(d.prompt, candidates, criteria_key=d.name)
                dt = int((time.monotonic() - t0) * 1000)
                entry["ok"] = True
                entry["latency_ms"] = dt
                entry["returned"] = len(results)
                if results:
                    score_by_id = {r.id: r for r in results}
                    pred_band, pred_scores, gold_aligned, matched = [], [], [], 0
                    for (it, sr), gb in zip(items, gold_band):
                        r = score_by_id.get(it.id)
                        if r is None:
                            continue
                        pred_band.append(r.band)
                        pred_scores.append(r.score)
                        gold_aligned.append(sr.relevance_score)
                        matched += int(r.band == gb)
                    n = len(pred_band)
                    entry["band_agreement"] = round(matched / n, 3) if n else None
                    entry["spearman_vs_relevance"] = round(
                        spearman(pred_scores, gold_aligned), 3) if n >= 3 else None
                    entry["score_distribution"] = {
                        "min": min(pred_scores), "max": max(pred_scores),
                        "band_dist": {b: pred_band.count(b) for b in ("high", "mid", "low")},
                    }
                    # 与既有打分的分歧形态：各 pred band 下的 relevance 均值
                    divergence = {}
                    for b in ("high", "mid", "low"):
                        rels = [g for g, pb in zip(gold_aligned, pred_band) if pb == b]
                        divergence[b] = round(sum(rels) / len(rels), 1) if rels else None
                    entry["relevance_mean_per_pred_band"] = divergence
            except RankError as e:
                entry["ok"] = False
                entry["error"] = str(e)[:300]
            report["providers"][name] = entry
            print(json.dumps({name: entry}, ensure_ascii=False)[:400])

        # ③阅读集排除效果：none vs 各 provider（构造 rank 开关下的 top-K 差异）
        from app.models import Author
        from app.authors.writer import assemble_reading_set, assemble_ranked_reading_set

        author = db.query(Author).filter_by(enabled=True).first()
        base_pairs = assemble_reading_set(db, author, k=10)
        base_ids = [it.id for it, _ in base_pairs]
        gold_map = {it.id: sr.relevance_score for it, sr in items}
        for name in ("bocha_reranker", "bocha_jev", "moark_jev", "llm"):
            author.rank_provider = name
            db.commit()
            try:
                pairs, meta = assemble_ranked_reading_set(db, author, k=10)
                ranked_ids = [it.id for it, _ in pairs]
                excluded = [i for i in base_ids if i not in ranked_ids]
                added = [i for i in ranked_ids if i not in base_ids]
                report["reading_set_diff"][name] = {
                    "topk": ranked_ids,
                    "excluded_from_base": excluded,
                    "added_vs_base": added,
                    "excluded_gold_relevance": [gold_map.get(i) for i in excluded],
                    "meta_kept": meta.get("kept"), "meta_excluded": meta.get("excluded"),
                    "fallback": meta.get("fallback"),
                }
            except Exception as e:  # noqa: BLE001
                report["reading_set_diff"][name] = {"error": str(e)[:200]}
        author.rank_provider = "none"
        db.commit()

    out = PROJECT_ROOT / "verify" / "V11_ranking_results.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n明细已写 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
