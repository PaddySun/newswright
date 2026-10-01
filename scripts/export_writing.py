"""成稿与废稿导出（任务书硬要求：DB 可见 + md 导出）。

默认导出到仓库内 data/exports/writing/（本地过程产物，gitignored；
Demo 阶段曾导出到外层文档区，随 G0 自包含改造改为内聚）。

用法：
  python scripts/export_writing.py --run 15                # 单 run
  python scripts/export_writing.py --batch ovnight         # 整批
  python scripts/export_writing.py --author 鲁迅            # 某作者全部
废稿 = trace 中被门禁拒绝/重试弃用/空输出的中间稿 + FAILED run 的中间产物，
导出文件附门禁拒绝原因。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Article, Author, WriteRun  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = PROJECT_ROOT / "data" / "exports" / "writing"


def _safe(s: str) -> str:
    return "".join(c for c in s if c not in '\\/:*?"<>| ')[:40]


def export_run(db, run: WriteRun, out_dir: Path) -> list[Path]:
    author = db.get(Author, run.author_id)
    date = run.created_at.strftime("%Y%m%d") if run.created_at else datetime.now().strftime("%Y%m%d")
    base = f"{_safe(author.name)}_{date}_run{run.id}"
    paths: list[Path] = []
    payload = run.payload or {}

    if run.article_id:
        article = db.get(Article, run.article_id)
        gates = payload.get("gates_final") or {}
        head = (
            f"---\nauthor: {author.name}\nwrite_run: {run.id}\narticle: {article.id}\n"
            f"date: {date}\nmodel: {run.model}\nstatus: {run.status}\n"
            f"route: {json.dumps(payload.get('route', {}), ensure_ascii=False)}\n"
            f"gates: {json.dumps(gates.get('stats', {}), ensure_ascii=False)}\n"
            f"cost: {json.dumps(payload.get('cost', {}), ensure_ascii=False)}\n---\n\n"
        )
        p = out_dir / f"{base}_成稿.md"
        p.write_text(head + article.body + "\n", encoding="utf-8")
        paths.append(p)

    # 废稿：discarded 标记的 trace 条目 + FAILED run 的所有草稿类节点输出
    for i, t in enumerate(payload.get("trace") or []):
        discarded = t.get("discarded") or (run.status == "FAILED" and not run.article_id
                                           and t.get("node") in ("w_draft", "w_revise"))
        if not discarded:
            continue
        reason = t.get("note") or ""
        hist = (payload.get("gate_history") or [])
        if hist and i < len(hist) and not hist[i]["verdict"].get("passed"):
            reason = "；".join(hist[i]["verdict"]["issues"])
        head = (
            f"---\nauthor: {author.name}\nwrite_run: {run.id}\ndate: {date}\n"
            f"node: {t.get('node')}\nkind: 废稿\ndiscarded: {t.get('discarded')}\n"
            f"reject_reason: {reason}\nrun_status: {run.status}\nrun_error: {(run.error or '')[:300]}\n---\n\n"
        )
        p = out_dir / f"{base}_废稿{i:02d}_{t.get('node', 'node')}.md"
        p.write_text(head + (t.get("output") or "") + "\n", encoding="utf-8")
        paths.append(p)
    return paths


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=int, default=None)
    ap.add_argument("--batch", default=None)
    ap.add_argument("--author", default=None)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    try:
        q = db.query(WriteRun).order_by(WriteRun.id.desc())
        if args.run:
            q = q.filter(WriteRun.id == args.run)
        runs = q.all()
        if args.batch:
            runs = [r for r in runs if (r.payload or {}).get("batch_id") == args.batch]
        if args.author:
            a = db.query(Author).filter_by(name=args.author).first()
            runs = [r for r in runs if a and r.author_id == a.id]

        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        n = 0
        for run in runs:
            for p in export_run(db, run, out_dir):
                print(f"[export] {p.name}")
                n += 1
        print(f"[export] 共 {n} 个文件 -> {out_dir}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
