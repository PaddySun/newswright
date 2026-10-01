"""切片提取器（任务书 M16.3）：项目文档（外层）谭雅/小说素材（14 个 GBK txt）→ 候选切片清单。

方法（如实记录，全程确定性、零 LLM 成本）：
1. GBK 严格解码（失败回退 errors=replace 并记录 decode_failed 文件）；
2. 结构化切分：非空行=段落（含起止行号）；相邻段落粘合为"自包含对话/独白段"，
   可见字符 ≤500（**切片取原文精确子串，仅去首尾空白，保证逐字性**）；
3. 声音代表性评分（词表源自《谭雅角色卡设定.md》§五用词域与§二核心算法）：
   强标记（成本/损益/预算/风险/效率/合理/人事/激励/复盘/备案/止损/交涉/存在X/神…）
   ×3 + 对话标记「×1 + 第一人称×1（上限2）；无强标记者剔除；
4. 多样性：每文件最多 3 片、同文件 50 字首部去重、全局按分排序取前 N。

用法：
  python scripts/extract_slices.py --top 16 --out config/authors/tanya_slices.json
  python scripts/extract_slices.py --top 16 --apply config/authors/tanya.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT.parent / "doc" / "谭雅" / "小说素材"

# 声音代表性词表（出处：谭雅角色卡 §五用词域、§二决策流程与核心算法）
STRONG_MARKERS = [
    "成本", "损益", "损耗", "预算", "风险", "回报", "效率", "合理", "理性", "人事",
    "绩效", "激励", "复盘", "备案", "归档", "止损", "交涉", "谈判", "薪水分母",
    "存在", "神", "信仰", "参谋", "帝国军", "魔导师", "战争", "士气", "缺陷",
    "暇疵", "瑕疵", "人事评价", "调令", "加班", "咖啡",
]
WEAK_MARKERS = ["我", "「"]

MIN_CHARS, MAX_CHARS = 80, 500
MAX_PER_FILE = 3


def decode_file(path: Path) -> tuple[str, str]:
    """返回 (text, note)；GBK 严格解码失败时回退 replace 并如实记录。"""
    raw = path.read_bytes()
    try:
        return raw.decode("gbk"), ""
    except UnicodeDecodeError as e:
        return raw.decode("gbk", errors="replace"), f"gbk_decode_failed@{e.start}(replace)"


def paragraphs(text: str) -> list[tuple[int, int, str]]:
    """[(起始行, 结束行, 原文精确子串)]；行号 1-based。"""
    out = []
    start = None
    char_off = 0
    seg_start_off = seg_end_off = 0
    last_nonblank = 0
    for lineno, line in enumerate(text.splitlines(keepends=True), 1):
        if line.strip():
            last_nonblank = lineno
            if start is None:
                start = lineno
                seg_start_off = char_off + (len(line) - len(line.lstrip()))
            seg_end_off = char_off + len(line.rstrip())
        else:
            if start is not None:
                out.append((start, lineno - 1, text[seg_start_off:seg_end_off]))
                start = None
        char_off += len(line)
    if start is not None:
        out.append((start, last_nonblank, text[seg_start_off:seg_end_off]))
    return out


def extract(text: str) -> list[dict]:
    """相邻段落粘合（≤6 段、80-500 可见字符）：按行号区间用原文行重切，保逐字。"""
    lines = text.splitlines(keepends=True)
    paras = paragraphs(text)
    out = []
    for i in range(len(paras)):
        for j in range(i, min(i + 6, len(paras))):
            l0, _ = paras[i][0], paras[i][1]
            l1 = paras[j][1]
            piece = "".join(lines[l0 - 1 : l1]).strip()
            n = len(piece)
            if n > MAX_CHARS:
                break
            if n >= MIN_CHARS:
                out.append({"text": piece, "line_start": l0, "line_end": l1})
    return out


def score(cand: dict) -> int:
    t = cand["text"]
    strong = sum(2 for w in STRONG_MARKERS if w in t)
    weak = min(2, t.count("「")) + min(2, t.count("我"))
    return strong + weak


def has_voice(cand: dict) -> bool:
    return any(w in cand["text"] for w in STRONG_MARKERS)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=16)
    ap.add_argument("--out", default=str(ROOT / "config" / "authors" / "tanya_slices.json"))
    ap.add_argument("--apply", default=None, help="把切片写入该 author.json 的 memory.static_blocks")
    args = ap.parse_args()

    all_c: list[dict] = []
    decoded_ok = decoded_fail = 0
    for f in sorted(SRC_DIR.glob("*.txt")):
        text, note = decode_file(f)
        if note:
            decoded_fail += 1
            print(f"[warn] {f.name}: {note}")
        else:
            decoded_ok += 1
        file_c = [c for c in extract(text) if has_voice(c)]
        for c in file_c:
            c["file"] = f.name
            c["score"] = score(c)
        # 每文件内部去重（首 50 字相同视为同段）后取前 MAX_PER_FILE
        seen: set[str] = set()
        uniq = []
        for c in sorted(file_c, key=lambda x: -x["score"]):
            key = c["text"][:50]
            if key in seen:
                continue
            seen.add(key)
            uniq.append(c)
        all_c.extend(uniq[:MAX_PER_FILE])

    # 全局去重 + 排序取前 N
    seen = set()
    finals = []
    for c in sorted(all_c, key=lambda x: (-x["score"], x["file"], x["line_start"])):
        key = c["text"][:50]
        if key in seen:
            continue
        seen.add(key)
        finals.append(c)
    finals = finals[: args.top]

    # 逐字性自检（切片必须是原文件文本的子串）
    for c in finals:
        src = (SRC_DIR / c["file"]).read_bytes().decode("gbk")
        assert c["text"] in src, f"逐字性校验失败: {c['file']} loc{c['line_start']}"

    payload = {
        "method": "GBK严格解码→段落结构化切分(相邻段≤6段粘合,80-500字)→角色卡用词域确定性评分→每文件≤3片+全局去重",
        "decoded_ok": decoded_ok, "decoded_fail": decoded_fail,
        "total": len(finals),
        "slices": [
            {"id": f"slice_{i+1:03d}", "file": c["file"], "line_start": c["line_start"],
             "line_end": c["line_end"], "chars": len(c["text"]), "score": c["score"],
             "text": c["text"]}
            for i, c in enumerate(finals)
        ],
    }
    out = Path(args.out)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[slices] {decoded_ok} 文件解码OK / {decoded_fail} 失败；候选切片 {len(finals)} → {out}")

    if args.apply:
        target = Path(args.apply)
        cfg = json.loads(target.read_text(encoding="utf-8"))
        cfg["memory"]["static_blocks"] = [
            {"id": s["id"], "text": s["text"],
             "source": f"小说素材/{s['file']} loc{s['line_start']}-{s['line_end']}",
             "injection": {"max_chars": 500}}
            for s in payload["slices"]
        ]
        target.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[apply] {len(payload['slices'])} 片写入 {target}")


if __name__ == "__main__":
    main()
