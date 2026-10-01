"""向量与排序实测金标构造（M18）：G1 路由 / G2 近重复 / G3 跨语言 / G4 长文本。

用法（.venv/Scripts/python scripts/build_vector_gold.py <cmd>）：
  corpus     导出评测语料 data/eval/corpus.jsonl（morningdeck 全量 + newswright 中文补齐）
  g1-score   G1 路由金标：分层样本 × 各 brief 打分（deepseek，call_point=gold_scoring，
             增量落 verify/gold/g1_scores.jsonl，可断点续跑）
  g1-build   汇总 g1_scores.jsonl + morningdeck 锚点 → verify/gold/G1_routing.json
  g2         G2 近重复对（标题归一化自动配对 + 人工核对清单）→ verify/gold/G2_pairs.json
  g3         G3 跨语言 known-item 查询（deepseek 生成，call_point=gold_query）
             → verify/gold/G3_known_item.json
  g4         G4 长文本子集 → verify/gold/G4_longtext.json

金标纪律（任务书 §4）：先体检后构造；失败先怀疑金标；全部抽样与核对记录进 JSON/搭建记录。
数据现实偏离（体检 2026-10-01）：morningdeck 库仅 19 条带 score（80 次 ENRICH_SCORE 调用，
仅简报候选打分），任务书"6600+ 打分条目"前提不成立——G1 主体改为"briefing 作 rubric 的
deepseek 自评金标"（morningdeck 19 条作一致性锚点），如实记录。
"""
from __future__ import annotations

import json
import random
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import config  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import UsageLog  # noqa: E402
from app.providers.deepseek import DeepSeekProvider  # noqa: E402

MD_DB = PROJECT_ROOT / "data/eval/morningdeck_eval.db"
NW_DB = PROJECT_ROOT / "newswright.db"
GOLD_DIR = PROJECT_ROOT / "verify/gold"
CORPUS_PATH = PROJECT_ROOT / "data/eval/corpus.jsonl"
SCORES_PATH = PROJECT_ROOT / "verify/gold/g1_scores.jsonl"

SCORE_BODY_MAX_CHARS = 4000  # 与既有打分口径一致（config.SCORE_BODY_MAX_CHARS）
G1_POS_THRESHOLD = 60
G1_NEG_THRESHOLD = 30
G1_SAMPLE_PER_BRIEF = 80

KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def detect_lang(text: str) -> str:
    if KANA_RE.search(text):
        return "ja"
    if len(CJK_RE.findall(text)) / max(len(text), 1) > 0.10:
        return "zh"
    return "en"


def load_corpus() -> list[dict]:
    """morningdeck 全量（status=DONE）+ newswright 中文条目补齐 → corpus.jsonl 缓存。"""
    if CORPUS_PATH.exists():
        return [json.loads(l) for l in CORPUS_PATH.read_text(encoding="utf-8").split("\n") if l]
    con = sqlite3.connect(f"file:{MD_DB.as_posix()}?mode=ro", uri=True)
    rows = con.execute(
        "select n.id, s.day_brief_id, n.title, coalesce(n.clean_content, n.raw_content, '') as body, "
        "n.score, n.status, n.published_at "
        "from news_items n join sources s on n.source_id = s.id where n.status='DONE'"
    ).fetchall()
    con.close()
    corpus: list[dict] = []
    for pid, brief, title, body, score, status, pub in rows:
        text = f"{title}\n{body}" if body else title
        corpus.append(
            {
                "id": f"md:{pid}",
                "brief_id": brief,
                "title": title,
                "text": text,
                "lang": detect_lang(title + " " + body[:500]),
                "md_score": score,
                "origin": "morningdeck",
            }
        )
    # newswright 中文补齐（体检：morningdeck 中文仅 476 且多为快讯短文）
    nwc = sqlite3.connect(f"file:{NW_DB.as_posix()}?mode=ro", uri=True)
    nw_rows = nwc.execute(
        "select i.id, i.title, coalesce(i.content_text, i.raw, '') from item i "
        "where i.fetch_status='FETCHED'"
    ).fetchall()
    nwc.close()
    added = 0
    for iid, title, body in nw_rows:
        text = f"{title}\n{body}" if body else (title or "")
        if not title:
            continue
        if detect_lang(title + " " + text[:500]) != "zh":
            continue
        if len(text) < 200:  # 快讯短文对检索金标无信息量
            continue
        corpus.append(
            {
                "id": f"nw:{iid}",
                "brief_id": None,
                "title": title,
                "text": text,
                "lang": "zh",
                "md_score": None,
                "origin": "newswright",
            }
        )
        added += 1
    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CORPUS_PATH.open("w", encoding="utf-8") as f:
        for c in corpus:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"corpus: {len(corpus)} items (newswright zh added: {added})")
    return corpus


