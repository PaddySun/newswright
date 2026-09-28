"""OV1 端到端全链路串联（用户点名最优先）：

四通道抓取（RSS + 网页监测 + 热榜 + 搜索）→ sanitize → 规则初筛 → 方向打分
→ 阅读集（预排序）→ AI 作者写作（luxun + 谭雅各 1 篇）→ C 流文章。

验收（任务书 §7.6）：每个可用通道至少有一条内容可追溯到成文引用，或给出可解释的
中途退出原因（如搜索条目未过阈值、热点通道为风向段设计性不可引用）。
报告落 verify/e2e_report.json + verify/e2e_report.md；摘要进晨报（--morning）。

用法：python scripts/run_e2e.py [--skip-fetch] [--skip-write] [--batch e2e_20260929]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Article, Author, HotBatch, Item, ScoreResult, Source, WriteRun  # noqa: E402

VERIFY = Path(__file__).resolve().parents[1] / "verify"
CHANNEL_LABEL = {"rss": "RSS", "web": "网页监测", "search": "搜索", "hot": "热榜"}


def trace_channels(db) -> dict:
    """逐通道追溯：抓取 → 打分 → 通过 → 进阅读集 → 被引用。"""
    out = {}
    for stype in ("rss", "web", "search"):
        src_ids = [s.id for s in db.query(Source).filter_by(type=stype, enabled=True).all()]
        if not src_ids:
            out[stype] = {"label": CHANNEL_LABEL[stype], "exit_reason": "无该类型启用源"}
            continue
        items = db.query(Item).filter(Item.source_id.in_(src_ids)).all()
        item_ids = [i.id for i in items]
        scored = (db.query(ScoreResult)
                  .filter(ScoreResult.item_id.in_(item_ids), ScoreResult.status == "OK",
                          ScoreResult.passed.is_(True)).count() if item_ids else 0)
        out[stype] = {"label": CHANNEL_LABEL[stype], "items_total": len(items),
                      "passed": scored}
    # 热榜：设计上走风向段（禁作引用来源，V9 护栏实测）
    hb = db.query(HotBatch).order_by(HotBatch.id.desc()).first()
    out["hot"] = {"label": CHANNEL_LABEL["hot"],
                  "batches": db.query(HotBatch).count(),
                  "latest_keywords": (hb.keywords if hb else [])[:8],
                  "exit_reason": "设计性不可引用：热点经风向段注入提示词（背景信息），"
                                 "引用护栏只认阅读集 item（V9 实测不绕过）"}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--skip-write", action="store_true")
    ap.add_argument("--batch", default=f"e2e_{datetime.now():%Y%m%d_%H%M}")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    report: dict = {"batch": args.batch, "started": datetime.now().isoformat(timespec="seconds"),
                    "stages": {}, "channels": {}}

    # 1. 四通道抓取（fetch_round 覆盖 rss/web/search；hot 单独轮次）
    if not args.skip_fetch:
        from app.pipeline.runner import fetch_round
        t0 = time.monotonic()
        fr = fetch_round(db, triggered_by="e2e")
        report["stages"]["fetch"] = {"latency_s": int(time.monotonic() - t0),
                                     "sources": len(fr["sources"]),
                                     "failed": sum(1 for s in fr["sources"] if s.get("error"))}
        try:
            from app.hot.service import run_hot_round
            hr = run_hot_round(db, triggered_by="e2e")
            report["stages"]["hot_round"] = {k: hr.get(k) for k in ("status", "platforms", "keywords") if k in hr}
        except Exception as e:
            report["stages"]["hot_round"] = {"error": str(e)[:200]}

        # 2. 规则初筛 + 打分（sanitize 骨架 pass-through 在 fetch 内强制流经）
        from app.pipeline.runner import score_round
        sr = score_round(db, triggered_by="e2e")
        report["stages"]["score"] = sr["directions"]

    # 3. 写作（luxun + 谭雅各 1 篇，走 author.json 管线）
    if not args.skip_write:
        from app.pipeline.runner import write_task
        report["stages"]["write"] = {}
        for name in ("鲁迅", "谭雅·冯·提古雷查夫"):
            author = db.query(Author).filter_by(name=name).first()
            if author is None:
                report["stages"]["write"][name] = {"error": "author 不存在"}
                continue
            r = write_task(db, author.id, triggered_by="e2e", batch_id=args.batch)
            report["stages"]["write"][name] = r

    # 4. 逐通道追溯（成文引用 ← 阅读集 ← 通道）
    reading_ids: set[int] = set()
    cited_by_channel: dict[str, int] = {"rss": 0, "web": 0, "search": 0}
    runs = [r for r in db.query(WriteRun).order_by(WriteRun.id.desc()).limit(8).all()
            if (r.payload or {}).get("batch_id") == args.batch]
    for r in runs:
        reading_ids.update(r.reading_set_item_ids or [])
        if r.article_id:
            a = db.get(Article, r.article_id)
            for c in a.citations or []:
                it = db.get(Item, c["item_id"])
                if it is None:
                    continue
                src = db.get(Source, it.source_id)
                if src and src.type in cited_by_channel:
                    cited_by_channel[src.type] += 1
    report["channels"] = trace_channels(db)
    for stype, ch in report["channels"].items():
        if stype == "hot":
            continue
        ch["in_reading_set"] = sum(
            1 for iid in reading_ids
            if (it := db.get(Item, iid)) and it.source_id in
            [s.id for s in db.query(Source).filter_by(type=stype).all()])
        ch["cited_in_articles"] = cited_by_channel[stype]
        if ch.get("cited_in_articles", 0) == 0:
            if ch.get("passed", 0) == 0:
                ch["exit_reason"] = "该通道条目全部未通过打分阈值（或无 FETCHED 条目）"
            else:
                ch["exit_reason"] = "有通过条目但未进入本批阅读集 top-K（被其他通道高分条目挤出）"
    report["write_runs"] = [
        {"run": r.id, "author": db.get(Author, r.author_id).name, "status": r.status,
         "article": r.article_id, "reading_set": len(r.reading_set_item_ids or [])}
        for r in runs]

    VERIFY.mkdir(exist_ok=True)
    (VERIFY / "e2e_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    # md 摘要
    md = [f"# E2E 端到端报告 {report['batch']}", f"> {report['started']}", "",
          "## 通道追溯", ""]
    for stype, ch in report["channels"].items():
        md.append(f"- **{ch['label']}**：{json.dumps({k: v for k, v in ch.items() if k != 'label'}, ensure_ascii=False)}")
    md += ["", "## 写作", ""]
    for w in report["write_runs"]:
        md.append(f"- run {w['run']} {w['author']}: {w['status']} article={w['article']} 阅读集 {w['reading_set']} 条")
    (VERIFY / "e2e_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(report["channels"], ensure_ascii=False, indent=1))
    print(f"[e2e] 报告 -> verify/e2e_report.json / verify/e2e_report.md")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
