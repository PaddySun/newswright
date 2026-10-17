"""白名单渲染器契约测试（C5-1 变异分诊批：render_markdown_whitelist 面）。

覆盖口径（Markdown 白名单渲染主入口的语法表与安全面，设计依据见
docs/design-index.md「ADR-7」「AC-12.1」）：
- 脚注区引用条目按序对位补原文链接（citations 序号 ↔ 正文 [^n] 出现顺序）；
- 引用 URL 只放行 http(s)/站内相对（javascript: 等不安全 scheme 拒转链接），
  URL 中引号做属性安全编码（不破出 href 属性）；
- 语法白名单表逐块：表格（表头/数据行/分隔行滤除/列切分/单行表/连表）、
  围栏代码（内容保真/闭合/块后内容/无语言围栏/连块）、有序无序列表
  （类型区分/连续合并/内容剥标记）、脚注区文本保真。

断言两档说明：标签结构断言先小写化（HTML 标签大小写不敏感，语法功能在
即过——措辞/形态变体不在本文件射程）；内容与安全断言按语义档精确。

注：引用块（> 前缀）语法不属本文件射程——其行首标记在整篇转义后须按
&gt; 形态匹配的可达性契约由引用块契约测试文件覆盖
（tests/test_mutation_c5_1b_public_render_blockquote_contract.py）。
"""
from app.api.public_render import render_markdown_whitelist


def test_citation_source_links_align_with_footnote_order():
    """脚注区原文链接按出现顺序对位：第 n 个脚注定义接 citations 第 n 条的
    URL（AC-12.1 一键跳转语义——序号与正文 [^n] 按出现顺序对应）。"""
    html = render_markdown_whitelist(
        "正文引用[^1]，再引[^2]。\n\n[^1]: 引文一\n[^2]: 引文二",
        citations=[
            {"item_id": 101, "quote": "q1", "url": "https://one.example/x"},
            {"item_id": 102, "quote": "q2", "url": "https://two.example/y"},
        ],
    )
    assert 'href="https://one.example/x"' in html
    assert 'href="https://two.example/y"' in html
    assert html.count('class="fn-source"') == 2  # 恰好等长：末位脚注不丢链接
    # 对位序：第一个脚注条目只接第一个 URL（错位/越界兜底均破坏对应关系）
    first_item = html.split('id="fn-1"')[1].split("</li>")[0]
    assert 'href="https://one.example/x"' in first_item
    assert 'href="https://two.example/y"' not in first_item


def test_citation_source_link_rejects_unsafe_scheme():
    """不安全 scheme 的引用 URL 拒转链接（javascript: 永不产生活动面——
    链接 URL 白名单 _SAFE_URL 只放行 http(s) 与站内相对路径）。"""
    html = render_markdown_whitelist(
        "正文[^1]。\n\n[^1]: 引文",
        citations=[{"item_id": 1, "quote": "q",
                    "url": "javascript:alert(1)"}],
    )
    assert "fn-source" not in html
    assert "javascript:" not in html
    assert "引文" in html  # 条目本体保留，仅链接被拒


def test_citation_source_link_escapes_quotes_in_href():
    """引用 URL 含引号时属性安全编码：href 属性值中不得出现字面双引号
    （脚注区 href 走 html.escape(quote=True)——破出属性即注入面）。"""
    html = render_markdown_whitelist(
        "正文[^1]。\n\n[^1]: 引文",
        citations=[{"item_id": 1, "quote": "q",
                    "url": 'https://example.com/a"b'}],
    )
    assert 'class="fn-source"' in html
    href = html.split('fn-source" href="', 1)[1].split('"', 1)[0]
    assert '"' not in href
    assert "&quot;" in href


def test_table_renders_header_cells_and_filters_separator_row():
    """表格语法：首行为表头、数据行全量呈现、分隔行滤除、按竖线切列
    （白名单语法表「表格」——标签与列结构由渲染器字面生成）。"""
    html = render_markdown_whitelist(
        "|甲|乙|\n|---|---|\n|一|二|\n|三|四|").lower()
    assert "<table>" in html and "</table>" in html
    assert "<th>甲</th>" in html and "<th>乙</th>" in html
    assert "<td>一</td>" in html and "<td>三</td>" in html
    assert ">---<" not in html  # 分隔行不进输出
    assert "<th></th>" not in html and "<td></td>" not in html  # 首尾无空单元格


