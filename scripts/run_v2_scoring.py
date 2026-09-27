"""V2 验证：方向打分质量。

- 从 jev kit news-full.csv（1403 条真实语料）按长度/来源分层抽 50 条；
- 用 seed 的演示方向打分（独立临时 DB，不污染演示库）；
- 指标：解析成功率（status=OK 占比）、分数分布可分档性、理由可解释性（人工抽查 ≥10 条）；
- 与 kit 跑批已知失败模式对照（薄正文漏检：RSS 摘要级条目是否被判高分）。
- 产出：verify/V2_scoring_results.json
"""
from __future__ import annotations

import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

CSV_PATH = PROJECT_ROOT.parent / "doc" / "jev-scoring-kit-20260928" / "jev-scoring-kit" / "data" / "news-full.csv"
OUT_PATH = PROJECT_ROOT / "verify" / "V2_scoring_results.json"
SAMPLE_N = 50
V2_DB = "sqlite:///scratch_v2.db"


def sample_rows() -> list[dict]:
    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("title") or "").strip() and (r.get("clean_content") or "").strip()]
    def blen(r):
        return len(r.get("clean_content") or "")
    buckets = {"short": [], "mid": [], "long": []}
    for r in rows:
        n = blen(r)
        buckets["short" if n < 400 else "mid" if n < 1500 else "long"].append(r)
    rng = random.Random(20260928)
    picked = []
    quota = {"short": 15, "mid": 15, "long": 20}
    for key, k in quota.items():
        pool = buckets[key][:]
        rng.shuffle(pool)
        # 优先来源分散；不足配额时不再限来源
        first_pass, seen_src = [], set()
        for r in pool:
            src = r.get("source_name") or ""
            if src in seen_src:
                continue
            first_pass.append(r)
            seen_src.add(src)
        take = first_pass[:k]
        if len(take) < k:
            rest = [r for r in pool if r not in take]
            take = take + rest[: k - len(take)]
        picked.extend(take)
    # 配额不满（语料某长度桶不足）时从全量剩余中补足
    if len(picked) < SAMPLE_N:
        chosen = set(id(r) for r in picked)
        for r in rng.sample(rows, len(rows)):
            if id(r) not in chosen:
                picked.append(r)
                chosen.add(id(r))
            if len(picked) == SAMPLE_N:
                break
    return picked[:SAMPLE_N]


def main() -> int:
    import os
    os.environ["NEWSWRIGHT_DB"] = V2_DB
    # 强制重新加载 db/config（脚本独立进程，直接 import 即可）
    from app.db import SessionLocal, init_db
    from app.models import Direction, Item, ScoreResult, Source
    from app.scoring.service import score_item
    from scripts.seed import DEMO_DIRECTION_PROMPT

    for p in (PROJECT_ROOT / "scratch_v2.db",):
        p.unlink(missing_ok=True)

    init_db()
    rows = sample_rows()
    print(f"V2: 抽样 {len(rows)} 条")
    out_rows = []
    with SessionLocal() as db:
        d = Direction(name="AI 与软件工程", prompt=DEMO_DIRECTION_PROMPT, prompt_version="v1", threshold=60)
        db.add(d)
        src = Source(direction_id=1, url="https://v2.local/corpus", type="rss")
        db.add(src)
        db.commit()

        for i, r in enumerate(rows, 1):
            body = (r.get("clean_content") or "").strip()
            item = Item(
                source_id=src.id,
                guid=f"v2-{i}",
                url=(r.get("link") or ""),
                title=(r.get("title") or "").strip(),
                published_at=None,
                content_text=body,
            )
            db.add(item)
            db.commit()
            sr = score_item(db, item, d)
            out_rows.append({
                "idx": i,
                "title": (r.get("title") or "")[:80],
                "source": r.get("source_name"),
                "body_chars": len(body),
                "quality": sr.quality_score,
                "relevance": sr.relevance_score,
                "band": sr.band,
                "passed": sr.passed,
                "status": sr.status,
                "error": (sr.error or "")[:150] or None,
                "reason": sr.reason,
            })
            print(f"[{i}/{len(rows)}] {sr.status} rel={sr.relevance_score} q={sr.quality_score}")

    ok = [r for r in out_rows if r["status"] == "OK"]
    rels = sorted(r["relevance"] for r in ok)
    def bucket(chars):
        return "short" if chars < 400 else "mid" if chars < 1500 else "long"
    # 薄正文漏检检查：短正文条目被判 relevance≥70 的数量与明细
    thin_high = [r for r in ok if bucket(r["body_chars"]) == "short" and r["relevance"] >= 70]
    summary = {
        "total": len(out_rows),
        "parse_ok": len(ok),
        "parse_success_rate": round(len(ok) / len(out_rows), 3) if out_rows else None,
        "failed": len(out_rows) - len(ok),
        "relevance_min_median_max": [rels[0], rels[len(rels)//2], rels[-1]] if rels else None,
        "band_dist": dict(Counter(r["band"] for r in ok)),
        "passed_at_threshold_60": sum(1 for r in ok if r["passed"]),
        "relevance_bucket_means": {},
        "thin_body_high_relevance": {
            "count": len(thin_high),
            "titles": [t["title"][:60] for t in thin_high],
        },
        "model": "deepseek-chat (deepseek-flash)",
        "prompt_version": "v1",
    }
    for b in ("short", "mid", "long"):
        vals = [r["relevance"] for r in ok if bucket(r["body_chars"]) == b]
        summary["relevance_bucket_means"][b] = round(sum(vals) / len(vals), 1) if vals else None

    OUT_PATH.write_text(
        json.dumps({"summary": summary, "results": out_rows}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"结果已写入 {OUT_PATH}")
    from app.db import engine

    engine.dispose()  # Windows 下须先释放连接才能删库文件
    (PROJECT_ROOT / "scratch_v2.db").unlink(missing_ok=True)
    return 0 if summary["parse_success_rate"] and summary["parse_success_rate"] >= 0.95 else 1


if __name__ == "__main__":
    raise SystemExit(main())
