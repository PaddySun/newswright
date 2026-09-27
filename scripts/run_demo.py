"""一键全链路演示：seed（幂等）→ 抓取 → 打分 → 写作 → 用量汇总。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from app.db import SessionLocal, init_db
    from app.models import Article, Author, ScoreResult
    from app.pipeline.runner import fetch_round, score_round, write_task

    print("== newswright 全链路演示 ==")
    import scripts.seed as seed  # noqa: F401  幂等灌入
    from scripts.seed import main as seed_main

    seed_main()
    init_db()
    with SessionLocal() as db:
        print("\n[1/3] 抓取 + 初筛 ...")
        fetch = fetch_round(db, triggered_by="run_demo")
        for s in fetch["sources"]:
            print(f"  src{s['source_id']} {s['url'].split('/')[2]:22} {s['status']:6} "
                  f"feed={s.get('feed_entries', 0)} 入库={s.get('inserted', 0)} "
                  f"去重拦截={s.get('dup_blocked', 0)} 规则拒={s.get('rule_rejected', 0)} 失败={s.get('failed', 0)}"
                  + (f" err={s['error'][:60]}" if s.get("error") else ""))

        print("\n[2/3] 方向打分 ...")
        score = score_round(db, triggered_by="run_demo")
        for d in score["directions"]:
            print(f"  方向[{d['name']}] {d['status']} 候选={d.get('candidates', 0)} "
                  f"打分={d.get('scored', 0)} 过阈值={d.get('passed', 0)} 失败={d.get('call_failed', 0)}"
                  + (f" err={d['error']}" if d.get("error") else ""))

        print("\n[3/3] 作者写作 ...")
        authors = db.query(Author).filter_by(enabled=True).all()
        for a in authors:
            r = write_task(db, a.id, triggered_by="run_demo")
            print(f"  作者[{a.name}] task={r['task_id']} {r['status']} decision={r['payload'].get('decision')} "
                  + (f"err={r['last_error']}" if r.get("last_error") else ""))

        articles = db.query(Article).order_by(Article.id.desc()).limit(5).all()
        print("\n最近文章：")
        for a in articles:
            print(f"  #{a.id} 《{a.title[:40]}》 引用{len(a.citations)}条")
        total_scores = db.query(ScoreResult).count()
        print(f"\n累计打分 {total_scores} 条；GET /usage/summary 查看成本归因")
    print("\n启动 API：.venv/Scripts/python -m uvicorn app.main:app --port 8300")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
