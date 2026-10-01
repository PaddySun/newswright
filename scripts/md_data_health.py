"""morningdeck scratch 库数据体检（向量与排序实测 M18：先体检再构造金标）。

用法：.venv/Scripts/python scripts/md_data_health.py [scratch.db]
输出：打印摘要 + JSON 明细 verify/md_data_health.json。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "data/eval/morningdeck_eval.db"

KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def detect_lang(text: str) -> str:
    """粗粒度语言判定：假名→ja；汉字占比>10%→zh；否则 en。（如实标注为启发式）"""
    if not text:
        return "empty"
    if KANA_RE.search(text):
        return "ja"
    n = len(text)
    cjk = len(CJK_RE.findall(text))
    if cjk / max(n, 1) > 0.10:
        return "zh"
    return "en"


def pct(sorted_vals: list[int], p: float) -> int:
    if not sorted_vals:
        return 0
    i = min(int(len(sorted_vals) * p), len(sorted_vals) - 1)
    return sorted_vals[i]


def main() -> None:
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out: dict = {"db": str(DB)}

    out["counts"] = {
        r[0]: r[1]
        for r in con.execute(
            "select 'news_items',count(*) from news_items union all "
            "select 'sources',count(*) from sources union all "
            "select 'day_briefs',count(*) from day_briefs union all "
            "select 'daily_reports',count(*) from daily_reports union all "
            "select 'report_items',count(*) from report_items union all "
            "select 'api_usage_logs',count(*) from api_usage_logs"
        )
    }

    # 各简报：条目数（经源归属）与 score 分布
    per_brief = []
    for b in con.execute("select id,title,briefing from day_briefs order by position"):
        bid = b["id"]
        n_items = con.execute(
            "select count(*) from news_items n join sources s on n.source_id=s.id where s.day_brief_id=?",
            (bid,),
        ).fetchone()[0]
        scored = con.execute(
            "select n.score from news_items n join sources s on n.source_id=s.id "
            "where s.day_brief_id=? and n.score is not null",
            (bid,),
        ).fetchall()
        scores = sorted(r[0] for r in scored)
        per_brief.append(
            {
                "brief_id": bid,
                "title": b["title"],
                "briefing": b["briefing"],
                "briefing_chars": len(b["briefing"] or ""),
                "items": n_items,
                "scored": len(scores),
                "ge60": sum(1 for s in scores if s >= 60),
                "le30": sum(1 for s in scores if s <= 30),
                "score_min": scores[0] if scores else None,
                "score_max": scores[-1] if scores else None,
                "score_mean": round(sum(scores) / len(scores), 1) if scores else None,
            }
        )
    out["per_brief"] = per_brief

    # report_items 交叉核对：report_items.score 与 news_items.score 是否一致
    ri = con.execute(
        "select r.score as rs, n.score as ns, r.position, n.title from report_items r "
        "join news_items n on n.id=r.news_item_id"
    ).fetchall()
    out["report_items_crosscheck"] = {
        "n": len(ri),
        "score_equal": sum(1 for r in ri if r["rs"] == r["ns"]),
        "sample": [{"rs": r["rs"], "ns": r["ns"], "pos": r["position"], "title": r["title"][:60]} for r in ri[:8]],
    }

    # news_items 全表 NULL / 脏数据
    totals = con.execute("select count(*) from news_items").fetchone()[0]
    nulls = {
        col: con.execute(f"select count(*) from news_items where {col} is null or {col}=''").fetchone()[0]
        for col in ["title", "link", "raw_content", "clean_content", "web_content", "summary", "score", "published_at"]
    }
    out["nulls"] = {"total": totals, **nulls}
    out["status_dist"] = dict(con.execute("select status, count(*) from news_items group by status").fetchall())
    out["scored_count"] = con.execute("select count(*) from news_items where score is not null").fetchone()[0]

    # 语言分布（title+clean_content 启发式）
    lang = Counter()
    for t, c in con.execute("select title, clean_content from news_items"):
        lang[detect_lang((t or "") + " " + (c or "")[:500])] += 1
    out["lang_dist_heuristic"] = dict(lang)

    # clean_content 长度分布
    lens = sorted(
        r[0] for r in con.execute("select length(clean_content) from news_items where clean_content is not null")
    )
    out["clean_content_len"] = {
        "n": len(lens),
        "p50": pct(lens, 0.50),
        "p90": pct(lens, 0.90),
        "p99": pct(lens, 0.99),
        "max": lens[-1] if lens else 0,
        "ge2000": sum(1 for v in lens if v >= 2000),
    }
    web_lens = sorted(
        r[0] for r in con.execute("select length(web_content) from news_items where web_content is not null")
    )
    out["web_content_len"] = {
        "n": len(web_lens),
        "p50": pct(web_lens, 0.50),
        "p90": pct(web_lens, 0.90),
        "ge2000": sum(1 for v in web_lens if v >= 2000),
    }

    # 源清单（G2 近重复配对需要 hnrss 系查询源重叠）
    out["sources_top"] = [
        dict(r)
        for r in con.execute(
            "select s.name, s.url, s.day_brief_id, count(n.id) as items from sources s "
            "left join news_items n on n.source_id=s.id group by s.id order by items desc limit 20"
        )
    ]

    # 标题归一化后的重复度概览（G2 可行性）
    titles = [r[0] for r in con.execute("select title from news_items where title is not null")]

    def norm(t: str) -> str:
        return re.sub(r"[\s\W_]+", "", t.lower(), flags=re.UNICODE)

    norm_counter = Counter(norm(t) for t in titles if norm(t))
    dup_groups = {k: v for k, v in norm_counter.items() if v > 1}
    out["title_dup"] = {
        "exact_normalized_dup_groups": len(dup_groups),
        "dup_items_total": sum(dup_groups.values()),
        "top10": sorted(dup_groups.items(), key=lambda x: -x[1])[:10],
    }

    con.close()
    Path(PROJECT_ROOT / "verify").mkdir(exist_ok=True)
    (PROJECT_ROOT / "verify/md_data_health.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=2)[:4000])


if __name__ == "__main__":
    main()