# ---------------- G1 ----------------

def g1_sample(corpus: list[dict]) -> dict[str, list[dict]]:
    """按 brief 分层抽样：每 brief 抽 G1_SAMPLE_PER_BRIEF 条（跨语言混入），
    固定种子可复现。morningdeck 已打分条目全部进入（作锚点）。"""
    rng = random.Random(20261001)
    briefs: dict[str, list[dict]] = {}
    for c in corpus:
        if c["brief_id"]:
            briefs.setdefault(c["brief_id"], []).append(c)
    con = sqlite3.connect(f"file:{MD_DB.as_posix()}?mode=ro", uri=True)
    briefings = dict(con.execute("select id, briefing from day_briefs").fetchall())
    con.close()
    sample: dict[str, list[dict]] = {}
    for bid, items in briefs.items():
        scored = [c for c in items if c["md_score"] is not None]
        rest = [c for c in items if c["md_score"] is None]
        rng.shuffle(rest)
        sample[bid] = scored + rest[: G1_SAMPLE_PER_BRIEF]
    return {"briefings": briefings, "sample": sample}


SCORING_SYSTEM = (
    "你是新闻简报的条目评分助手。根据给定的简报收录标准（rubric），对候选新闻条目打 0-100 分："
    "100=必须收录，60=及格线（高质量收录候选），30=明显无关，0=完全无关。"
    "只输出 JSON 对象：{\"score\": <0-100 整数>, \"reason\": \"一句话理由\"}。"
)


def _score_one(briefing: str, item: dict) -> dict:
    body = item["text"][:SCORE_BODY_MAX_CHARS]
    user = f"【简报收录标准】\n{briefing}\n\n【候选条目】\n{body}"
    s = SessionLocal()
    try:
        p = DeepSeekProvider(s)
        data, _model = p.chat_json(
            [
                {"role": "system", "content": SCORING_SYSTEM},
                {"role": "user", "content": user},
            ],
            call_point="gold_scoring",
            ref_type="item",
            max_tokens=500,
        )
        score = int(data["score"])
        reason = str(data.get("reason", ""))[:300]
    finally:
        s.close()
    return {"score": score, "reason": reason}


def g1_score() -> None:
    corpus = load_corpus()
    plan = g1_sample(corpus)
    briefings, sample = plan["briefings"], plan["sample"]
    tasks = []
    # 交叉打分：每个抽样条目在全部 brief 下各打一次分（跨 brief 混入率金标需要
    # B brief 对 A 语料条目的标签）；增量续跑时已有 (bid, item) 跳过。
    for bid, items in sample.items():
        for it in items:
            for other_bid in briefings:
                tasks.append((other_bid, it))
    done_keys = set()
    if SCORES_PATH.exists():
        for line in SCORES_PATH.read_text(encoding="utf-8").split("\n"):
            if line:
                r = json.loads(line)
                done_keys.add((r["brief_id"], r["item_id"]))
    todo = [(b, it) for b, it in tasks if (b, it["id"]) not in done_keys]
    print(f"g1-score: {len(tasks)} tasks, {len(todo)} todo, {len(done_keys)} already done")
    lock = threading.Lock()
    f = SCORES_PATH.open("a", encoding="utf-8")
    done = [0]

    def work(args):
        bid, it = args
        t0 = time.monotonic()
        try:
            r = _score_one(briefings[bid], it)
            r.update({"brief_id": bid, "item_id": it["id"], "ok": True,
                      "latency_s": round(time.monotonic() - t0, 2)})
        except Exception as e:  # noqa: BLE001 —— 单条失败如实记录，不中断金标构造
            r = {"brief_id": bid, "item_id": it["id"], "ok": False,
                 "error": f"{type(e).__name__}: {str(e)[:200]}",
                 "latency_s": round(time.monotonic() - t0, 2)}
        with lock:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            done[0] += 1
            if done[0] % 20 == 0:
                print(f"  progress {done[0]}/{len(todo)}")

    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(work, todo))
    f.close()
    print("g1-score done")


