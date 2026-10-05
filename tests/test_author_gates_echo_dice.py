"""锚回显门禁与选题去重相似度的判定语义（正例/反例双面）。

覆盖：回显源只含风格锚的叙事示范段（元指令行/编排注记行/空行不参与比对、
扫描不中断、比对串按空白归一化口径拼接）、长锚含高频常用字时短语级复制仍须
整段检出；选题去重的字符 bigram Dice 在共享二字片的短标题对上命中、单字标题
不产生误判重。
设计依据见 docs/design-index.md「AC-11.2」（门禁拒收语义）、「AC-20.4」（选题
去重拒收留痕）；比对口径沿 app/authors/gates.py 模块说明（lab v3_gate /
v3_echo_source 移植：去脚注+空白归一化、锚回显 ≥20 字符短语级复制）。
"""
import app.authors.gates as G

META_LINE = "【元指令说明行】这一行是编排注记不要照抄复制内容超过二十字"
CONT_LINE = "（续上段）这一行也是编排注记同样不要照抄内容也超过二十字了"
PAREN_LINE = "(注记行)这是半角括号注记同样不要照抄超过二十字以上内容"
NARRATIVE = "他推开那扇锈迹斑斑的铁门，一步一步走进了院子深处。"
ANCHOR = "\n".join([META_LINE, CONT_LINE, PAREN_LINE, "", NARRATIVE])


def test_echo_gate_flags_narrative_copy_and_ignores_meta_lines():
    """叙事示范段被 ≥20 字符短语级复制必须拦下；只复制元指令/编排注记行不得拦；
    空行与元指令行不得中断对后续叙事段的扫描。"""
    # 叙事段复制（位于空行与注记行之后）→ 拦截
    v = G.Verdict()
    G.gate_echo_check("开头。" + NARRATIVE + "结尾。", ANCHOR, v)
    assert v.issues and "回显" in v.issues[0]
    # 三种注记行被逐字复制 → 均不构成回显（比对源只含叙事示范段）
    v2 = G.Verdict()
    G.gate_echo_check("开头。" + META_LINE + "结尾。", ANCHOR, v2)
    assert v2.issues == []
    v3 = G.Verdict()
    G.gate_echo_check("开头。" + CONT_LINE + "结尾。", ANCHOR, v3)
    assert v3.issues == []
    v4 = G.Verdict()
    G.gate_echo_check("开头。" + PAREN_LINE + "结尾。", ANCHOR, v4)
    assert v4.issues == []


def test_echo_gate_detects_multiline_copy_after_whitespace_norm():
    """clean 口径去空白后，相邻两行示范文本被连排复制构成 ≥20 字符连续子串，
    仍须判回显（比对串按空白归一化口径无分隔拼接）。"""
    l1 = "第一行示范文本连续十二字"
    l2 = "第二行示范文本连续十二字"
    v = G.Verdict()
    G.gate_echo_check("开头。" + l1 + l2 + "结尾。", "\n".join([l1, l2]), v)
    assert v.issues


def test_echo_gate_survives_long_anchor_with_common_chars():
    """长锚（≥200 字）内含高频常用字时，跨高频字的 ≥20 字符短语复制仍须整段
    检出——比对器按 lab 口径关闭 junk 启发式，单一复制块不受高频字影响。"""
    phrase = "巷口的早点摊冒着热气，老太太的粥熬得浓稠，赶早的人们排着长队，呵出的气都是白的。"
    filler = ("巷子深处有个修鞋摊，老师傅的手艺是全城最好的，"
              "街坊们都说他修的鞋耐穿，找他的人络绎不绝。")
    anchor = phrase + filler * 4
    assert len(anchor) >= 200
    v = G.Verdict()
    G.gate_echo_check("开头。" + phrase + "结尾。", anchor, v)
    assert v.issues


def test_echo_gate_flags_long_copy_despite_common_char_runs():
    """长锚上含高频字的 ≥20 字符复制段必须检出：即使稿内另有更长的低频字
    公共块与之竞争，最长复制段不得被 junk 启发式吞掉（lab 口径关闭 autojunk
    的语义面：最长公共块按完整块计，高频字不拆块）。"""
    copy_p = "北方的冬天来得早，路上的行人缩着脖子赶路，呵出的气都是白的。"
    rare_run = "青铜巨鼎矗立于苍茫原野尽头千年不倒"
    filler = "田野尽头群山连绵起伏，云层低垂，风声掠过树梢，远处传来隐约的钟声，回荡在山谷之间。"
    anchor = copy_p + rare_run + "山脚下有一条小溪流过村庄，溪水清浅见底，游鱼可数。" + filler * 4
    assert len(anchor) >= 200
    v = G.Verdict()
    G.gate_echo_check("开头。" + copy_p + "中间。" + rare_run + "结尾。", anchor, v)
    assert v.issues


def test_topic_dedup_similar_titles_across_lengths():
    """共享二字片的不同长度标题对须给出 Dice 命中（含 2/3 字短标题——短标题
    同样参与相似度比对，不因长度被短路判不相似）。
    设计依据见 docs/design-index.md「AC-20.4」。"""
    v = G.Verdict()
    G.gate_topic_dedup("白猫黑猫花猫", ["白猫黑狗花猫"], 0.55, v)
    assert v.issues and "过于相似" in v.issues[0]
    v2 = G.Verdict()
    G.gate_topic_dedup("白猫", ["白猫黑"], 0.55, v2)
    assert v2.issues
    v3 = G.Verdict()
    G.gate_topic_dedup("白猫黑", ["白猫"], 0.55, v3)
    assert v3.issues


def test_topic_dedup_short_title_not_false_positive():
    """单字标题与近期标题无可共享二字片，不得误判相似拒收（无比即无相似的
    Dice 语义面；误判重会错误拦下可写选题）。"""
    v = G.Verdict()
    G.gate_topic_dedup("问", ["关于机器写作的三点观察"], 0.55, v)
    assert v.issues == []
