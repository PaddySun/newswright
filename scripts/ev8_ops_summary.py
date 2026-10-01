"""EV8 运维汇总：延迟/条、批量上限、免费档限流实测、存储估算、NeoHorse 计费口径。

用法：.venv/Scripts/python scripts/ev8_ops_summary.py [--burst N]
输出：verify/EV8_ops.json + 摘要打印。
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from app import config  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import UsageLog  # noqa: E402
from test_embeddings import MODELS  # noqa: E402

VERIFY = PROJECT_ROOT / "verify"
SQLITE_PAGE = 4096  # sqlite 默认页大小（估算用）
VEC_HDR = 8  # sqlite-vec float32 向量存 blob：blob 头 + 页开销按 ~1.1× 粗估


def latency_stats() -> dict:
    s = SessionLocal()
    out = {}
    try:
        rows = (s.query(UsageLog)
                .filter(UsageLog.call_point == "embed", UsageLog.ok.is_(True)).all())
        by_model: dict[str, list] = {}
        for r in rows:
            by_model.setdefault(r.model, []).append((r.item_count or 0, r.latency_ms,
                                                     r.prompt_tokens))
        for m, items in by_model.items():
            n_total = sum(i[0] for i in items)
            lat_total = sum(i[1] for i in items)
            toks = [i[2] for i in items]
            out[m] = {
                "batches": len(items),
                "items_total": n_total,
                "ms_per_item": round(lat_total / max(n_total, 1), 1),
                "prompt_tokens_total": sum(toks),
                "tokens_reported_zero": sum(toks) == 0,
            }
    finally:
        s.close()
    return out


def burst_limit(n: int) -> dict:
    """免费档连发观测：qwen06 单条 × n 连发，记录 429/5xx 与耗时。"""
    url = config.MOARK_BASE_URL + "/v1/embeddings"
    H = {"Authorization": f"Bearer {config.MOARK_API_KEY}"}
    codes: dict[str, int] = {}
    t0 = time.monotonic()
    for i in range(n):
        r = httpx.post(url, json={"model": "Qwen3-Embedding-0.6B",
                                  "input": [f"限流探针 {i}"], "encoding_format": "float"},
                       headers=H, timeout=60)
        codes[str(r.status_code)] = codes.get(str(r.status_code), 0) + 1
        if r.status_code in (429, 500, 502, 503):
            time.sleep(1)
    dt = time.monotonic() - t0
    return {"requests": n, "status_codes": codes, "wall_s": round(dt, 1),
            "rps_free_observed": round(n / dt, 2)}


def storage_estimate() -> dict:
    corpus_n = 6812
    out = {}
    for key, (model, dims) in MODELS.items():
        d = {"qwen06_512": 512, "qwen06_256": 256}.get(key, dims)
        bytes_per_vec = d * 4
        raw_gb = corpus_n * bytes_per_vec / 1e9
        out[f"{model}@{d}"] = {
            "bytes_per_vec": bytes_per_vec,
            "raw_6812_items_mb": round(raw_gb * 1000, 1),
            "sqlite_page_overhead_est_mb": round(raw_gb * 1000 * 1.12, 1),
            "sqlite_file_pages": int(corpus_n * bytes_per_vec / SQLITE_PAGE) + 1,
        }
    # 暴力检索延迟预估：numpy 点积 6812×1024 实测参考（本机 demo 级别）
    import numpy as np

    q = np.random.rand(1, 1024).astype(np.float32)
    db = np.random.rand(corpus_n, 1024).astype(np.float32)
    t0 = time.monotonic()
    for _ in range(10):
        _ = (db @ q.T).ravel()
    dt = (time.monotonic() - t0) / 10 * 1000
    out["brute_force_numpy_1024d_ms"] = round(dt, 3)
    return out


def neohorse_billing() -> dict:
    """EV7 调用的计量口径汇总（usage_log: input/output/billing_units/expanded）。"""
    s = SessionLocal()
    out = {}
    try:
        rows = (s.query(UsageLog)
                .filter(UsageLog.provider == "moark_jev").all())
        by_model: dict[str, list] = {}
        for r in rows:
            by_model.setdefault(r.model, []).append(r)
        for m, rs in by_model.items():
            out[m] = {
                "calls": len(rs),
                "input_tokens": sum(r.prompt_tokens for r in rs),
                "output_tokens": sum(r.completion_tokens for r in rs),
                "billing_units": sum(r.billing_units for r in rs),
                "latency_ms_mean": round(statistics.mean(r.latency_ms for r in rs), 0),
                "note": "systemone usage 含 expanded_input_tokens（ criteria 展开后）"
                        "与 input_tokens 两口径，adapter 记 input_tokens",
            }
    finally:
        s.close()
    return out


if __name__ == "__main__":
    burst_n = 30
    if "--burst" in sys.argv:
        burst_n = int(sys.argv[sys.argv.index("--burst") + 1])
    out = {
        "latency_per_item": latency_stats(),
        "burst_free_tier": burst_limit(burst_n),
        "storage_estimate": storage_estimate(),
        "neohorse_billing": neohorse_billing(),
        "batch_limits_observed": {
            "Qwen3-Embedding-0.6B": "1000 条/请求（1001→400）",
            "Qwen3-Embedding-4B": "100 条/请求（128→400 'maximum of 100 inputs'）",
            "Qwen3-Embedding-8B/jina/bge": "64 批实测触发服务端按 token 拆批重编号 index"
                                            "（数量校验护栏拦截，生产建议批 ≤16-32）",
        },
    }
    (VERIFY / "EV8_ops.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=1))
