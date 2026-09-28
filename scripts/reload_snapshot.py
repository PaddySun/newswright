"""从快照回灌重建（跳过网络抓取，换库/换机/断网可复跑打分与写作实验）。

用法：python scripts/reload_snapshot.py data/snapshot/<目录>
行为：向**当前 DB** 幂等回灌——按唯一键去重（direction.name / source.url / item(source_id,guid) /
其余表按主键存在即跳过），保留自增 ID 与快照一致（SQLite 直接显式主键插入）。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# 回灌顺序：外键依赖序（hot_batch 先于 hot_topic）
TABLE_ORDER = ["direction", "source", "item", "score_result", "author", "memory_entry",
               "write_run", "article", "usage_log", "pipeline_task",
               "hot_batch", "hot_topic", "search_call_log", "search_quota", "rank_call_log"]
MODEL_MAP = {
    "direction": "Direction", "source": "Source", "item": "Item",
    "score_result": "ScoreResult", "author": "Author", "memory_entry": "MemoryEntry",
    "write_run": "WriteRun", "article": "Article", "usage_log": "UsageLog",
    "pipeline_task": "PipelineTask", "hot_batch": "HotBatch", "hot_topic": "HotTopic",
    "search_call_log": "SearchCallLog", "search_quota": "SearchQuota",
    "rank_call_log": "RankCallLog",
}


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python scripts/reload_snapshot.py <snapshot_dir>")
        return 2
    snap_dir = Path(sys.argv[1])
    if not snap_dir.is_dir():
        print(f"快照目录不存在: {snap_dir}")
        return 2

    from app.db import SessionLocal, init_db
    from app import models as M

    init_db()
    total = {}
    with SessionLocal() as db:
        for table in TABLE_ORDER:
            path = snap_dir / f"{table}.jsonl"
            if not path.exists():
                continue
            model = getattr(M, MODEL_MAP[table])
            datetime_cols = {c.name for c in model.__table__.columns if isinstance(c.type, DateTime)}
            n = 0
            for line in open(path, encoding="utf-8"):
                rec = json.loads(line)
                rec.pop("_table", None)
                for col in datetime_cols:
                    v = rec.get(col)
                    if isinstance(v, str):
                        rec[col] = datetime.fromisoformat(v)
                if db.get(model, rec["id"]) is not None:
                    continue
                db.add(model(**rec))
                n += 1
            db.commit()
            total[table] = n
    print("回灌完成（新增行数）:")
    for k, v in total.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
