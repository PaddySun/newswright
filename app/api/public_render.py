"""公开页 Markdown 白名单渲染器（纯逻辑，无 DB/IO 依赖）。

安全模型（转义-白名单双层，设计依据见 docs/design-index.md「ADR-7」）：
第一层先把整篇源文本做 HTML 转义——任何内嵌的 ``<script>``/``<img onerror>``
等标记在此刻失去标记语义，只剩字面字符；第二层只把白名单内的 Markdown 语法
（标题/强调/行内代码/围栏代码/引用块/链接/有序无序列表/表格/段落/脚注）重新
组装为受控标签，标签名与属性全部由本模块字面生成、不接受源文本注入。两层
缺一不可：只转义则页面无排版，只白名单则逃逸序列有注入面。

脚注转链接：正文 ``[^n]`` 引用位转为指向文末引用区的锚链接；引用区条目在
citations 映射提供原文 URL 时整体链接到原文（AC-12.1 一键跳转语义）。

SPA 客户端渲染器（app/static/app/）与本模块实现同一套语法白名单与转义次序，
规则以本文件为服务端权威版本。
"""
from __future__ import annotations

import html
import re

# 脚注引用位（[^1]）与脚注定义行（[^1]: 文本）；K 允许字母数字，[^nK] 同形
_FOOTNOTE_REF = re.compile(r"\[\^([0-9a-zA-Z]+)\]")
_FOOTNOTE_DEF = re.compile(r"^\[\^([0-9a-zA-Z]+)\]:\s*(.*)$")
# 链接 URL 只放行 http(s) 与站内相对路径，防 javascript:/data: 注释面
_SAFE_URL = re.compile(r"^(https?://|/)", re.IGNORECASE)


def first_sentence(text: str, max_chars: int = 120) -> str:
    """原文首句截取（模式 B 降深摘要——非 AI 生成）。

    以中英文句终符（。！？；）切第一句并保留句终符；无句终符或首句超长时
    按 max_chars 硬截断加省略号。空白归一后返回。
    """
    normalized = " ".join((text or "").split())
    if not normalized:
        return ""
    pieces = re.split(r"([。！？；!?])", normalized, maxsplit=2)
    cut = pieces[0]
    if len(pieces) > 1 and pieces[1]:
        cut += pieces[1]  # 保留句终符
    cut = cut.strip()
    if not cut:
        cut = normalized
    if len(cut) > max_chars:
        return cut[:max_chars].rstrip() + "…"
    return cut


def _link_markup(url_escaped: str, label_escaped: str) -> str:
    """安全链接的受控标记：外链新窗打开并切断反向引用；不安全 scheme 拒绝
    转链接（退化为纯文本，永不产生活动面）。URL 中的引号做百分号编码——
    源文本已按 quote=False 转义，引号仍是字面量，不编码可破出 href 属性。"""
    if _SAFE_URL.match(url_escaped.replace("&amp;", "&")):
        href = url_escaped.replace('"', "%22")
        return (f'<a href="{href}" target="_blank" '
                f'rel="noopener noreferrer nofollow">{label_escaped}</a>')
    return label_escaped


def _inline(markup_escaped: str) -> str:
    """行内语法白名单（输入已整篇转义）：行内代码 → 强调 → 链接。
    行内代码最先处理，代码内容不再参与后续语法（防代码内记号被二次展开）。"""
    markup_escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", markup_escaped)
    markup_escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", markup_escaped)
    markup_escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", markup_escaped)
    markup_escaped = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda m: _link_markup(m.group(2), m.group(1)),
        markup_escaped,
    )
    return markup_escaped


def _footnote_refs(line: str) -> str:
    """正文脚注引用位 → 上标锚链接（跳文末引用区）。"""
    return _FOOTNOTE_REF.sub(
        lambda m: f'<sup class="fn-ref"><a href="#fn-{m.group(1)}">{m.group(1)}</a></sup>',
        line,
    )


