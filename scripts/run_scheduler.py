"""调度器前台常驻（能力①）：Ctrl-C 退出。调度只入队，执行走 worker 路径。

用法：.venv/Scripts/python scripts/run_scheduler.py [--once-fetch]
  --once-fetch  只跑一轮 fetch+score 立即退出（不等 interval，冒烟用）
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


def main() -> int:
    from app.db import SessionLocal, init_db
    from app.pipeline.runner import enqueue_fetch_round, process_fetch_round, score_round
    from app import scheduler as sched

    init_db()
    if "--once-fetch" in sys.argv:
        with SessionLocal() as db:
            t = enqueue_fetch_round(db, triggered_by="scheduler_once")
            if t is None:
                print("上一轮未结束（防重叠），退出")
                return 1
            print(process_fetch_round(db, t))
            print(score_round(db, triggered_by="scheduler_once"))
        return 0

    sched.start()
    print("调度器已启动（Ctrl-C 退出）。fetch:", sched.status()["intervals"])
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("收到 Ctrl-C，关闭调度器")
        sched.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