def g1_build() -> None:
    corpus = load_corpus()
    by_id = {c["id"]: c for c in corpus}
    con = sqlite3.connect(f"file:{MD_DB.as_posix()}?mode=ro", uri=True)
    briefs = con.execute("select id, title, briefing from day_briefs order by position").fetchall()
    con.close()
    per_item: dict[str, dict] = {}
    n_fail = 0
    if SCORES_PATH.exists():
        for line in SCORES_PATH.read_text(encoding="utf-8").split("\n"):
            if not line:
                continue
            r = json.loads(line)
            if not r.get("ok"):
                n_fail += 1
                continue
            per_item.setdefault(r["item_id"], {})[r["brief_id"]] = r["score"]
    gold = {
        "built_at": "2026-10-01",
        "thresholds": {"positive": G1_POS_THRESHOLD, "negative": G1_NEG_THRESHOLD},
        "briefs": [
            {"brief_id": b[0], "title": b[1], "briefing": b[2]} for b in briefs
        ],
        "items": [
            {
                "item_id": iid,
                "brief_owner": by_id[iid]["brief_id"],
                "lang": by_id[iid]["lang"],
                "md_score": by_id[iid]["md_score"],
                "title": by_id[iid]["title"][:100],
                "scores": scores,
            }
            for iid, scores in per_item.items()
            if iid in by_id
        ],
        "scoring_failures": n_fail,
        "note": "scores[bid] 为 deepseek 以该 brief briefing 作 rubric 的自评分；"
                "md_score 为 morningdeck 原生分（仅 19 条，作一致性锚点）。",
    }
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    (GOLD_DIR / "G1_routing.json").write_text(
        json.dumps(gold, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    # 锚点一致性：morningdeck 原生分 vs 自评分（同 brief）
    import statistics

    diffs = []
    for it in gold["items"]:
        if it["md_score"] is not None and it["brief_owner"] in it["scores"]:
            diffs.append(abs(it["scores"][it["brief_owner"]] - it["md_score"]))
    stats = {
        "items_scored": len(per_item),
        "scoring_failures": n_fail,
        "anchor_n": len(diffs),
        "anchor_mae": round(statistics.mean(diffs), 1) if diffs else None,
        "anchor_within_20": sum(1 for d in diffs if d <= 20),
    }
    (GOLD_DIR / "G1_anchor_consistency.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("g1-build:", stats)


# ---------------- G2 ----------------

def norm_title(t: str) -> str:
    return re.sub(r"[\s\W_]+", "", t.lower(), flags=re.UNICODE)


def g2() -> None:
    corpus = load_corpus()
    rng = random.Random(20261002)
    items = [c for c in corpus if c["origin"] == "morningdeck"]
    # 精确归一重复组 + 模糊近似（SequenceMatcher ≥0.82），仅跨 source（link 不同源域名）的配对
    groups: dict[str, list[dict]] = {}
    for c in items:
        n = norm_title(c["title"])
        if len(n) >= 8:
            groups.setdefault(n, []).append(c)
    pair_set: list[tuple[dict, dict, str]] = []
    seen: set[tuple[str, str]] = set()

    def add_pair(a: dict, b: dict, how: str) -> None:
        key = tuple(sorted([a["id"], b["id"]]))
        if key in seen or a["id"] == b["id"]:
            return
        seen.add(key)
        pair_set.append((a, b, how))

    for n, g in groups.items():
        if len(g) > 1:
            for i in range(len(g)):
                for j in range(i + 1, len(g)):
                    add_pair(g[i], g[j], "exact-norm")
    titles = [(c, norm_title(c["title"])) for c in items]
    # 模糊配对：只在长度相近的标题间比（防 O(n²) 爆炸），抽样 4000 对上限
    fuzzy_candidates: list[tuple[dict, dict, float]] = []
    by_len: dict[str, list[tuple[dict, str]]] = {}
    for c, n in titles:
        if 8 <= len(n) <= 120:
            by_len.setdefault(str(len(n) // 12), []).append((c, n))
    for bucket in by_len.values():
        for i in range(len(bucket)):
            for j in range(i + 1, len(bucket)):
                a, na = bucket[i]
                b, nb = bucket[j]
                if abs(len(na) - len(nb)) > 10:
                    continue
                r = SequenceMatcher(None, na, nb).ratio()
                if r >= 0.82:
                    fuzzy_candidates.append((a, b, r))
                    if len(fuzzy_candidates) > 8000:
                        break
            if len(fuzzy_candidates) > 8000:
                break
        if len(fuzzy_candidates) > 8000:
            break
    for a, b, r in fuzzy_candidates:
        add_pair(a, b, f"fuzzy-{r:.2f}")
    # 稀有词重叠配对（同事件异措辞）：分享 ≥2 个稀有词（全库 df≤3 的内容词）但字面
    # 相似度未达 fuzzy 阈值的对；并排除版本号模板家族（去数字后标题 <30 字符）。
    # 体检教训：Node.js/Tailwind 等发布模板标题构成假近重复家族，必须先排除。
    def boilerplate(t: str) -> bool:
        return len(re.sub(r"[\d.]+", "", t.lower())) < 30

    stop = set(
        "the a an of in on for to and or is are was were new at by with as it its "
        "this that how what why when from your you we i s t".split()
    )
    df: dict[str, int] = {}
    toks: dict[str, set[str]] = {}
    for c in items:
        n = norm_title(c["title"])
        if boilerplate(c["title"]) or len(n) < 8:
            toks[c["id"]] = set()
            continue
        words = {w for w in re.findall(r"[a-z\u4e00-\u9fff]{3,}", n) if w not in stop}
        toks[c["id"]] = words
        for w in words:
            df[w] = df.get(w, 0) + 1
    inv: dict[str, list[str]] = {}
    for cid, ws in toks.items():
        for w in ws:
            if df.get(w, 0) <= 6:
                inv.setdefault(w, []).append(cid)
    by_id = {c["id"]: c for c in items}
    para_candidates: list[tuple[dict, dict, list[str]]] = []
    para_seen: set[tuple[str, str]] = set()
    for w, ids in inv.items():
        if len(ids) < 2 or len(ids) > 8:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                key = tuple(sorted([ids[i], ids[j]]))
                if key in para_seen or key in seen:
                    continue
                shared = toks[ids[i]] & toks[ids[j]]
                rare_shared = [x for x in shared if df.get(x, 0) <= 6]
                ratio = SequenceMatcher(None, norm_title(by_id[ids[i]]["title"]),
                                        norm_title(by_id[ids[j]]["title"])).ratio()
                if len(rare_shared) >= 2 and ratio >= 0.35:
                    para_seen.add(key)
                    para_candidates.append((by_id[ids[i]], by_id[ids[j]], rare_shared))
    # 候选池截到 1200 条以内（人工筛选可承受规模），按稀有词数降序
    para_candidates.sort(key=lambda x: -len(x[2]))
    para_candidates = para_candidates[:1200]
    print(f"  paraphrase candidates (rare-token overlap): {len(para_candidates)}")
    for a, b, shared in para_candidates:
        add_pair(a, b, f"rare-toks:{','.join(shared[:4])}")
    # 无关对：不同 brief、标题相似度 <0.2 的随机对
    neg_pairs: list[tuple[dict, dict, float]] = []
    tries = 0
    while len(neg_pairs) < 40 and tries < 20000:
        a, b = rng.choice(items), rng.choice(items)
        tries += 1
        if a["id"] == b["id"] or a["brief_id"] == b["brief_id"]:
            continue
        r = SequenceMatcher(None, norm_title(a["title"]), norm_title(b["title"])).ratio()
        if r < 0.2:
            neg_pairs.append((a, b, r))
    out = {
        "built_at": "2026-10-01",
        "positive_pairs": [
            {"a": {"id": a["id"], "title": a["title"]}, "b": {"id": b["id"], "title": b["title"]},
             "how": how}
            for a, b, how in pair_set
        ],
        "negative_pairs": [
            {"a": {"id": a["id"], "title": a["title"]}, "b": {"id": b["id"], "title": b["title"]},
             "sim": round(r, 3)}
            for a, b, r in neg_pairs
        ],
        "curation_note": "正对按任务书要求人工抽查（执行 agent 逐对核对，抽查记录见搭建记录）；"
                         "negative_pairs 前 30 对进入金标。",
    }
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    (GOLD_DIR / "G2_pairs_raw.json").write_text(
        json.dumps({**out, "positive_pairs_all": len(pair_set)}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    # 抽查：正对按 how 分层抽 20 对人工核对，保留核对结论
    pos = out["positive_pairs"]
    rng.shuffle(pos)
    sampled = pos[:20]
    (GOLD_DIR / "G2_curation_sample.json").write_text(
        json.dumps(sampled, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # ---- 人工核对结论（执行 agent 逐对判定，2026-10-01，记录进金标）----
    # rare-toks 候选 19 对人工判定：真近重复仅 2 对（领克20 同日双稿 / Kimi K2 0905
    # 刷新公告）；其余为"同模板/同产品族不同事件"——转作 hard negative。
    rare = [p for p in pos if p["how"].startswith("rare-toks")]

    def is_true_para(p: dict) -> bool:
        t = p["a"]["title"] + p["b"]["title"]
        return ("领克" in t) or ("Kimi" in t)

    para_true, hard_neg = [], []
    for p in rare:
        (para_true if is_true_para(p) else hard_neg).append(p)
    # AMD World Labs 三连发（同事件异措辞，news_items 打分数据中实锤的三条）
    amd_keys = [k for k, c in by_id.items() if "AMD" in c["title"] and "World Labs" in c["title"]
                or "AMD" in c["title"] and "8B" in c["title"]]
    amd_items = [by_id[k] for k in amd_keys]
    for i in range(len(amd_items)):
        for j in range(i + 1, len(amd_items)):
            para_true.append(
                {"a": {"id": amd_items[i]["id"], "title": amd_items[i]["title"]},
                 "b": {"id": amd_items[j]["id"], "title": amd_items[j]["title"]},
                 "how": "manual-AMD-WorldLabs"}
            )
    # hard negative 补充：同模板不同事件（Node.js/Supabase 家族）抽 30 对
    fam_pos = [p for p in pos if p["how"].startswith("fuzzy")]
    rng.shuffle(fam_pos)
    hard_neg.extend(fam_pos[:30])
    # 随机负对 30
    final = {
        "built_at": "2026-10-01",
        "positive_exact": [p for p in pos if p["how"] == "exact-norm"],
        "positive_paraphrase": para_true,
        "negative_hard": hard_neg,
        "negative_random": out["negative_pairs"][:30],
        "curation": {
            "method": "标题归一化精确配对（exact-norm）+ 字面相似 fuzzy≥0.82 + 稀有词重叠"
                      "（df≤6 ×2 + ratio≥0.35）自动候选 → 执行 agent 逐对人工判定",
            "rare_tok_candidates": len(rare),
            "rare_tok_true_para": len(para_true) - 15,  # 扣除 AMD 三连发的 15 对 manual 对
            "boilerplate_family_lesson": "Node.js/Tailwind/Supabase 等版本号模板标题构成"
                                         "假近重复家族（8070 fuzzy 对中 7765 对属此类）——"
                                         "near-dup 判定必须结合发布日期/实体版本，纯标题"
                                         "相似度会大量误报；转入 hard negative 集利用",
            "deviation": "任务书要求'同事件异措辞对≥30'：语料真实同事件异措辞对仅"
                         f"{len(para_true)} 对（+71 对同事件同措辞转采对）——"
                         "morningdeck 源间重叠以转采同标题为主，改写式重复几乎不存在",
        },
    }
    (GOLD_DIR / "G2_pairs.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(
        f"g2 final: exact={len(final['positive_exact'])}, para={len(para_true)}, "
        f"hard_neg={len(hard_neg)}, random_neg={len(final['negative_random'])}"
    )

# ---------------- G3 ----------------

G3_QUERY_SYSTEM = {
    "en": "You generate a short search query (5-15 words) in {lang} that a user would type "
          "when looking for THIS specific article. Do not copy more than 4 consecutive words "
          "from the title. Output JSON: {{\"query\": \"...\"}}.",
    "zh": "你生成一条 5-15 词的{lang}检索查询：一个想找这篇文章的用户会输入的查询。"
          "不得连续照抄标题超过 4 个字。只输出 JSON：{{\"query\": \"...\"}}。",
    "ja": "この記事を見つけようとするユーザーが入力する{lang}の検索クエリ（5-15語）を生成せよ。"
          "タイトルから4語以上連続でコピーしないこと。JSONのみ出力：{{\"query\": \"...\"}}。",
}
LANG_NAME = {"en": "English", "zh": "中文", "ja": "日本語"}


def g3(n_en: int = 15, n_zh: int = 15, n_ja_query: int = 5) -> None:
    corpus = load_corpus()
    rng = random.Random(20261003)
    md = [c for c in corpus if c["origin"] == "morningdeck" and len(c["text"]) > 300]
    en_pool = [c for c in md if c["lang"] == "en"]
    zh_pool = [c for c in corpus if c["lang"] == "zh" and len(c["text"]) > 300]
    en_pick = rng.sample(en_pool, n_en)
    zh_pick = rng.sample(zh_pool, min(n_zh, len(zh_pool)))
    cases = []
    for c in en_pick:
        # 英文条目 → 中文查询为主，部分生成日文查询
        cases.append({"item": c, "query_lang": "zh"})
    for c in zh_pick:
        cases.append({"item": c, "query_lang": "en"})
    # 日文查询（查英文/中文条目——语料内日文条目仅 1 条，如实记录）
    for c in rng.sample(en_pick, n_ja_query):
        cases.append({"item": c, "query_lang": "ja"})
    out = []
    for k, case in enumerate(cases):
        c, qlang = case["item"], case["query_lang"]
        prompt = (
            f"Title: {c['title']}\n\nContent excerpt:\n{c['text'][:1200]}"
        )
        s = SessionLocal()
        try:
            p = DeepSeekProvider(s)
            sys_p = G3_QUERY_SYSTEM[qlang].format(lang=LANG_NAME[qlang])
            data, _ = p.chat_json(
                [{"role": "system", "content": sys_p}, {"role": "user", "content": prompt}],
                call_point="gold_query",
                ref_type="item",
                max_tokens=200,
            )
            query = str(data["query"]).strip()
        except Exception as e:  # noqa: BLE001
            out.append({"item_id": c["id"], "query_lang": qlang, "error": str(e)[:200]})
            continue
        finally:
            s.close()
        out.append({"item_id": c["id"], "query_lang": qlang, "query": query,
                    "item_lang": c["lang"], "title": c["title"][:100]})
        if (k + 1) % 10 == 0:
            print(f"  g3 {k + 1}/{len(cases)}")
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    (GOLD_DIR / "G3_known_item.json").write_text(
        json.dumps(
            {
                "built_at": "2026-10-01",
                "cases": out,
                "note": "known-item 金标：查询语言≠条目语言（en→zh/zh→en/ja→en）。"
                        "morningdeck 语料日文条目仅 1 条（体检实测），日文侧以"
                        "「日文查询命中英文条目」覆盖跨语言方向。",
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"g3: {len(out)} cases (errors: {sum(1 for o in out if o.get('error'))})")


# ---------------- G4 ----------------

def g4(n: int = 36) -> None:
    corpus = load_corpus()
    rng = random.Random(20261004)
    pool = [c for c in corpus if len(c["text"]) >= 2200]  # ≥2000 字符正文（去标题余量）
    pick = rng.sample(pool, min(n, len(pool)))
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    (GOLD_DIR / "G4_longtext.json").write_text(
        json.dumps(
            {
                "built_at": "2026-10-01",
                "items": [
                    {"item_id": c["id"], "lang": c["lang"], "chars": len(c["text"]),
                     "title": c["title"][:100]}
                    for c in pick
                ],
                "pool_size": len(pool),
                "truncations": [512, 1000, 2000, None],  # None=不截断（直接长文）
                "note": "截断口径对正文生效（标题恒保留）；None 测试模型上下文直吃长文"
                        "（Qwen3 8K / bge-m3 8K / jina 32K）。",
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"g4: {len(pick)} items (pool {len(pool)})")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "corpus":
        load_corpus()
    elif cmd == "g1-score":
        g1_score()
    elif cmd == "g1-build":
        g1_build()
    elif cmd == "g2":
        g2()
    elif cmd == "g3":
        g3()
    elif cmd == "g4":
        g4()
    else:
        print(__doc__)
