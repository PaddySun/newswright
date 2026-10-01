"""embedding 五模型实测（EV1 连通 / EV2 路由 / EV3 跨语言 / EV4 近重复 / EV5 长文本）。

用法（.venv/Scripts/python scripts/test_embeddings.py <cmd> ...）：
  connect                          EV1：5 模型连通 + 维度行为 + MRL + 报错行为
  gen-queries                      G1 检索查询生成（deepseek，call_point=gold_query）
  embed --model M --dims N --trunc T   语料全量向量化 → data/eval/embcache/
  eval  --model M --dims N --trunc T   单配置评测（EV2/3/4 + EV5 若为长文配置）
  report                           汇总所有已评测配置 → verify/EV2..EV5*.json

计量纪律：全部调用走 provider 层（call_point=embed），usage_log 落账，免费也记账。
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import config  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.embedding import registry as embed_registry  # noqa: E402
from app.embedding.base import EmbeddingError  # noqa: E402
from app.providers.deepseek import DeepSeekProvider  # noqa: E402

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from build_vector_gold import CORPUS_PATH, GOLD_DIR, load_corpus  # noqa: E402

VERIFY = PROJECT_ROOT / "verify"
CACHE_DIR = PROJECT_ROOT / "data/eval/embcache"
QUERIES_PATH = PROJECT_ROOT / "verify/gold/G1_queries.json"

MODELS = {
    # key: (moark 模型名, 生产候选维度（None=模型默认）)
    "qwen06": ("Qwen3-Embedding-0.6B", 1024),
    "qwen4": ("Qwen3-Embedding-4B", 1024),
    "qwen8": ("Qwen3-Embedding-8B", 1024),
    "jina4": ("jina-embeddings-v4", 2048),
    "bgem3": ("bge-m3", 1024),
}
TRUNC_DEFAULT = 2000  # 语料向量化生产口径：正文截 2000 字符（标题恒保留）


def provider_for(key: str, dims_key: str | None = None):
    model, _ = MODELS[key]
    s = SessionLocal()
    p = embed_registry.get_provider("moark", s, model=model)
    return p, s


def make_texts(corpus: list[dict], trunc: int) -> list[str]:
    """生产口径文本：标题 + \\n + 正文[:trunc]（正文=clean/raw 合并文本去标题）。"""
    out = []
    for c in corpus:
        body = c["text"][len(c["title"]):].strip() if c["text"].startswith(c["title"]) else c["text"]
        out.append(f"{c['title']}\n{body[:trunc]}" if trunc else f"{c['title']}\n{body}")
    return out


# ---------------- EV1 ----------------

def connect() -> None:
    """EV1 前半：连通、维度行为、MRL、报错行为（走 provider 层计量）。"""
    init_db()
    results: dict[str, dict] = {}
    probes = {
        "zh": "人工智能与大型语言模型正在改变软件工程",
        "en": "Local inference of small decision models on consumer GPUs",
        "ja": "ローカルで動かす小型言語モデルと推論最適化",
    }
    for key, (model, _) in MODELS.items():
        p, s = provider_for(key)
        try:
            t0 = time.monotonic()
            vecs = p.embed(list(probes.values()), call_point="embed_connect")
            dt = time.monotonic() - t0
            results[key] = {
                "model": model,
                "ok": True,
                "dims": sorted({len(v) for v in vecs}),
                "latency_s": round(dt, 2),
                "lang_probe_ok": len({len(v) for v in vecs}) == 1,
            }
        except EmbeddingError as e:
            results[key] = {"model": model, "ok": False, "error": str(e)[:300]}
        finally:
            s.close()
    # dimensions 行为：MRL（qwen06 512/256）与不支持模型的静默忽略探测
    dims_behavior: dict[str, dict] = {}
    for key, (model, _) in MODELS.items():
        p, s = provider_for(key)
        try:
            v = p.embed(["维度探针"], dimensions=512, call_point="embed_dims_probe",
                        expected_dims=None)
            got = len(v[0])
            # expected_dims 不设时基类不校验——这里手动记录"请求 512 实得 got"
            dims_behavior[key] = {"requested": 512, "actual": got,
                                  "mrl_512_ok": got == 512,
                                  "silently_ignored": got != 512}
        except EmbeddingError as e:
            dims_behavior[key] = {"requested": 512, "error": str(e)[:200]}
        finally:
            s.close()
    # 报错行为：空输入串 / 超长 dimensions
    error_behavior: dict[str, str] = {}
    p, s = provider_for("qwen06")
    for name, kwargs, texts in [
        ("empty_string", {"dimensions": None}, [""]),
        ("invalid_dims", {"dimensions": 999999}, ["probe"]),
    ]:
        try:
            p.embed(texts, call_point="embed_error_probe", **kwargs)
            error_behavior[name] = "no-error (returned normally)"
        except EmbeddingError as e:
            error_behavior[name] = str(e)[:200]
    s.close()
    out = {
        "models": results,
        "dimensions_behavior_512": dims_behavior,
        "error_behavior": error_behavior,
        "metering": "全部探测经 provider 层，usage_log call_point=embed_*（免费也记账）",
    }
    (VERIFY / "EV1_embed_connectivity.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=1))


# ---------------- G1 queries ----------------

QUERY_SYSTEM = (
    "你为一个技术新闻简报生成检索查询。给定简报的收录标准（briefing），生成 3 条用户可能用"
    "来检索该简报最想收录内容的查询：第 1 条英文短查询（8-16 词）、第 2 条英文长查询"
    "（30-50 词，描述性）、第 3 条中文查询（15-30 字）。只输出 JSON："
    '{"queries": ["...", "...", "..."]}'
)


def gen_queries() -> None:
    gold = json.loads((GOLD_DIR / "G1_routing.json").read_text(encoding="utf-8"))
    out = []
    for b in gold["briefs"]:
        s = SessionLocal()
        try:
            p = DeepSeekProvider(s)
            data, _ = p.chat_json(
                [{"role": "system", "content": QUERY_SYSTEM},
                 {"role": "user", "content": b["briefing"]}],
                call_point="gold_query", ref_type="brief", max_tokens=400,
            )
            queries = data["queries"]
        finally:
            s.close()
        for q in queries:
            out.append({"brief_id": b["brief_id"], "brief_title": b["title"], "query": q})
    QUERIES_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"queries: {len(out)}")


# ---------------- embed corpus ----------------

def embed_corpus(model_key: str, dims: int | None, trunc: int) -> Path:
    corpus = load_corpus()
    cache = CACHE_DIR / f"{model_key}_d{dims or 'def'}_t{trunc}.npz"
    meta = CACHE_DIR / f"{model_key}_d{dims or 'def'}_t{trunc}.meta.json"
    if cache.exists() and meta.exists():
        print(f"cache hit: {cache.name}")
        return cache
    init_db()
    texts = make_texts(corpus, trunc)
    print(f"embedding {len(texts)} texts -> {cache.name}")
    lock = threading.Lock()
    results: dict[int, list[float]] = {}
    bs = config.EMBED_BATCH_SIZE
    chunks = [(i, texts[i : i + bs]) for i in range(0, len(texts), bs)]
    done = [0]

    def work(chunk):
        idx, ts = chunk
        p, s = provider_for(model_key)
        try:
            vecs = p.embed(ts, dimensions=dims, call_point="embed",
                           expected_dims=dims)
        finally:
            s.close()
        with lock:
            for j, v in enumerate(vecs):
                results[idx + j] = v
            done[0] += 1
            if done[0] % 20 == 0:
                print(f"  batch {done[0]}/{len(chunks)}")

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(work, chunks))
    mat = np.array([results[i] for i in range(len(texts))], dtype=np.float32)
    mat = mat / np.linalg.norm(mat, axis=1, keepdims=True)  # L2 归一化（cosine 即点积）
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, vecs=mat)
    meta.write_text(
        json.dumps({"model_key": model_key, "dims": dims, "trunc": trunc,
                    "n": len(texts), "dim": int(mat.shape[1]),
                    "ids": [c["id"] for c in corpus]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return cache


def load_cache(model_key: str, dims: int | None, trunc: int):
    cache = CACHE_DIR / f"{model_key}_d{dims or 'def'}_t{trunc}.npz"
    meta = CACHE_DIR / f"{model_key}_d{dims or 'def'}_t{trunc}.meta.json"
    if not cache.exists():
        raise SystemExit(f"cache missing: {cache}（先跑 embed）")
    m = json.loads(meta.read_text(encoding="utf-8"))
    vecs = np.load(cache)["vecs"]
    return vecs, m["ids"]


def embed_queries(model_key: str, dims: int | None, queries: list[str]) -> np.ndarray:
    p, s = provider_for(model_key)
    try:
        vecs = p.embed(queries, dimensions=dims, call_point="embed_query")
    finally:
        s.close()
    mat = np.array(vecs, dtype=np.float32)
    return mat / np.linalg.norm(mat, axis=1, keepdims=True)


# ---------------- metrics ----------------

def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """Mann-Whitney AUC：pos 与 neg 相似度分布的分离度。"""
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    greater = (pos[:, None] > neg[None, :]).sum()
    equal = (pos[:, None] == neg[None, :]).sum()
    return float((greater + 0.5 * equal) / (len(pos) * len(neg)))


def eval_config(model_key: str, dims: int | None, trunc: int) -> dict:
    corpus = load_corpus()
    vecs, ids = load_cache(model_key, dims, trunc)
    id2idx = {iid: i for i, iid in enumerate(ids)}
    gold = json.loads((GOLD_DIR / "G1_routing.json").read_text(encoding="utf-8"))
    queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))

    briefs = {b["brief_id"]: b["title"] for b in gold["briefs"]}
    labels = {it["item_id"]: it for it in gold["items"]}
    q_texts = [q["query"] for q in queries]
    q_mat = embed_queries(model_key, dims, q_texts)
    sims = q_mat @ vecs.T  # (nq, n)

    per_query = []
    for qi, q in enumerate(queries):
        own = q["brief_id"]
        s = sims[qi]
        order = np.argsort(-s)
        ranked = [ids[i] for i in order]
        pos_ids = [iid for iid, it in labels.items()
                   if it["brief_owner"] == own and (it["scores"].get(own) or 0) >= 60
                   and iid in id2idx]
        neg_ids = [iid for iid, it in labels.items()
                   if it["brief_owner"] == own and (it["scores"].get(own) or 0) <= 30
                   and iid in id2idx]
        def rank_of(iid):
            return ranked.index(iid) + 1 if iid in ranked else None
        pos_ranks = [rank_of(i) for i in pos_ids]
        pos_ranks = [r for r in pos_ranks if r]
        recall5 = sum(1 for r in pos_ranks if r <= 5) / len(pos_ids) if pos_ids else None
        recall10 = sum(1 for r in pos_ranks if r <= 10) / len(pos_ids) if pos_ids else None
        mrr = sum(1.0 / r for r in pos_ranks) / len(pos_ids) if pos_ids else None
        # 正负分离（检索视角：cos 相似度分布）
        pos_sims = [s[id2idx[i]] for i in pos_ids if i in id2idx]
        neg_sims = [s[id2idx[i]] for i in neg_ids if i in id2idx]
        sep_auc = auc(np.array(pos_sims), np.array(neg_sims)) if pos_sims and neg_sims else None
        # 跨 brief 混入：top-10 中属于"其他 brief 的正例（按其自身 brief 标签）"的占比
        top10 = ranked[:10]
        labeled = [i for i in top10 if i in labels]
        mixed = [i for i in labeled
                 if labels[i]["brief_owner"] != own
                 and (labels[i]["scores"].get(labels[i]["brief_owner"]) or 0) >= 60]
        per_query.append({
            "brief": briefs[own], "query": q["query"],
            "n_pos": len(pos_ids), "n_neg": len(neg_ids),
            "recall@5": None if recall5 is None else round(recall5, 3),
            "recall@10": None if recall10 is None else round(recall10, 3),
            "mrr": None if mrr is None else round(mrr, 3),
            "sep_auc": None if sep_auc is None else round(sep_auc, 3),
            "mix@10": (len(mixed), len(labeled)),
        })

    # 限池检索（主口径）：标注集 259 条内检索排序——全库绝对 Recall 在稀疏标注
    # （259/6812=3.8%）下无意义；限池口径回答"金标正例是否排在金标负例前面"。
    labeled_ids = [iid for iid in labels if iid in id2idx]
    lab_idx = np.array([id2idx[i] for i in labeled_ids])
    per_query_r = []
    for qi, q in enumerate(queries):
        own = q["brief_id"]
        sub = sims[qi][lab_idx]
        order2 = np.argsort(-sub)
        ranked2 = [labeled_ids[j] for j in order2]
        pos_ids2 = [iid for iid in labeled_ids
                    if labels[iid]["brief_owner"] == own
                    and (labels[iid]["scores"].get(own) or 0) >= 60]
        ranks2 = [ranked2.index(i) + 1 for i in pos_ids2]
        k5 = sum(1 for r in ranks2 if r <= 5) / len(pos_ids2) if pos_ids2 else None
        k10 = sum(1 for r in ranks2 if r <= 10) / len(pos_ids2) if pos_ids2 else None
        mrr2 = sum(1.0 / r for r in ranks2) / len(pos_ids2) if pos_ids2 else None
        per_query_r.append({
            "brief": briefs[own],
            "n_pos": len(pos_ids2),
            "recall@5": None if k5 is None else round(k5, 3),
            "recall@10": None if k10 is None else round(k10, 3),
            "mrr": None if mrr2 is None else round(mrr2, 3),
        })

    # EV3 跨语言 known-item
    g3 = json.loads((GOLD_DIR / "G3_known_item.json").read_text(encoding="utf-8"))
    cases = [c for c in g3["cases"] if c.get("query")]
    gq = embed_queries(model_key, dims, [c["query"] for c in cases])
    gs = gq @ vecs.T
    by_dir: dict[str, list[int]] = {}
    for ci, c in enumerate(cases):
        tgt = c["item_id"]
        rank = int(np.argmax(np.argsort(-gs[ci]) == id2idx.get(tgt, -1))) + 1 if tgt in id2idx else None
        if tgt in id2idx:
            r = int(np.where(np.argsort(-gs[ci]) == id2idx[tgt])[0][0]) + 1
            by_dir.setdefault(f'{c["item_lang"]}→{c["query_lang"]}', []).append(r)
    ev3 = {
        f"{d}": {
            "n": len(rs),
            "recall@1": round(sum(1 for r in rs if r == 1) / len(rs), 3),
            "recall@5": round(sum(1 for r in rs if r <= 5) / len(rs), 3),
            "recall@10": round(sum(1 for r in rs if r <= 10) / len(rs), 3),
            "mrr": round(sum(1 / r for r in rs) / len(rs), 3),
        }
        for d, rs in by_dir.items()
    }

    # EV4 近重复对分离 + 探索层 P5
    g2 = json.loads((GOLD_DIR / "G2_pairs.json").read_text(encoding="utf-8"))

    def pair_sims(pairs):
        out = []
        for p in pairs:
            a, b = p["a"]["id"], p["b"]["id"]
            if a in id2idx and b in id2idx:
                out.append(float(vecs[id2idx[a]] @ vecs[id2idx[b]]))
        return out

    ps_exact = pair_sims(g2["positive_exact"])
    ps_para = pair_sims(g2["positive_paraphrase"])
    ns_hard = pair_sims(g2["negative_hard"])
    ns_rand = pair_sims(g2["negative_random"])
    pos_all = np.array(ps_exact + ps_para)
    neg_all = np.array(ns_hard + ns_rand)
    ev4 = {
        "sim_pos_exact_mean": round(float(np.mean(ps_exact)), 4) if ps_exact else None,
        "sim_pos_para_mean": round(float(np.mean(ps_para)), 4) if ps_para else None,
        "sim_neg_hard_mean": round(float(np.mean(ns_hard)), 4) if ns_hard else None,
        "sim_neg_random_mean": round(float(np.mean(ns_rand)), 4) if ns_rand else None,
        "auc_pos_vs_neg": round(auc(pos_all, neg_all), 3),
        "auc_pos_vs_hard_neg": round(auc(pos_all, np.array(ns_hard)), 3) if ns_hard else None,
        "gap_pos_mean_minus_hard_neg_mean":
            round(float(np.mean(pos_all) - np.mean(ns_hard)), 4),
        "n_pairs": {"pos_exact": len(ps_exact), "pos_para": len(ps_para),
                    "neg_hard": len(ns_hard), "neg_random": len(ns_rand)},
    }
    # 探索层：每 brief 查询距离最远 5% 条目的自身 brief 得分（质量地板参照）
    expl = []
    for qi, q in enumerate(queries):
        own = q["brief_id"]
        s = sims[qi]
        n_tail = max(int(len(ids) * 0.05), 10)
        tail_idx = np.argsort(s)[:n_tail]
        scores = []
        for i in tail_idx:
            it = labels.get(ids[i])
            if it and it["brief_owner"] == own and it["scores"].get(own) is not None:
                scores.append(it["scores"][own])
        expl.append({
            "brief": briefs[own],
            "tail_labeled_n": len(scores),
            "tail_score_ge40": sum(1 for x in scores if x >= 40),
            "tail_score_max": max(scores) if scores else None,
        })

    out = {
        "model_key": model_key,
        "model": MODELS[model_key][0],
        "dims": dims or "default",
        "trunc": trunc,
        "ev2_routing_per_query": per_query,
        "ev2_routing_restricted_pool": per_query_r,
        "ev2_note": "restricted_pool=主口径（259 标注条内检索）；全库 per_query 为参考"
                    "（标注密度 3.8%，绝对 Recall 被未标注条目稀释）",
        "ev3_crosslingual": ev3,
        "ev4_neardup": ev4,
        "ev4_exploration_tail": expl,
    }
    return out


# ---------------- EV5 长文本 ----------------

def eval_longtext(model_key: str, dims: int | None) -> dict:
    """G4 长文本子集：36 条 ≥2000 字符长文，标题生成查询（en），测 4 档截断下目标排名。"""
    corpus = load_corpus()
    g4 = json.loads((GOLD_DIR / "G4_longtext.json").read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in corpus}
    items = [by_id[g["item_id"]] for g in g4["items"]]
    # 查询：用条目标题生成跨语言 en 查询太贵——直接用标题（标题不在正文截断范围内，
    # 但在文本首行——改用"标题以外的首个问题式改写"不可行；采用标题作 query，同时把
    # 标题从被检索文本中剔除以保证公平）。这里改为：query=标题；文本=正文（不含标题）。
    queries = [c["title"] for c in items]
    q_mat = embed_queries(model_key, dims, queries)
    res = {}
    for trunc in [512, 1000, 2000, None]:
        texts = [c["text"][len(c["title"]):].strip()[:trunc] if c["text"].startswith(c["title"])
                 else c["text"][:trunc] for c in items]
        # 长文本逐条发送：服务端按 token 预算拆批会重编号 index（EV1 实测），
        # 且单条失败可定位到具体条目（如实记录，不猜补）
        mat_rows: list = []
        fails = []
        for i, t in enumerate(texts):
            p, s = provider_for(model_key)
            try:
                v = p.embed([t], dimensions=dims, call_point="embed_longtext")
                mat_rows.append(v[0])
            except EmbeddingError as e:
                fails.append({"i": i, "chars": len(t), "error": str(e)[:150]})
                mat_rows.append(None)
            finally:
                s.close()
        valid = [(i, r) for i, r in enumerate(mat_rows) if r is not None]
        q_ok = [q_mat[i] for i, _ in valid]
        mat = np.array([r for _, r in valid], dtype=np.float32)
        mat = mat / np.linalg.norm(mat, axis=1, keepdims=True)
        sims = np.array(q_ok) @ mat.T
        ranks = []
        for row, (i, _) in zip(sims, valid):
            order = np.argsort(-row)
            ranks.append(int(np.where(order == list(x for x, _ in valid).index(i))[0][0]) + 1)
        res[str(trunc)] = {
            "recall@1": round(sum(1 for r in ranks if r == 1) / len(valid), 3),
            "recall@5": round(sum(1 for r in ranks if r <= 5) / len(valid), 3),
            "mean_rank": round(float(np.mean(ranks)), 2),
            "worst_rank": max(ranks),
            "n_valid": len(valid),
            "fails": fails,
        }
    return {"model_key": model_key, "n_items": len(items), "truncation_recall": res}


# ---------------- CLI ----------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--model", default="qwen06")
    ap.add_argument("--dims", default=None)
    ap.add_argument("--trunc", default=None, type=int)
    args = ap.parse_args()
    dims = int(args.dims) if args.dims else None
    trunc = args.trunc if args.trunc is not None else TRUNC_DEFAULT

    if args.cmd == "connect":
        connect()
    elif args.cmd == "gen-queries":
        gen_queries()
    elif args.cmd == "embed":
        embed_corpus(args.model, dims, trunc)
    elif args.cmd == "eval":
        out = eval_config(args.model, dims, trunc)
        (VERIFY / f"EV2_eval_{args.model}_d{dims or 'def'}_t{trunc}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(json.dumps({k: v for k, v in out.items() if k != "ev2_routing_per_query"},
                         ensure_ascii=False, indent=1))
    elif args.cmd == "eval-long":
        out = eval_longtext(args.model, dims)
        (VERIFY / f"EV5_longtext_{args.model}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(json.dumps(out, ensure_ascii=False, indent=1))
    elif args.cmd == "report":
        report()
    else:
        print(__doc__)


def report() -> None:
    """汇总所有 eval JSON → EV2/EV3/EV4 总表。"""
    rows = []
    for f in sorted(VERIFY.glob("EV2_eval_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        pq = d["ev2_routing_per_query"]
        rq = d.get("ev2_routing_restricted_pool", [])
        def avg(items, k):
            vals = [x[k] for x in items if x.get(k) is not None]
            return round(sum(vals) / len(vals), 3) if vals else None
        rows.append({
            "model": d["model"], "dims": d["dims"], "trunc": d["trunc"],
            "recall@5": avg(rq, "recall@5"), "recall@10": avg(rq, "recall@10"),
            "mrr": avg(rq, "mrr"),
            "sep_auc": avg(pq, "sep_auc"),
            "ev3_recall@5": (
                round(float(np.mean([v["recall@5"] for v in d["ev3_crosslingual"].values()])), 3)
                if d["ev3_crosslingual"] else None),
            "ev4_auc": d["ev4_neardup"]["auc_pos_vs_neg"],
            "ev4_auc_hard": d["ev4_neardup"].get("auc_pos_vs_hard_neg"),
        })
    (VERIFY / "EV2-EV4_summary.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
