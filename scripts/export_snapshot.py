"""全量数据导出快照：items（含被拒全文）/score_result/articles/write_run/usage_log
→ data/snapshot/<日期>/*.jsonl。磁盘留存（.gitignore），供复跑实验与换库重建。"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

def _dump(rows, path: Path) -> int:
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
            n += 1
    return n


def main() -> int:
    from app.db import SessionLocal
    from app.models import (
        Article, Author, Direction, HotBatch, HotTopic, Item, MemoryEntry,
        PipelineTask, RankCallLog, ScoreResult, SearchCallLog, SearchQuota,
        Source, UsageLog, WriteRun,
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = PROJECT_ROOT / "data" / "snapshot" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    counts = {}
    with SessionLocal() as db:
        def rows(model):
            for r in db.query(model).all():
                d = {c.name: getattr(r, c.name) for c in model.__table__.columns}
                d["_table"] = model.__tablename__
                yield d

        models = (Direction, Source, Item, ScoreResult, Article, WriteRun, UsageLog,
                  Author, MemoryEntry, PipelineTask, HotTopic, HotBatch,
                  SearchCallLog, SearchQuota, RankCallLog)
        for model in models:
            counts[model.__tablename__] = _dump(rows(model), out_dir / f"{model.__tablename__}.jsonl")

    print(f"快照已写入 {out_dir}")
    for k, v in counts.items():
        print(f"  {k}: {v} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
