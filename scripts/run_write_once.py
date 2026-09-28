"""单篇写作入口（冒烟与夜跑批跑共用）。

用法：
  python scripts/run_write_once.py --author 鲁迅
  python scripts/run_write_once.py --author 鲁迅 --batch-id ov_night --window 3,6 \
      --override '{"draft": {"mode": "single"}, "passes": []}'
幂等：--batch-id 时先查库，同 batch 同作者同 route 签名已成功过则跳过。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.authors.writer import run_write  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Article, Author, WriteRun  # noqa: E402


def route_signature(payload: dict) -> str:
    return json.dumps({
        "draft": (payload.get("route") or {}).get("draft"),
        "window": payload.get("reading_window"),
        "batch": payload.get("batch_id"),
    }, sort_keys=True, ensure_ascii=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--author", required=True, help="作者名或 id")
    ap.add_argument("--batch-id", default=None)
    ap.add_argument("--window", default=None, help="阅读集窗口 'offset,k'（批跑轮换用）")
    ap.add_argument("--override", default=None, help="route 覆盖 JSON（single 对照等）")
    ap.add_argument("--triggered-by", default="manual")
    ap.add_argument("--force", action="store_true", help="忽略幂等检查")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    try:
        author = (db.get(Author, int(args.author)) if args.author.isdigit()
                  else db.query(Author).filter_by(name=args.author).first())
        if author is None:
            print(f"[write] 作者不存在: {args.author}")
            return 2
        if not author.author_json:
            print(f"[write] 作者 {author.name} 无 author.json，走现行 single 路线")

        window = tuple(int(x) for x in args.window.split(",")) if args.window else None
        overrides = json.loads(args.override) if args.override else None

        # 幂等：同 batch + 同 route 签名 + 已 OK 的 write_run 不重复执行
        if args.batch_id and not args.force:
            for r in db.query(WriteRun).filter_by(author_id=author.id).all():
                p = r.payload or {}
                if p.get("batch_id") == args.batch_id and r.status == "OK" and \
                        route_signature(p) == route_signature({
                            "route": p.get("route"), "reading_window": window,
                            "batch_id": args.batch_id}):
                    print(json.dumps({"skipped": True, "write_run_id": r.id,
                                      "article_id": r.article_id}, ensure_ascii=False))
                    return 0

        run = run_write(db, author, triggered_by=args.triggered_by, batch_id=args.batch_id,
                        reading_window=window, route_overrides=overrides)
        # run_write 对 JSON 作者透传批跑参数
        article = db.get(Article, run.article_id) if run.article_id else None
        out = {
            "skipped": False,
            "write_run_id": run.id,
            "status": run.status,
            "decision": run.decision,
            "article_id": run.article_id,
            "title": article.title if article else None,
            "error": (run.error or "")[:300],
            "cost": (run.payload or {}).get("cost"),
            "gates": (run.payload or {}).get("gates_final"),
        }
        print(json.dumps(out, ensure_ascii=False, default=str))
        return 0 if run.status == "OK" else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