def render_markdown_whitelist(source: str,
                              citations: list[dict] | None = None) -> str:
    """Markdown 白名单渲染主入口：返回可信 HTML 片段（模板侧 |safe）。

    citations 为文章的结构化引用（[{item_id, quote}]，可选附 url）：序号与
    正文 [^n] 按出现顺序对应；提供 url 的条目渲染为指向原文的链接。
    """
    citations = citations or []
    citation_urls = [str(c.get("url") or "") for c in citations]
    lines = html.escape(source or "", quote=False).split("\n")

    out: list[str] = []
    footnote_definitions: list[tuple[str, str]] = []
    paragraph: list[str] = []
    list_stack: list[str] = []  # 元素为 "ul" | "ol"
    in_code_fence = False
    code_lines: list[str] = []
    code_lang = ""
    table_buffer: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            joined = "<br>".join(_footnote_refs(_inline(p)) for p in paragraph)
            out.append(f"<p>{joined}</p>")
            paragraph.clear()

    def flush_table() -> None:
        nonlocal table_buffer
        rows = [ln for ln in table_buffer if not re.match(r"^\|[\s:|-]+\|$", ln.strip())]
        if len(rows) >= 1:
            cells = lambda ln: [c.strip() for c in ln.strip().strip("|").split("|")]
            head = "".join(f"<th>{_inline(c)}</th>" for c in cells(rows[0]))
            body_rows = [
                "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells(r)) + "</tr>"
                for r in rows[1:]
            ]
            out.append(
                "<table><thead><tr>" + head + "</tr></thead><tbody>"
                + "".join(body_rows) + "</tbody></table>"
            )
        table_buffer = []

    def close_list() -> None:
        while list_stack:
            out.append(f"</{list_stack.pop()}>")

    for raw in lines:
        line = raw.rstrip()

        if in_code_fence:
            if re.match(r"^```\s*$", line):
                lang = html.escape(code_lang)
                code = "\n".join(code_lines)
                out.append(
                    f"<pre><code class=\"language-{lang}\">{code}</code></pre>"
                )
                in_code_fence = False
                code_lines = []
                code_lang = ""
            else:
                code_lines.append(line)
            continue

        fence = re.match(r"^```([0-9a-zA-Z+-]*)\s*$", line)
        if fence:
            flush_paragraph()
            close_list()
            flush_table()
            in_code_fence = True
            code_lang = fence.group(1)
            continue

        if line.strip().startswith("|") and line.strip().endswith("|"):
            flush_paragraph()
            close_list()
            table_buffer.append(line)
            continue
        if table_buffer:
            flush_table()

        footnote = _FOOTNOTE_DEF.match(line.strip())
        if footnote:
            flush_paragraph()
            close_list()
            footnote_definitions.append((footnote.group(1), footnote.group(2)))
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            text = _footnote_refs(_inline(heading.group(2)))
            out.append(f"<h{level}>{text}</h{level}>")
            continue

        if re.match(r"^>\s?", line):
            flush_paragraph()
            close_list()
            quote = _footnote_refs(_inline(re.sub(r"^>\s?", "", line)))
            if out and out[-1].startswith("<blockquote>"):
                out[-1] = out[-1][:-13] + f"<p>{quote}</p></blockquote>"
            else:
                out.append(f"<blockquote><p>{quote}</p></blockquote>")
            continue

        unordered = re.match(r"^[-*]\s+(.*)$", line)
        ordered = re.match(r"^\d+[.、]\s+(.*)$", line)
        if unordered or ordered:
            flush_paragraph()
            want = "ul" if unordered else "ol"
            if not list_stack or list_stack[-1] != want:
                close_list()
                list_stack.append(want)
                out.append(f"<{want}>")
            out.append(f"<li>{_footnote_refs(_inline((unordered or ordered).group(1)))}</li>")
            continue

        if not line.strip():
            flush_paragraph()
            close_list()
            continue

        if list_stack:
            # 列表项的续行并入上一列表项（软换行）
            out[-1] = out[-1][:-4] + _footnote_refs(_inline(line.strip())) + "</li>"
            continue
        paragraph.append(line.strip())

    flush_paragraph()
    close_list()
    flush_table()

    if footnote_definitions:
        items = []
        for idx, (key, text) in enumerate(footnote_definitions, start=1):
            body = _footnote_refs(_inline(text))
            url = citation_urls[idx - 1] if idx - 1 < len(citation_urls) else ""
            if url and _SAFE_URL.match(url):
                href = html.escape(url, quote=True)
                body += (f' <a class="fn-source" href="{href}" target="_blank" '
                         f'rel="noopener noreferrer nofollow">原文</a>')
            items.append(f'<li id="fn-{key}">{body}</li>')
        out.append('<section class="footnotes"><ol>' + "".join(items) + "</ol></section>")

    return "\n".join(out)
