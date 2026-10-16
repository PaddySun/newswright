"""行内语法白名单与首句摘要契约测试（C5-1 变异分诊批：
_inline / _link_markup / first_sentence 面）。

覆盖口径（设计依据见 docs/design-index.md「ADR-7」「AC-16.1」）：
- 行内语法表：行内代码/斜体强调/粗体（标签由渲染器字面生成——结构在即过，
  大小写/包裹文本变体不在射程）；链接 label 取源文本、URL 引号百分号编码
  （不破出 href 属性）；
- 首句摘要（模式 B 降深——原文截取一句话，非 AI 生成）：句终符保留、
  空白归一、空文本回空、超长截断加省略号、纯句终符文本可用。
"""
import re

from app.api.public_render import first_sentence, render_markdown_whitelist


def test_inline_code_em_strong_syntax_table():
    """行内语法表三件：`代码`→code、*强调*→em、**粗体**→strong
    （语法白名单成员逐一受控转标签——记号不残留字面）。"""
    html = render_markdown_whitelist("段落 `代码` 与 *强调* 与 **粗体**。").lower()
    assert "<code>代码</code>" in html
    assert "<em>强调</em>" in html
    assert "<strong>粗体</strong>" in html
    assert "`代码`" not in html  # 行内代码记号被消费
    assert "*强调*" not in html


def test_inline_link_label_from_source_text():
    """链接 label 取源文本方括号内容（不得退化为 None 或 URL 本身——
    受控标记的可见文本面）。"""
    html = render_markdown_whitelist("[标签字](https://e.example/x)")
    assert 'href="https://e.example/x"' in html
    assert ">标签字</a>" in html


def test_inline_link_quote_percent_encoded_in_href():
    """链接 URL 含引号时百分号编码：href 属性值必须含引号编码（%22），
    不得字面残留（破出 href 属性即注入面——URL 引号编码是白名单安全行为）。"""
    html = render_markdown_whitelist('[x](https://e.example/a"b)')
    m = re.search(r'href="([^"]*)"', html)
    assert m is not None
    assert "%22" in m.group(1)


def test_first_sentence_keeps_terminal_punctuation():
    """首句保留句终符：切出的第一句连句终符一起返回（摘要=完整一句话）。"""
    assert first_sentence("第一句。第二句。") == "第一句。"


def test_first_sentence_normalizes_whitespace():
    """空白归一：多空白/制表折叠为单空格（归一语义钉死输出形态）。"""
    assert first_sentence("多  空白\t文本。") == "多 空白 文本。"


def test_first_sentence_empty_text_returns_empty():
    """空文本/None 返回空串（空原文→空摘要，不产出占位垃圾）。"""
    assert first_sentence("") == ""
    assert first_sentence(None) == ""


def test_first_sentence_truncates_long_text_with_ellipsis():
    """超长首句硬截断加省略号：截断确实发生且保留段是原文前缀。"""
    text = "长" * 130
    out = first_sentence(text)
    assert "…" in out
    assert len(out) < len(text)
    assert text.startswith(out.split("…")[0][:100])


def test_first_sentence_punctuation_only_text_usable():
    """纯句终符文本不崩溃且首句即句终符本身（切句路径对合法文本可用）。"""
    assert first_sentence("。") == "。"
