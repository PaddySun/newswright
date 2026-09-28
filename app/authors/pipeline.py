"""可配置写作管线执行器（任务书 §4，选型草稿 §3.2.4）。

节点库最小集（本阶段）：outline（pyramid/variation/sectional/formula/none）+
draft（single/incubate/rolling/dictate 四模式）+ 修订遍（prune/rhythm；
distort/callback/selfrev 占位接口）+ 门禁（length/fingerprint/echo_check/
citation/copyright/topic_dedup）+ rewrite（gated_retry 附违规说明重试 /
zero_revision 只记审计）。

移植纪律：节点提示词语义 1:1 取自 persona-writing-lab（longgraph_v3/studio.engine，
runs/v3-20260928-134456 已验证），按 newswright 契约改造——引用从「新闻素材 n*/
记忆 m*」改为「阅读集条目 item_id + [^K] 脚注定义行」，输出 markdown 落库。

trace 纪律：全节点 trace（节点/输入摘要/输出全文/门禁结果/重试次数/token/耗时）
落 write_run.payload 并逐节点 commit——废稿（被门禁拒绝或重试弃用的中间稿）即
trace 中的中间产物，DB 可见。

分层纪律：模型不在 author.json——运行时模型取 Author.model；reasoner|chat 档位
走 provider 层（model_tier），不可用自动回退并记录。
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import Article, Author, WriteRun
from ..providers.base import JSONParseError, ProviderError, parse_strict_json
from ..providers.deepseek import DeepSeekProvider
from . import gates as G
from .memory import fill_placeholders
from .schema import AuthorConfigError, load_author_config
from .writer import _hot_brief, assemble_ranked_reading_set

log = logging.getLogger("newswright.pipeline")

READING_BODY_MAX_CHARS = 1200
FOOTNOTE_DEF_RE = re.compile(r"^\[\^(\d+)\]\s*:\s*\[条目\s*(\d+)\]\s*(.*)$", re.M)
FOOTNOTE_MARK_RE = re.compile(r"\[\^(\d+)\]")

# 节点默认 max_tokens（lab 实证口径）；output.max_tokens_per_node 可覆写
NODE_MAX_TOKENS = {"w_outline": 900, "w_incubate": 1400, "w_draft": 4000,
                   "w_prune": 2600, "w_rhythm": 2600, "w_revise": 2600}

# JSON 节点保持 chat 档（lab studio A/B：JSON 节点 reasoner 无风格优势且成本 ×1.8）
JSON_NODES = {"w_outline", "w_incubate"}


class PipelineAbort(Exception):
    """执行中止（阅读集为空等）；run 落 FAILED/SKIP 并保留原因。"""


# ---------------- 提示词装配 ----------------

def _identity_system(cfg: dict) -> str:
    """稳定段（人格卡整体），cache 友好；语义对齐 lab persona_system_v3。"""
    ident = cfg["identity"]
    rules = ident.get("style_rules", {})
    do = "\n".join("- " + r for r in rules.get("do", [])) or "（无）"
    dont = "\n".join("- " + r for r in rules.get("dont", [])) or "（无）"
    fps = "、".join(rules.get("fingerprint", [])[:8]) or "（无）"
    quotes = "\n".join("- " + q for q in ident.get("quotes_original", [])[:5]) or "（无）"
    return f"""你是{ident['name']}。这是一次新闻评论写作任务：以你的身份、人格与文风写作。

【你是谁（传记事实）】
{ident.get('description') or '（未提供）'}

【人格与思维方式】
{ident.get('personality') or '（未提供）'}

【价值立场——必须在文章中可辨识地体现】
{ident.get('values_stance') or '（未提供）'}

【场景】
{ident.get('scenario') or '（未提供）'}

【文风规则——必须做到】
{do}

【文风规则——禁止】
{dont}

【风格指纹（语感自检词）】{fps}

【风格锚——模仿语感，绝不照抄其内容】
{ident.get('style_anchor') or '（未提供）'}

【自我引句（声音锚，少量）】
{quotes}

