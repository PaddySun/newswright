"""夜跑晨报生成（任务书 §7.5.5）：批跑结束后自动生成 夜跑晨报-<日期>.md。

内容：进度与里程碑状态 / 成稿·废稿清单（DB id 对照）/ 异常与失败清单 /
Token 按作者·节点汇总 / 遗留问题 / （可选）soak 期间调度器轮次统计。

用法：python scripts/morning_report.py [--batch ovnight_20260929] [--date 20260929]
      [--include-soak]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import (Article, Author, Item, PipelineTask, ScoreResult,  # noqa: E402
                        UsageLog, WriteRun)
from sqlalchemy import func  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[2] / "doc" / "草稿与过程文件" / "写作实测"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default=None)
    ap.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--include-soak", action="store_true")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    lines: list[str] = []
    q = db.query(WriteRun).order_by(WriteRun.id)
    runs = [r for r in q.all()
            if args.batch is None or (r.payload or {}).get("batch_id") == args.batch]

    lines.append(f"# 夜跑晨报 {args.date}\n")
    lines.append(f"> 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}；"
                 f"批跑批次：{args.batch or '（全部 write_run）'}\n")

    # 1. 进度与状态
    ok = [r for r in runs if r.status == "OK" and r.decision == "WRITE"]
    skip = [r for r in runs if r.decision == "SKIP"]
    fail = [r for r in runs if r.status == "FAILED"]
    lines.append("## 一、批跑进度\n")
    lines.append(f"- 批跑 write_run：{len(runs)} 篇 | 成稿 {len(ok)} | 不写 {len(skip)} | 失败(废稿) {len(fail)}\n")

    # 2. 成稿清单
    lines.append("\n## 二、成稿清单（DB id 对照）\n")
    lines.append("| write_run | article | 作者 | 标题 | 门禁 stats | 成本(in/out) | 导出文件 |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in ok:
        a = db.get(Article, r.article_id)
        p = r.payload or {}
        stats = json.dumps((p.get("gates_final") or {}).get("stats", {}), ensure_ascii=False)
        cost = p.get("cost", {})
        author = db.get(Author, r.author_id)
        fn = f"{author.name}_{r.created_at:%Y%m%d}_run{r.id}_成稿.md".replace(" ", "")
        lines.append(f"| {r.id} | {r.article_id} | {author.name} | {a.title} | {stats} | "
                     f"{cost.get('prompt_tokens', 0)}/{cost.get('completion_tokens', 0)} | 写作实测/{fn} |")

    # 3. 废稿与失败清单
    lines.append("\n## 三、废稿 / 失败清单（中间稿在 write_run.payload.trace 可查）\n")
    for r in fail:
        author = db.get(Author, r.author_id)
        gf = (r.payload or {}).get("gates_final") or {}
        lines.append(f"- run {r.id}（{author.name}）：{(r.error or '')[:200]}"
                     f" ｜ 终版门禁 issues：{gf.get('issues', [])} ｜ attempts："
                     f"{(r.payload or {}).get('rewrite', {}).get('attempts')}")
    if not fail:
        lines.append("- （无）")

    # 4. Token 汇总（usage_log，call_point 口径）
    lines.append("\n## 四、Token 消耗（usage_log 按作者×调用点汇总）\n")
    rows = (db.query(UsageLog.ref_type, UsageLog.ref_id, UsageLog.call_point,
                     func.count(UsageLog.id), func.sum(UsageLog.prompt_tokens),
                     func.sum(UsageLog.completion_tokens))
            .filter(UsageLog.ref_type == "author")
            .group_by(UsageLog.ref_type, UsageLog.ref_id, UsageLog.call_point).all())
    by_author: dict[int, dict] = {}
    for _rt, rid, cp, n, pt, ct in rows:
        d = by_author.setdefault(rid, {})
        d[cp] = {"calls": n, "in": int(pt or 0), "out": int(ct or 0)}
    for rid, d in by_author.items():
        author = db.get(Author, rid)
        total_in = sum(v["in"] for v in d.values())
        total_out = sum(v["out"] for v in d.values())
        lines.append(f"\n**{author.name}**（author {rid}）：合计 {total_in} in / {total_out} out\n")
        for cp, v in sorted(d.items()):
            lines.append(f"  - {cp}: {v['calls']} 次, {v['in']} / {v['out']}")

    # 5. 调度 soak 统计（可选）
    if args.include_soak:
        since = datetime.now(timezone.utc) - timedelta(hours=12)
        rounds = (db.query(PipelineTask)
                  .filter(PipelineTask.kind.in_(("fetch_round", "hot_round")),
                          PipelineTask.created_at >= since)
                  .order_by(PipelineTask.id).all())
        lines.append("\n## 五、Soak 期间调度器轮次\n")
        new_items = db.query(Item).filter(Item.fetched_at >= since).count()
        new_scored = db.query(ScoreResult).filter(ScoreResult.created_at >= since).count()
        fr = [t for t in rounds if t.kind == "fetch_round"]
        hr = [t for t in rounds if t.kind == "hot_round"]
        lines.append(f"- 12h 窗口：fetch_round {len(fr)} 轮（DONE {sum(1 for t in fr if t.status == 'DONE')}）、"
                     f"hot_round {len(hr)} 轮；新增条目 {new_items}、新增打分 {new_scored}\n")

    # 6. 遗留问题（固定段落，执行侧填）
    lines.append("\n## 六、遗留问题\n")
    lines.append("- reasoner 档：协议层就位（不可用自动回退），但上游实报模型名与档位漂移（deepseek-reasoner 请求实报 deepseek-flash），语义待官方 API 复核。\n")
    lines.append("- distort/callback/selfrev 修订遍为接口占位（任务书 §10 边界）。\n")
    lines.append("- r2-r4 文章池策略留接口（本阶段仅 r1 口径配置位）。\n")

    out = OUT_DIR / f"夜跑晨报-{args.date}.md"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[morning-report] {out}")
    db.close()


if __name__ == "__main__":
    main()