def test_table_with_header_only_still_renders():
    """单数据行表（头+分隔行）也渲染——行数守卫不得把合法最小表吞掉。"""
    html = render_markdown_whitelist("|甲|\n|---|").lower()
    assert "<th>甲</th>" in html


def test_two_tables_both_render():
    """两个表格先后渲染均可用（表格缓冲在 flush 后正确复位）。"""
    html = render_markdown_whitelist(
        "|甲|\n|---|\n\n间隔段落。\n\n|乙|\n|---|").lower()
    assert html.count("<table>") == 2
    assert "<th>甲</th>" in html and "<th>乙</th>" in html
    assert "间隔段落" in html


def test_code_fence_preserves_content_and_closes():
    """围栏代码：内容逐字保真（含换行）、闭栏后正文正常渲染
    （白名单语法表「围栏代码」——代码内容不被改写）。"""
    html = render_markdown_whitelist(
        "```python\ncode 一行\ncode 二行\n```\n\n闭栏后段落。").lower()
    assert "<pre><code" in html
    assert "code 一行\ncode 二行" in html
    assert "<p>闭栏后段落。</p>" in html


def test_code_fence_without_language_renders():
    """无语言围栏：可开可闭、内容保真（语言标注缺席不是崩溃理由）。"""
    html = render_markdown_whitelist("```\n裸代码\n```\n\n后续段落。").lower()
    assert "<pre><code" in html
    assert "裸代码" in html
    assert "<p>后续段落。</p>" in html


def test_two_code_fences_both_render():
    """两个围栏代码块先后渲染均可用（围栏状态在闭栏后正确复位）。"""
    html = render_markdown_whitelist(
        "```python\n第一块\n```\n\n间隔段落。\n\n```js\n第二块\n```").lower()
    assert html.count("<pre><code") == 2
    assert "第一块" in html and "第二块" in html
    assert "间隔段落" in html


def test_unordered_list_items_merge_into_single_list():
    """无序列表：连续条目合并为单个 <ul>、条目内容剥除列表标记、
    列表后段落正常（白名单语法表「有序无序列表」）。"""
    html = render_markdown_whitelist("- 甲\n- 乙\n\n列表后段落。").lower()
    assert html.count("<ul>") == 1
    assert ">甲<" in html and ">乙<" in html  # 条目内容进 li（剥标记后）
    assert "- 甲" not in html and "- 乙" not in html  # 列表标记不进内容
    assert "<p>列表后段落。</p>" in html


def test_list_continuation_line_appends_to_previous_item():
    """列表续行并入上一列表项（软换行）：两项列表后续行并入最后一项、
    前项完整保留、列表结构与续行后正文正常（白名单语法「有序无序列表」）。"""
    import re as _re

    html = render_markdown_whitelist(
        "- 甲\n- 乙\n续行文本。\n\n尾段。").lower()
    assert "<ul>" in html  # 列表结构保留
    items = _re.findall(r"<li>(.*?)</li>", html, _re.DOTALL)
    # 续行并入上一（最近）列表项：乙项含续行文本
    assert any("乙" in item and "续行文本" in item for item in items)
    # 前项不被续行错并（甲项独立完整）
    assert any("甲" in item and "续行文本" not in item for item in items)
    assert "<p>尾段。</p>" in html


def test_ordered_list_renders_ol_tag():
    """有序列表渲染 <ol>（数字前缀条目不得落入无序 <ul>——类型区分：
    有序条目必须产出 ol 标签，恒走 ul 分支即类型混淆）。"""
    html = render_markdown_whitelist("1. 第一项\n2. 第二项").lower()
    assert "<ol>" in html and "</ol>" in html
    assert ">第一项<" in html


def test_footnote_section_preserves_definition_text():
    """脚注区条目保真：定义行文本完整进入引用区（有原文链接时文本与
    链接并存，不得互相覆盖——AC-12.1 引用可溯源）。"""
    html = render_markdown_whitelist(
        "正文[^1]。\n\n[^1]: 引文内容原样",
        citations=[{"item_id": 1, "quote": "q", "url": "https://e.example/z"}])
    assert 'id="fn-1"' in html
    assert "引文内容原样" in html
    assert 'href="https://e.example/z"' in html
