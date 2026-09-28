"""写作管线门禁（任务书 §4.1：全部代码可判定）。

门禁语义对齐 persona-writing-lab v3_gate / studio_gate（移植不 fork）：
- verdict 统一形态 {"passed", "issues", "warns", "stats"}；issues 非空即不通过。
- 指纹/虚词命中、锚回显（≥20 字符短语级复制，lab 仪器级发现：模型会整句复读风格锚
  骗门禁）、引用逐字溯源、n-gram 复述检查（C 档语义 → 静态记忆块版权门禁）、
  句长标准差（节奏指标）。
- 新增：length（字数区间）、topic_dedup（L1 选题去重前置门禁，标题 bigram Dice）。

所有文本比较先做「去脚注标记 + 空白归一化」的 clean 口径（与 lab v3_gate 一致）。
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

_WS_RE = re.compile(r"\s+")
FOOTNOTE_DEF_RE = re.compile(r"^\[\^[^\]]+\]:.*$", re.M)
FOOTNOTE_MARK_RE = re.compile(r"\[\^([^\]]+)\]")

ECHO_MIN_CHARS = 20  # <20 多为惯用搭配（lab：14-19 容忍带），≥20 判短语级复制


def norm(s: str) -> str:
    return _WS_RE.sub("", (s or "")).lower()


def strip_footnotes(text: str) -> str:
    """去掉 [^K] 标记与文末定义行，得 clean 正文（门禁统一口径）。"""
    t = FOOTNOTE_DEF_RE.sub("", text)
    return FOOTNOTE_MARK_RE.sub("", t)


def clean_text(text: str) -> str:
    return _WS_RE.sub("", strip_footnotes(text))


@dataclass
class Verdict:
    passed: bool = True
    issues: list[str] = field(default_factory=list)
    warns: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def feedback(self) -> str:
        """gated 重试时附给模型的违规说明。"""
        return "；".join(self.issues + self.warns) or "（无）"

    def to_dict(self) -> dict:
        return {"passed": self.passed, "issues": self.issues,
                "warns": self.warns, "stats": self.stats}


def gate_length(text: str, cfg: dict | bool | None, v: Verdict) -> None:
    if not cfg:
        return
    n = len(clean_text(text))
    v.stats["len_chars"] = n
    if isinstance(cfg, dict):
        lo, hi = cfg.get("min", 0), cfg.get("max", 10**9)
        if n < lo:
            v.issues.append(f"字数 {n} < {lo}")
        if n > hi:
            v.issues.append(f"字数 {n} > {hi}")


def gate_fingerprint(text: str, words: list[str], min_hits: int, v: Verdict) -> None:
    clean = clean_text(text)
    hits = [w for w in words if w in clean]
    v.stats["fingerprint_hits"] = hits
    if len(hits) < min_hits:
        v.issues.append(f"风格指纹命中 {len(hits)} < {min_hits}（词表: {words}）")
    elif hits:
        v.warns.append(f"风格指纹 {len(hits)}: {hits}")


def gate_echo_check(text: str, anchor: str, v: Verdict) -> None:
    """锚回显：正文与风格锚的最长公共子串 ≥20 字符判复制（difflib，lab 同口径）。"""
    if not anchor:
        return
    clean = clean_text(text)
    src = _echo_source(anchor)
    if not src:
        return
    m = difflib.SequenceMatcher(None, clean, src, autojunk=False).find_longest_match(
        0, len(clean), 0, len(src))
    v.stats["echo_max_chars"] = m.size
    if m.size >= ECHO_MIN_CHARS:
        v.issues.append(f"回显风格锚 {m.size} 字符：…{clean[m.a:m.a + m.size][:40]}…")


def _echo_source(anchor: str) -> str:
    """剥离锚文本中的元指令行（【…】行与（续…）编排注记），只留叙事示范段（lab v3_echo_source）。"""
    lines = []
    for line in anchor.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("【") or s.startswith("（续") or s.startswith("("):
            continue
        lines.append(s)
    return "".join(lines)


def gate_copyright(text: str, blocks: list[dict], ngram: int, v: Verdict) -> None:
    """正文对静态记忆块的 n-gram 复述检查（lab cgram_overlaps 的中文字符版）：
    原著片段是声音锚不是抄袭源——n 连续字符重叠 ≥2 处判 issue，1 处 warn。"""
    if not blocks or ngram < 2:
        return
    t = norm(clean_text(text))
    hits: list[str] = []
    seen: set[str] = set()
    for b in blocks:
        src = norm(b.get("text", ""))
        if len(src) < ngram:
            continue
        grams = {src[i:i + ngram] for i in range(len(src) - ngram + 1)}
        for i in range(len(t) - ngram + 1):
            g = t[i:i + ngram]
            if g in grams and g not in seen:
                seen.add(g)
                hits.append(g)
    v.stats["copyright_ngram_hits"] = len(hits)
    if len(hits) >= 2:
        v.issues.append(
            f"静态记忆块 n-gram 复述 {len(hits)} 处（n={ngram}，≥2）："
            + " | ".join(h[:24] for h in hits[:3]))
    elif hits:
        v.warns.append(f"静态记忆块 n-gram 命中 {len(hits)} 处（容忍级）: {hits[0][:24]}")


def gate_topic_dedup(title: str, recent_titles: list[str], threshold: float, v: Verdict) -> None:
    """L1 选题去重（三次复现的老问题）：与近期标题做字符 bigram Dice 相似度。
    阈值保守默认 0.55；精确同名直接判重。"""
    t = norm(title)
    for rt in recent_titles:
        r = norm(rt)
        if not t or not r:
            continue
        if t == r:
            v.issues.append(f"选题与近期文章同题：《{rt}》")
            return
        sim = _bigram_dice(t, r)
        if sim >= threshold:
            v.issues.append(f"选题与近期文章《{rt}》过于相似（Dice {sim:.2f} ≥ {threshold}）")
            return


def _bigram_dice(a: str, b: str) -> float:
    if len(a) < 2 or len(b) < 2:
        return 1.0 if a == b else 0.0
    ga = {a[i:i + 2] for i in range(len(a) - 1)}
    gb = {b[i:i + 2] for i in range(len(b) - 1)}
    inter = len(ga & gb)
    return 2 * inter / (len(ga) + len(gb)) if (ga and gb) else 0.0


def sentence_lengths(text: str) -> list[int]:
    clean = strip_footnotes(text)
    sents = [s for s in re.split(r"[。！？!?；;\n]", clean) if len(s.strip()) > 1]
    return [len(_WS_RE.sub("", s)) for s in sents]


def rhythm_stddev(text: str) -> float | None:
    lens = sentence_lengths(text)
    if len(lens) < 5:
        return None
    mean = sum(lens) / len(lens)
    var = sum((x - mean) ** 2 for x in lens) / len(lens)
    return round(var ** 0.5, 1)
