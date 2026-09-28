"""夜间批跑（任务书 §7.5）：luxun ≥3（含 1 篇 single 对照）+ 谭雅 ≥3。

纪律：
- 幂等断点续跑：batch_id + route 签名查库，已 OK 的不重复执行（scripts/run_write_once.py 内置）；
- 单篇失败不阻塞：FAILED 落库后继续下一篇，批跑结束汇总；
- 全程日志：verify/overnight_run.log 逐篇关键事件；
- 产物实时落库，不依赖进程存活。

用法：python scripts/run_overnight.py [--batch ovnight_20260929]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "verify" / "overnight_run.log"

# (作者, 窗口, route覆盖, 说明)
PLAN = [
    ("鲁迅", None, None, "multi-stage 基线（冒烟已验路线，batch 内幂等重跑）"),
    ("鲁迅", (6, 6), None, "multi-stage 阅读集窗口轮换"),
    ("鲁迅", None, {"draft": {"mode": "single"}, "passes": [], "outline": {"template": "none"}},
     "single 路线对照（W5 成本对比）"),
    ("谭雅·冯·提古雷查夫", None, None, "tanya 基线（切片 round_robin 相位=历史run数）"),
    ("谭雅·冯·提古雷查夫", (6, 6), None, "tanya 窗口轮换 + 切片轮转"),
    ("谭雅·冯·提古雷查夫", (12, 6), None, "tanya 窗口轮换 2（选题去重 L1 实测）"),
]


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default=f"ovnight_{datetime.now():%Y%m%d}")
    ap.add_argument("--triggered-by", default="overnight_batch")
    args = ap.parse_args()

    log(f"=== 夜跑批跑开始 batch={args.batch}，共 {len(PLAN)} 篇 ===")
    results = []
    for i, (author, window, overrides, note) in enumerate(PLAN, 1):
        cmd = [sys.executable, str(ROOT / "scripts" / "run_write_once.py"),
               "--author", author, "--batch-id", args.batch,
               "--triggered-by", args.triggered_by]
        if window:
            cmd += ["--window", f"{window[0]},{window[1]}"]
        if overrides:
            cmd += ["--override", json.dumps(overrides, ensure_ascii=False)]
        log(f"--- [{i}/{len(PLAN)}] {author} window={window} override={bool(overrides)} —— {note}")
        t0 = time.monotonic()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=1800)
            out = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
            log(f"    exit={proc.returncode} ({int(time.monotonic() - t0)}s) {out}")
            if proc.returncode != 0 and proc.stderr.strip():
                log(f"    stderr: {proc.stderr.strip()[-400:]}")
            results.append({"author": author, "window": window, "note": note,
                            "exit": proc.returncode, "out": out})
        except Exception as e:  # 单篇失败不阻塞
            log(f"    EXCEPTION: {e}")
            results.append({"author": author, "note": note, "exit": -1, "out": str(e)})
        time.sleep(2)

    ok = sum(1 for r in results if r["exit"] == 0)
    log(f"=== 批跑结束：成功 {ok}/{len(PLAN)}；逐篇结果已落库（write_run.payload.batch_id={args.batch}）===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
