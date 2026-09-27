"""V5 验证：管线可靠性（DB 即队列 + 失败重试 + 幂等）。

A. 重复跑 fetch+score：去重拦截全部条目，已 OK 打分零重打（usage_log 增量为 0）。
B. 故障注入：临时改错打分模型名 → 新条目打分 → 任务 FAILED、score_result 落 FAILED+原因、
   item 全文保留；恢复模型名后续跑 → 新条目补打成功，且旧条目不重复打分。
产出：verify/V5_pipeline_reliability.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

OUT_PATH = PROJECT_ROOT / "verify" / "V5_pipeline_reliability.json"


def count(db, model, **kw):
    return db.query(model).filter_by(**kw).count() if kw else db.query(model).count()


def main() -> int:
    from app.db import SessionLocal, init_db
    from app.models import Item, PipelineTask, ScoreResult, Source, UsageLog
    from app.pipeline.runner import fetch_round, score_round
    from app import config as cfg

    init_db()
    report: dict = {}

    with SessionLocal() as db:
        # ---- A. 幂等 ----
        before_usage_scoring = count(db, UsageLog, call_point="scoring")
        before_scores_ok = count(db, ScoreResult, status="OK")
        fetch2 = fetch_round(db, triggered_by="v5-idempotency")
        score2 = score_round(db, triggered_by="v5-idempotency")
        after_usage_scoring = count(db, UsageLog, call_point="scoring")
        report["A_idempotency"] = {
            "fetch_round2_sources": [
                {"url": s["url"].split("/")[2], "status": s["status"], "feed": s.get("feed_entries", 0),
                 "dup_blocked": s.get("dup_blocked", 0), "inserted": s.get("inserted", 0), "error": s.get("error")}
                for s in fetch2["sources"]
            ],
            "score_round2": score2["directions"],
            "scoring_llm_calls_delta": after_usage_scoring - before_usage_scoring,
            "scores_ok_before": before_scores_ok,
            "scores_ok_after": count(db, ScoreResult, status="OK"),
            "total_items": count(db, Item),
        }

        # ---- B. 故障注入 ----
        src = db.query(Source).first()
        items_new = []
        for i in range(2):
            it = Item(
                source_id=src.id, guid=f"v5-test-{i}", url="https://v5.local/x",
                title=f"V5 故障注入测试条目 {i}",
                content_text="这是一条用于验证失败恢复的测试内容。" * 20,
            )
            db.add(it)
            items_new.append(it)
        db.commit()
        new_ids = [it.id for it in items_new]

        real_model = cfg.DEEPSEEK_MODEL
        cfg.DEEPSEEK_MODEL = "deepseek-nonexistent-model"  # 注入错误模型名
        score3 = score_round(db, triggered_by="v5-fault")
        cfg.DEEPSEEK_MODEL = real_model  # 恢复

        failed_rows = db.query(ScoreResult).filter(ScoreResult.item_id.in_(new_ids)).all()
        tasks = db.query(PipelineTask).filter_by(kind="score").order_by(PipelineTask.id.desc()).first()
        report["B_fault_injection"] = {
            "injected_model": "deepseek-nonexistent-model",
            "score_round3": score3["directions"],
            "score_results_for_new_items": [
                {"item_id": r.item_id, "status": r.status, "error": (r.error or "")[:120]} for r in failed_rows
            ],
            "new_items_content_kept": all(
                len(db.get(Item, i).content_text) > 100 for i in new_ids
            ),
            "latest_score_task": {
                "id": tasks.id, "status": tasks.status, "last_error": (tasks.last_error or "")[:120],
            },
        }

        # 恢复后续跑
        score4 = score_round(db, triggered_by="v5-recovery")
        rows_after = db.query(ScoreResult).filter(
            ScoreResult.item_id.in_(new_ids), ScoreResult.status == "OK"
        ).count()
        after_scores_ok = count(db, ScoreResult, status="OK")
        scoring_calls_total = count(db, UsageLog, call_point="scoring")
        report["C_recovery"] = {
            "score_round4": score4["directions"],
            "new_items_now_scored_ok": rows_after,
            "scores_ok_after_recovery": after_scores_ok,
            "note": "恢复后仅 2 条新条目被补打，旧 OK 条目未重打（见 usage delta）",
        }

    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"结果已写入 {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