【输出纪律（硬约束）】
- 只输出被要求的正文；不输出解释或元评论；绝不以"作为AI/模型/助手"口吻说话；绝不提"模仿/实验/人格/设定"字眼。
- 【风格锚使用纪律】锚只示范语感与声音；锚中出现的具体句子、比喻、开场方式与措辞，一律不得复用进你的正文（回显检测器会拦截，拦截即失败）。
- 静态记忆片段（如提供）是你自己的记忆/语感来源，只可模仿其声音，其具体文句不得整段复制进正文（版权检测器会拦截）。"""


def _static_injection(db: Session, author: Author, cfg: dict,
                      pairs: list) -> tuple[list[dict], list[dict]]:
    """静态记忆块按 injection 配置选取与硬预算裁剪。返回 (选中块, payload记录)。

    selection: round_robin=按该作者历史 WriteRun 数轮转（轮换组合实测用）；
    recency=取列表末尾 N 块；relevant=按与阅读集标题的字符 bigram 重叠取前 N。
    硬预算：max_slices_per_run × per_block_max_chars，超长截断并如实记录。
    """
    mem = cfg["memory"]
    inj = mem["injection"]
    blocks = mem.get("static_blocks") or []
    n = int(inj.get("max_slices_per_run") or 0)
    per = int(inj.get("per_block_max_chars") or 500)
    if n <= 0 or not blocks:
        return [], []
    sel = inj.get("selection") or "round_robin"
    if sel == "recency":
        chosen = blocks[-n:]
    elif sel == "relevant":
        titles = G.norm("".join(item.title or "" for item, _ in pairs))
        def score(b: dict) -> float:
            t = G.norm(b.get("text", ""))
            grams = {t[i:i + 2] for i in range(max(0, len(t) - 1))} if len(t) >= 2 else set()
            return len(grams & {titles[i:i + 2] for i in range(max(0, len(titles) - 1))}) if grams else 0.0
        chosen = sorted(blocks, key=score, reverse=True)[:n]
    else:  # round_robin：历史 run 数做轮转相位
        offset = db.query(WriteRun).filter_by(author_id=author.id).count()
        chosen = [blocks[(offset + i) % len(blocks)] for i in range(min(n, len(blocks)))]

    out, records = [], []
    for pos_i, b in enumerate(chosen):
        text = b.get("text", "")
        truncated = len(text) > per
        if truncated:
            text = text[:per]
        out.append({"id": b.get("id", f"blk{pos_i}"), "text": text})
        records.append({"block_id": b.get("id", f"blk{pos_i}"), "source": b.get("source", ""),
                        "chars": len(text), "original_chars": len(b.get("text", "")),
                        "truncated": truncated, "selection": sel})
    return out, records


def _slices_block(slices: list[dict], position: str) -> str:
    if not slices:
        return ""
    body = "\n".join(f"- {s['text']}" for s in slices)
    return (f"\n\n【你的记忆片段（声音锚，只模仿语感；具体文句不得整段复制进正文）】\n{body}\n"
            if position == "tail" else
            f"\n\n【你的记忆片段（声音锚，只模仿语感；具体文句不得整段复制进正文）】\n{body}")


def _recent_titles(db: Session, author: Author, n: int) -> list[str]:
    if n <= 0:
        return []
    rows = (
        db.query(Article.title)
        .filter_by(author_id=author.id)
        .order_by(Article.id.desc())
        .limit(n)
        .all()
    )
    return [r[0] for r in rows]


def _refs_listing(pairs: list) -> str:
    lines = []
    for item, sr in pairs:
        body = (item.content_text or "").strip()[:READING_BODY_MAX_CHARS]
        pub = item.published_at.strftime("%Y-%m-%d") if item.published_at else "未知"
        rel = getattr(sr, "relevance_score", None)
        lines.append(
            f"【条目 {item.id}】{item.title}\n来源: {item.url or '未知'} | 发布: {pub} | 相关分: {rel}\n正文: {body or '（无正文）'}"
        )
    return "\n\n".join(lines)


def _citation_discipline(min_count: int) -> str:
    return f"""【引用纪律（硬约束）】
