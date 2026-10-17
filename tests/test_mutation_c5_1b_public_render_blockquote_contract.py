"""引用块渲染契约测试（引用块可达性修复批：blockquote 语法面）。

覆盖口径（Markdown 白名单渲染器的引用块语法，设计依据见
docs/design-index.md「ADR-7」与「PR-1 整篇转义先行的行首标记匹配」）：
- 引用块可达：行首 > 标记经整篇 HTML 转义后为 &gt; 形态，判定与内容剥离
  均按转义后形态做前缀容忍匹配（> / &gt; 双形态），剥离后内容进
  <blockquote> 包裹段落；
- 连续引用行合并为单个 blockquote（与 SPA 客户端渲染器同规则）；
- 引用内容内行内语法（强调）与脚注引用位照常生效（处理链复用）；
- 引用内容保持转义语义（内嵌 <script> 仍为转义文本——安全不回退）；
- 嵌套 >> 行保持单层剥离现状（白名单未定义嵌套引用层级，不新增语义）。

断言两档说明：标签结构断言先小写化（HTML 标签大小写不敏感，语法功能在
即过——措辞/形态变体不在本文件射程）；内容与安全断言按语义档精确。
"""
from app.api.public_render import render_markdown_whitelist


def test_blockquote_line_renders_wrapped_and_marker_stripped():
    """引用块可达：行首 > 标记的行渲染为 blockquote 包裹段落，标记本身
    剥离不进内容（含标记后单个空格的消费）。"""
    html = render_markdown_whitelist("> 引文一句").lower()
    assert html.count("<blockquote>") == 1
    assert "<p>引文一句</p>" in html
    assert "&gt;" not in html  # 标记（转义形态）不残留进引用内容


def test_blockquote_marker_without_space_also_renders():
    """标记后无空格（>引文）同样是引用块：标记后的空白为可选消费，
    剥离后内容以引文起头。"""
    html = render_markdown_whitelist(">引文无空格").lower()
    assert "<blockquote>" in html
    assert "<p>引文无空格</p>" in html


def test_consecutive_blockquote_lines_merge_into_single_quote_block():
    """连续引用行合并为单个 blockquote（两段引用内容共用一个包裹——
    与列表连续条目合并同构）。"""
    html = render_markdown_whitelist("> 引甲行\n> 引乙行").lower()
    assert html.count("<blockquote>") == 1
    assert "<p>引甲行</p>" in html and "<p>引乙行</p>" in html


def test_blockquote_followed_by_paragraph_renders_both():
    """引用块后的正文正常渲染（引用行处理不终止整篇渲染）。"""
    html = render_markdown_whitelist("> 引文。\n\n引用块后段落。").lower()
    assert "<blockquote>" in html
    assert "<p>引用块后段落。</p>" in html


def test_inline_and_footnote_refs_active_inside_blockquote():
    """引用内容内行内语法与脚注引用位照常生效（强调标签与脚注锚链接
    在 blockquote 内产出——行内/脚注处理链复用，不因引用块短路）。"""
    html = render_markdown_whitelist("> 引文**强调**与[^1]").lower()
    assert "<blockquote>" in html
    assert "<strong>强调</strong>" in html
    assert 'class="fn-ref"' in html and 'href="#fn-1"' in html


def test_blockquote_content_keeps_escape_safety():
    """引用内容保持转义语义：内嵌 <script> 在引用内仍是转义文本
    （安全不回退——白名单渲染器的第一层整篇转义不被引用块语法绕开）。"""
    html = render_markdown_whitelist("> 引<script>alert(1)</script>文")
    assert "<script>" not in html.lower()
    assert "&lt;script&gt;" in html


def test_nested_marker_keeps_single_layer_strip():
    """嵌套 >> 行保持单层剥离现状：剥一层标记后剩余 &gt; 以转义文本
    进引用内容（白名单未定义嵌套引用层级语义）。"""
    html = render_markdown_whitelist(">> 嵌套引文").lower()
    assert html.count("<blockquote>") == 1
    assert "<p>&gt; 嵌套引文</p>" in html