- 文中的事实性陈述必须来自下方阅读集；每处事实引用在句末标脚注 [^K]（K=1,2,3…按正文出现顺序连续编号）。
- 文末为每个编号写一行定义，格式严格为：[^K]: [条目 <item_id>] <逐字摘自该条目正文的原句>
- 引用至少 {min_count} 条；quote 必须逐字摘自该条目正文（不许改写、拼接、虚构），校验器逐条比对，失败即拒收。
- 阅读集之外的任何材料（含记忆片段、热点风向）一律不得作为引用来源。"""


def _draft_task(cfg: dict, pairs: list, *, incubate: dict | None = None,
                outline: dict | None = None, section: tuple[int, int] | None = None,
                prev_sections: list[str] | None = None) -> str:
    gates = cfg["route"]["gates"]
    length = gates.get("length") or {}
    lo, hi = length.get("min", 600), length.get("max", 1400)
    task = _citation_discipline((gates.get("citation") or {}).get("min_count", 2))
    task += f"\n\n【输出格式】Markdown 正文（不要 HTML；不要一级标题），{lo}-{hi} 字，结尾不写总结腔套话。"
    if incubate:
        task += "\n\n【你的腹稿（照此落笔，可微调）】\n" + json.dumps(incubate, ensure_ascii=False, indent=1)
    if outline and section:
        i, total = section
        sec = outline["sections"][i - 1]
        task += (f"\n\n【规划】{outline.get('title', '')} / {outline.get('thesis', '')}\n"
                 f"本节（第{i}/{total}节）：{sec.get('key', '')} —— {sec.get('brief', '')}")
        if prev_sections:
            task += "\n\n【已写成的正文（衔接，勿重复）】\n" + "\n\n".join(prev_sections)
    return task


# ---------------- 脚注解析与校验 ----------------

def parse_footnote_defs(text: str) -> dict[int, tuple[int, str]]:
    """解析文末定义行 [^K]: [条目 <id>] <quote> → {K: (item_id, quote)}。"""
    defs: dict[int, tuple[int, str]] = {}
    for m in FOOTNOTE_DEF_RE.finditer(text):
        defs[int(m.group(1))] = (int(m.group(2)), m.group(3).strip())
    return defs


def assemble_article_text(title: str, body: str, defs: dict[int, tuple[int, str]]) -> str:
    """正文 + 规范化脚注定义区（渲染白名单：转义 HTML 标签起始角括号；单独的 > 不危险，保留）。"""
    body = re.sub(r"<(?=[a-zA-Z/!])", "&lt;", body)
    body = FOOTNOTE_DEF_RE.sub("", body).rstrip()
    lines = [f"[^{k}]: [条目 {iid}] {q}" for k, (iid, q) in sorted(defs.items())]
    return body + ("\n\n" + "\n".join(lines) if lines else "")


def validate_citations_pipeline(text: str, defs: dict[int, tuple[int, str]],
                                pairs: list, min_count: int) -> None:
    """引用门禁：编号↔定义 1:1、item 在阅读集内、quote 空白归一化子串命中。失败抛 CitationError。"""
    from .writer import CitationError, _norm

    bodies = {item.id: item.content_text or "" for item, _ in pairs}
    marks = {int(m.group(1)) for m in FOOTNOTE_MARK_RE.finditer(FOOTNOTE_DEF_RE.sub("", text))}
    if len(defs) < min_count:
        raise CitationError(f"脚注引用 {len(defs)} 条 < 最低要求 {min_count} 条")
    for k in sorted(marks):
        if k not in defs:
            raise CitationError(f"正文有脚注标记 [^{k}] 但文末缺定义行")
    for k in sorted(defs):
        if k not in marks:
            raise CitationError(f"文末定义 [^{k}] 在正文中没有对应标记")
    for k, (item_id, quote) in defs.items():
        if item_id not in bodies:
            raise CitationError(f"[^{k}] 的条目 {item_id} 不在阅读集内")
        if not quote:
            raise CitationError(f"[^{k}] 的 quote 为空")
        if _norm(quote) not in _norm(bodies[item_id]):
            raise CitationError(f"[^{k}] 的 quote 在条目 {item_id} 正文中找不到（需逐字摘自原文）: {quote[:80]!r}")


# ---------------- 执行器 ----------------

class PipelineRunner:
    def __init__(self, db: Session, author: Author, run: WriteRun, cfg: dict, provider: DeepSeekProvider):
        self.db, self.author, self.run, self.cfg = db, author, run, cfg
        self.provider = provider
        self.trace: list[dict] = []
        self.cost = {"prompt_tokens": 0, "completion_tokens": 0}

    # ---- 基础设施 ----

    def _tier(self, node: str) -> str:
        tr = self.cfg["route"]["think_routing"]
        if node in JSON_NODES:
            return "chat"  # JSON 节点保持 chat（lab 实证）
        return tr.get("per_node", {}).get(node) or tr.get("default", "chat")

    def _max_tokens(self, node: str, default: int) -> int:
        override = self.cfg["output"].get("max_tokens_per_node", {})
        return int(override.get(node) or NODE_MAX_TOKENS.get(node, default))

    def _call(self, node: str, messages: list[dict], *, json_mode: bool = False,
              temperature: float = 0.5) -> tuple[str, dict]:
        """单节点调用：计量入 trace（provider 层 usage_log 照常全量落库）。"""
        t0 = time.monotonic()
        content, model = self.provider.chat(
            messages,
            call_point=node,
            ref_type="author",
            ref_id=self.author.id,
            json_mode=json_mode,
            max_tokens=self._max_tokens(node, 4000),
            temperature=temperature,
            model_tier=self._tier(node),
        )
        usage = dict(self.provider.last_usage)
        entry = {
            "node": node, "tier": self._tier(node),
            "fallback_note": getattr(self.provider, "fallback_note", None),
            "model": model,
            "input_digest": (messages[-1]["content"] or "")[:200],
            "output": content,
            "tokens_in": usage.get("prompt_tokens", 0),
            "tokens_out": usage.get("completion_tokens", 0),
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.trace.append(entry)
        self.cost["prompt_tokens"] += entry["tokens_in"]
        self.cost["completion_tokens"] += entry["tokens_out"]
        self._flush()
        return content, entry

    def _call_json(self, node: str, messages: list[dict], temperature: float) -> dict:
        """JSON 节点：解析失败附反馈重试一次（lab 纪律），再失败如实失败。"""
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                content, _ = self._call(node, messages, json_mode=True, temperature=temperature)
                return parse_strict_json(content)
            except JSONParseError as e:
                last_err = e
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"解析失败：{e}。只重新输出合法 JSON；字符串值内部禁止使用英文双引号（改用《》或单引号）。"},
                ]
        raise PipelineAbort(f"{node} JSON 解析重试仍失败: {last_err}")

    def _flush(self) -> None:
        self.run.payload = {**self.run.payload, "trace": self.trace, "cost": self.cost}
        self.db.commit()

    # ---- 门禁 ----

    def run_gates(self, text: str, defs: dict[int, tuple[int, str]], pairs: list,
                  recent_titles: list[str]) -> G.Verdict:
        v = G.Verdict()
        route = self.cfg["route"]
        gc = route["gates"]
        identity = self.cfg["identity"]
        G.gate_length(text, gc.get("length"), v)
        G.gate_fingerprint(text, identity.get("style_rules", {}).get("fingerprint", []),
                           (gc.get("fingerprint") or {}).get("min_hits", 0), v)
        if gc.get("echo_check"):
            G.gate_echo_check(text, identity.get("style_anchor", ""), v)
        if gc.get("copyright"):
            blocks = self.cfg["memory"].get("static_blocks") or []
            G.gate_copyright(text, blocks, (gc.get("copyright") or {}).get("ngram", 8), v)
        td = gc.get("topic_dedup")
        if td:
            recent = recent_titles[: int(td.get("recent_n", 5))]
            G.gate_topic_dedup(self._title(text), recent,
                               float(td.get("threshold", 0.55)), v)
        try:
            validate_citations_pipeline(text, defs, pairs,
                                        (gc.get("citation") or {}).get("min_count", 2))
        except Exception as e:  # CitationError → 门禁 issue
            v.issues.append(str(e))
        v.stats["rhythm_stddev"] = G.rhythm_stddev(text)
        v.passed = not v.issues
        return v

    @staticmethod
    def _title(text: str) -> str:
        for line in text.splitlines():
            s = line.strip().lstrip("#").strip()
            if s:
                return s[:120]
        return "（无题）"

    # ---- 节点 ----

    def node_outline(self, user_ctx: str) -> dict:
        template = self.cfg["route"]["outline"]["template"]
        hints = {
            "pyramid": "金字塔结构：导语先给最硬的事实与结论，以下按重要性递减展开，结尾收束到论点。",
            "variation": "乐章式变奏结构：起（具体小事/场景）→ 承（翻出一层机制）→ 转（反面或追问）→ 合（冷收，不总结）。",
            "sectional": "剖层结构：像解剖一样把议题按层面切开（如表象/机制/人），一层一节递进。",
            "formula": "公式结构：轶事导语 → nut graf（一段说清本文要论证什么）→ 主体展开 → kicker 收尾（回扣导语）。",
        }
        hint = hints.get(template, "")
        messages = [
            {"role": "system", "content": self._system},
            {"role": "user", "content":
                f"{user_ctx}\n\n【任务】先做规划，不写正文。{hint}\n"
                '输出 JSON：{"title":"标题","thesis":"中心论点一句",'
                '"sections":[{"key":"主题词","brief":"要点+计划引用的条目号"}] ×3}；sections 恰好 3 个。'},
        ]
        o = self._call_json("w_outline", messages, temperature=0.7)
        if not o.get("sections") or len(o["sections"]) < 2:
            raise PipelineAbort(f"outline sections 不足: {o.get('sections')}")
        return o

    def node_incubate(self, user_ctx: str) -> dict:
        messages = [
            {"role": "system", "content": self._system},
            {"role": "user", "content":
                f"{user_ctx}\n\n【任务】闭目构思（腹稿）：只输出 JSON："
                '{"theme":"核心之事一句","chain":["追问一层","再追问一层","最深一层"],'
                '"opening_image":"起笔的具体小事","closing_line":"结尾的短句或反问"}'
                "（字符串值内部禁止使用英文双引号）。"},
        ]
        return self._call_json("w_incubate", messages, temperature=0.9)

    def node_draft(self, user_ctx: str, *, incubate: dict | None = None,
                   outline: dict | None = None, section: tuple[int, int] | None = None,
                   prev_sections: list[str] | None = None) -> str:
        task = _draft_task(self.cfg, pairs=self.pairs, incubate=incubate, outline=outline,
                           section=section, prev_sections=prev_sections)
        messages = [
            {"role": "system", "content": self._system},
            {"role": "user", "content": user_ctx + "\n\n" + task},
        ]
        content, _ = self._call("w_draft", messages, temperature=0.9)
        return content.strip()

    def node_pass(self, ptype: str, params: dict, text: str) -> str:
        """修订遍；distort/callback/selfrev 为占位接口（本阶段 passthrough + 记录）。"""
        node = f"w_{ptype}"
        if ptype == "prune":
            lo, hi = (self.cfg["route"]["gates"].get("length") or {}).get("min", 600), \
                     (self.cfg["route"]["gates"].get("length") or {}).get("max", 1400)
            instr = params.get("instruction") or (
                "【任务】删节遍：写作是删节的艺术。逐句审视，竭力将可有可无的字、句、段删去，"
                f"保持事实、脚注标记与结构不变。目标：长度压到 {lo}-{hi} 字"
                f"（当前 {{n}} 字）。只输出删节后全文。").replace("{n}", str(len(G.clean_text(text))))
            messages = [
                {"role": "system", "content": self._system},
                {"role": "user", "content": f"【你的初稿】\n{text}\n\n{instr}"},
            ]
            content, _ = self._call(node, messages, temperature=0.6)
            return content.strip()
        if ptype == "rhythm":
            messages = [
                {"role": "system", "content": self._system},
                {"role": "user", "content": f"【你的初稿】\n{text}\n\n"
                 "【任务】节奏重构遍：调整长短句节奏（短句砸重点，长句铺陈），"
                 "删除可有可无的字句。保持事实、脚注标记与结构不变。只输出修订后全文。"},
            ]
            content, _ = self._call(node, messages, temperature=0.8)
            return content.strip()
        # distort / callback / selfrev：接口占位（任务书 §10：不完整实现，留接口）
        self.trace.append({"node": node, "skipped": f"{ptype} 修订遍为接口占位，本阶段未实现，passthrough"})
        self._flush()
        return text

    def node_revise(self, text: str, feedback: str) -> str:
        messages = [
            {"role": "system", "content": self._system},
            {"role": "user", "content":
                f"【你的稿子】\n{text}\n\n【编辑器检出的问题（必须全部消除）】\n{feedback}\n\n"
                "【要求】保持事实与脚注引用纪律不变（引用编号与定义行完整保留，缺引用则补）；"
                "风格锚与记忆片段的具体文句不得复用；只输出修订后全文。"},
        ]
        content, _ = self._call("w_revise", messages, temperature=0.8)
        return content.strip()

    # ---- 主流程 ----

    def execute(self, *, reading_window: tuple[int, int] | None = None) -> Article | None:
        cfg = self.cfg
        self._system = _identity_system(cfg)

        pairs = list(self.pairs)
        if reading_window:
            off, k = reading_window
            window = pairs[off:off + k]
            if window:
                pairs = window
                self.run.payload = {**self.run.payload, "reading_window": {"offset": off, "k": k}}
        self.pairs = pairs
        if not pairs:
            raise PipelineAbort("阅读集为空（无可写素材），管线不落笔")

        user_ctx = "【本期阅读集】\n" + _refs_listing(pairs)
        user_ctx += _hot_brief(self.db, self.author)
        slices, inj_records = _static_injection(self.db, self.author, cfg, pairs)
        self.run.payload = {**self.run.payload, "static_injection": inj_records}
        position = cfg["memory"]["injection"].get("position") or "head"
        # U 形放置（lab 结论4）：稳定段（风格示范）在前，易变段（上下文）在后
        if slices and position in ("head", "u"):
            head = slices if position == "head" else slices[:1]
            user_ctx = _slices_block(head, "head") + user_ctx
            if position == "u" and len(slices) > 1:
                user_ctx += _slices_block(slices[1:], "tail")
        elif slices:
            user_ctx += _slices_block(slices, "tail")
        recent_n = (cfg["route"]["gates"].get("topic_dedup") or {}).get("recent_n", 5)
        recent = _recent_titles(self.db, self.author, recent_n)
        if recent:
            user_ctx += ("\n\n【近期已写文章标题（选题不得与它们重复）】\n"
                         + "\n".join(f"- 《{t}》" for t in recent))
        # 动态记忆占位符（feedback/topic）
        user_ctx = fill_placeholders(self.db, self.author, user_ctx)

        route = cfg["route"]
        mode = route["draft"]["mode"]

        outline = self.node_outline(user_ctx) if route["outline"]["template"] != "none" else None
        incubate = self.node_incubate(user_ctx) if mode == "incubate" else None

        if mode == "rolling":
            if outline is None:
                outline = self.node_outline(user_ctx)  # rolling 依赖大纲
            secs = outline["sections"][:3]
            lo = ((route["gates"].get("length") or {}).get("min", 600)) // 3
            hi = int(((route["gates"].get("length") or {}).get("max", 1400)) * 0.4)
            sections: list[str] = []
            for i, _sec in enumerate(secs, 1):
                text_i = self.node_draft(user_ctx, outline=outline, section=(i, len(secs)),
                                         prev_sections=sections)
                sections.append(text_i)
            body = "\n\n".join(sections)
            title = outline.get("title") or self._title(body)
            draft_text = f"# {title}\n\n{body}"
        else:  # single / dictate / incubate（腹稿后一次落笔）：全文一次生成
            draft_text = self.node_draft(user_ctx, incubate=incubate)

        # prompt 快照（W4 核验点：静态切片与阅读集在此逐字可核）
        self.run.payload = {**self.run.payload, "trace": self.trace, "cost": self.cost}
        self.run.prompt_snapshot = (
            self._system + "\n\n---USER---\n\n" + user_ctx
            + "\n\n---TASK---\n\n" + _draft_task(cfg, pairs=self.pairs))
        self.db.commit()

        # 修订遍
        for p in route.get("passes", []):
            before = len(G.clean_text(draft_text))
            draft_text = self.node_pass(p["type"], p.get("params") or {}, draft_text)
            self.trace[-1]["pass_stats"] = {
                "chars_before": before, "chars_after": len(G.clean_text(draft_text)),
                "prune_ratio": round(1 - len(G.clean_text(draft_text)) / before, 3) if before else 0.0}

        # 门禁 + 重写（max_attempts 对齐 lab gated_node：含初稿的总尝试数）
        rewrite = route["rewrite"]
        revise_enabled = rewrite["mode"] == "gated_retry" and rewrite.get("on_gate_fail", "revise") == "revise"
        max_attempts = int(rewrite.get("max_attempts", 3))
        attempts = 0
        title = self._title(draft_text)
        defs = parse_footnote_defs(draft_text)
        verdict = self.run_gates(draft_text, defs, self.pairs, recent)
        gate_history = [{"attempt": attempts, "verdict": verdict.to_dict()}]
        while not verdict.passed and revise_enabled and attempts + 1 < max_attempts:
            attempts += 1
            self.trace[-1]["discarded"] = True  # 门禁拒绝的中间稿=废稿，trace 留痕
            draft_text = self.node_revise(draft_text, verdict.feedback())
            title = self._title(draft_text)
            defs = parse_footnote_defs(draft_text)
            verdict = self.run_gates(draft_text, defs, self.pairs, recent)
            gate_history.append({"attempt": attempts, "verdict": verdict.to_dict()})

        self.run.payload = {**self.run.payload, "trace": self.trace, "cost": self.cost,
                            "gate_history": gate_history,
                            "gates_final": verdict.to_dict(),
                            "rewrite": {"mode": rewrite["mode"], "attempts": attempts,
                                        "revise_enabled": revise_enabled},
                            "title": title}
        self.db.commit()

        if not verdict.passed:
            # gated 耗尽或 zero_revision 语义由调用方处理；此处 zero_revision 仍入库
            if revise_enabled:
                self.run.status = "FAILED"
                self.run.error = f"门禁重试耗尽（{attempts} 次）: " + verdict.feedback()[:500]
                self.db.commit()
                return None
            self.run.payload = {**self.run.payload,
                                "audit_note": "zero_revision/record 语义：门禁未过仍入库，违规只记审计工件"}

        defs = {k: (iid, q) for k, (iid, q) in defs.items() if k in
                {int(m.group(1)) for m in FOOTNOTE_MARK_RE.finditer(FOOTNOTE_DEF_RE.sub("", draft_text))}}
        body_final = assemble_article_text(title, draft_text, defs)
        citations = [{"item_id": iid, "quote": q} for _k, (iid, q) in sorted(defs.items())]
        article = Article(author_id=self.author.id, title=title, body=body_final,
                          citations=citations, status="PUBLISHED_TO_C")
        self.db.add(article)
        self.db.commit()
        self.run.decision = "WRITE"
        self.run.article_id = article.id
        self.run.status = "OK"
        self.run.error = None
        self.db.commit()

        from .memory import add_memory
        first_item = citations[0]["item_id"] if citations else None
        add_memory(self.db, self.author, module="topic",
                   content=f"本次写了《{title}》，选题来自阅读集条目 {first_item} 等内容。",
                   source_event="write")
        return article


def run_pipeline_write(
    db: Session,
    author: Author,
    *,
    triggered_by: str = "manual",
    model: str | None = None,
    batch_id: str | None = None,
    reading_window: tuple[int, int] | None = None,
    route_overrides: dict | None = None,
) -> WriteRun:
    """author.json 驱动的写作入口（writer.run_write 对有 JSON 作者的分派目标）。

    route_overrides：批跑对照实验用（如 single 对照），深合并进 route 后重新校验，
    只影响本次执行、不回写 author_json（模型绑定与身份资产分层纪律）。
    """
    cfg = dict(author.author_json or {})
    if route_overrides:
        cfg = {**cfg, "route": {**cfg.get("route", {}), **route_overrides}}
    try:
        cfg = load_author_config(cfg)
    except AuthorConfigError as e:
        run = WriteRun(author_id=author.id, triggered_by=triggered_by,
                       reading_set_item_ids=[], payload={"config_error": str(e)[:1000]},
                       prompt_snapshot="", model=model or author.model, status="FAILED",
                       error="author.json 校验失败")
        db.add(run)
        db.commit()
        return run

    pairs, rank_meta = assemble_ranked_reading_set(db, author)
    run = WriteRun(
        author_id=author.id,
        triggered_by=triggered_by,
        reading_set_item_ids=[item.id for item, _ in pairs],
        payload={"route": {"outline": cfg["route"]["outline"]["template"],
                           "draft": cfg["route"]["draft"]["mode"],
                           "passes": [p["type"] for p in cfg["route"].get("passes", [])],
                           "overrides": route_overrides},
                 "rank": rank_meta,
                 "batch_id": batch_id,
                 "reading_window": reading_window},
        prompt_snapshot="",
        model=model or author.model,
        status="FAILED",
    )
    db.add(run)
    db.commit()

    provider = DeepSeekProvider(db)
    runner = PipelineRunner(db, author, run, cfg, provider)
    try:
        runner.pairs = pairs
        article = runner.execute(reading_window=reading_window)
        _ = article
    except PipelineAbort as e:
        run.status = "FAILED"
        run.error = str(e)
        db.commit()
    except ProviderError as e:
        run.status = "FAILED"
        run.error = f"ProviderError: {e}"
        db.commit()
    return run
