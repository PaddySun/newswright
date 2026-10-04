"""C1-6 分诊批次 8a：authors.schema 五域验证器 + 入口/缺省 C 类闭合测试。

> 追溯注记：本文件原名 tests/test_mutation_c1_6.py（原批次代号见文件名），按对象重命名于 F1⑫治理批。

裁决面：产品书 US-10 AC-10.1（校验失败信息**含字段路径**、**一次报全不短路**）/
AC-10.2（模型不在 JSON）；docs/author-json-schema.md 字段总表（顶层/identity/
route/memory/output 各键的必填✓、类型、枚举、unit:"chars"、format=markdown、
draft.params.max_tokens 默认 4000、rewrite.max_attempts int(1-10)、偏离记录 2/4）
+ schema 头部版本 `2026-09-29-a`；技术书 v1.7 §4.1 author 行、§5
AUTHOR_JSON_INVALID 行；模块 docstring（缺字段/类型错/非法枚举全部报错、
无错返回空列表、校验返回全部错误不短路）。

断言纪律：设计书钉死「报哪些字段（路径）、判定结果、是否一次报全」——断言
错误前缀（字段路径）与错误存在性/崩溃；**不钉措辞**（缺失/类型/枚举文案本体、
XX 包裹、实得类型回显均未钉）；**不钉未钉数值**（length 600/1400、ngram 界外、
recent_n/max_chars 等数值边界无条款——沿 C1-5a「数值缺省无条款」先例）。
"""
import pytest

from app.authors.schema import (
    AuthorConfigError,
    default_author_config,
    load_author_config,
    validate_author_json,
)

GATE_KEYS = ("length", "fingerprint", "echo_check", "citation", "copyright",
             "topic_dedup", "custom")


def base():
    return default_author_config("t1", "测试作者")


def only(errors, keyword):
    """含 keyword 的错误子集（用于「该域无其他错误」断言）。"""
    return [e for e in errors if keyword in e]


# ---------------- 顶层与入口（AC-10.1 含字段路径 / docs 顶层字段总表） ----------------

def test_root_top_level_sections_report_path():
    # docs 顶层表：id/template/identity/route/memory/output/version 全部必填✓；
    # AC-10.1：报错含字段路径（顶层约定前缀 (root)，既有 M14 测试已钉 (root) 形态）
    for key in ("id", "template", "identity", "route", "memory", "output", "version"):
        cfg = base()
        del cfg[key]
        errors = validate_author_json(cfg)
        assert any(e.startswith(f"(root).{key}") for e in errors), (key, errors)


def test_root_id_rejects_non_string_and_blank():
    # docs 顶层表：id string 必填（必须为非空字符串语义）
    cfg = base()
    cfg["id"] = 123
    assert any(e.startswith("(root).id") for e in validate_author_json(cfg))
    cfg = base()
    cfg["id"] = "   "
    assert any(e.startswith("(root).id") for e in validate_author_json(cfg))


def test_root_sections_reject_non_dict():
    # docs 顶层表：identity/route/memory/output 均 object 必填✓
    for key in ("identity", "route", "memory", "output"):
        cfg = base()
        cfg[key] = "garbage"
        errors = validate_author_json(cfg)
        assert any(e.startswith(f"(root).{key}") for e in errors), (key, errors)


def test_template_enum_lab_prefix_and_missing():
    # docs 顶层表 template：single|custom|lab:<人格>；偏离记录：lab 前缀形合法
    cfg = base()
    cfg["template"] = "quantum"
    assert any(e.startswith("(root).template") for e in validate_author_json(cfg))
    cfg = base()
    del cfg["template"]
    assert any(e.startswith("(root).template") for e in validate_author_json(cfg))
    cfg = base()
    cfg["template"] = "lab:测试人格"
    assert validate_author_json(cfg) == []


# ---------------- identity（docs identity 字段总表） ----------------

def test_identity_string_fields_type_paths():
    # docs identity 表：description/personality/values_stance/scenario/style_anchor
    # 均 string 必填✓
    for key in ("description", "personality", "values_stance", "scenario", "style_anchor"):
        cfg = base()
        cfg["identity"][key] = 123
        errors = validate_author_json(cfg)
        assert any(e.startswith(f"identity.{key}") for e in errors), (key, errors)


def test_identity_style_rules_required_keys():
    # docs identity 表：style_rules 必填✓（object），其 do/dont/fingerprint 均 string[] 必填✓
    cfg = base()
    del cfg["identity"]["style_rules"]
    assert any(e.startswith("identity.style_rules") for e in validate_author_json(cfg))
    cfg = base()
    cfg["identity"]["style_rules"] = {}
    errors = validate_author_json(cfg)
    for key in ("do", "dont", "fingerprint"):
        assert any(e.startswith(f"identity.style_rules.{key}") for e in errors), (key, errors)


def test_identity_style_rules_str_list_type():
    # docs identity 表：do/dont/fingerprint = string[]
    for key in ("do", "dont", "fingerprint"):
        cfg = base()
        cfg["identity"]["style_rules"][key] = "not-a-list"
        errors = validate_author_json(cfg)
        assert any(e.startswith(f"identity.style_rules.{key}") for e in errors), (key, errors)
        cfg = base()
        cfg["identity"]["style_rules"][key] = [1, 2]
        errors = validate_author_json(cfg)
        assert any(e.startswith(f"identity.style_rules.{key}") for e in errors), (key, errors)


def test_identity_extra_checks_object_type():
    # docs identity 表：style_rules.extra_checks object（可选）——类型错仍须报
    cfg = base()
    cfg["identity"]["style_rules"]["extra_checks"] = "not-a-dict"
    errors = validate_author_json(cfg)
    assert any(e.startswith("identity.style_rules.extra_checks") for e in errors)


def test_identity_quotes_original():
    # docs identity 表：quotes_original string[] 必填✓
    cfg = base()
    del cfg["identity"]["quotes_original"]
    assert any(e.startswith("identity.quotes_original") for e in validate_author_json(cfg))
    cfg = base()
    cfg["identity"]["quotes_original"] = "not-a-list"
    assert any(e.startswith("identity.quotes_original") for e in validate_author_json(cfg))


def test_identity_provenance():
    # docs identity 表：provenance string[] 必填✓（来源标注）
    cfg = base()
    del cfg["identity"]["provenance"]
    assert any(e.startswith("identity.provenance") for e in validate_author_json(cfg))
    for bad in ("not-a-list", [1, 2]):
        cfg = base()
        cfg["identity"]["provenance"] = bad
        errors = validate_author_json(cfg)
        assert any(e.startswith("identity.provenance") for e in errors), (bad, errors)


# ---------------- output（docs output 字段总表） ----------------

def test_output_format_markdown_only():
    # docs output 表 + 偏离记录4：format 本阶段仅 markdown；必填✓
    cfg = base()
    cfg["output"]["format"] = "html"
    assert any(e.startswith("output.format") for e in validate_author_json(cfg))
    cfg = base()
    del cfg["output"]["format"]
    assert any(e.startswith("output.format") for e in validate_author_json(cfg))


def test_output_footnote_citations_bool():
    # docs output 表：footnote_citations bool 必填✓
    cfg = base()
    cfg["output"]["footnote_citations"] = "yes"
    assert any(e.startswith("output.footnote_citations") for e in validate_author_json(cfg))
    cfg = base()
    del cfg["output"]["footnote_citations"]
    assert any(e.startswith("output.footnote_citations") for e in validate_author_json(cfg))


def test_output_max_tokens_per_node_int_values():
    # docs output 表：max_tokens_per_node object（可选），调用点→max_tokens（int 覆写）
    cfg = base()
    cfg["output"]["max_tokens_per_node"] = {"w_draft": "many"}
    errors = validate_author_json(cfg)
    assert any(e.startswith("output.max_tokens_per_node") for e in errors)
    cfg = base()
    cfg["output"]["max_tokens_per_node"] = "not-a-dict"
    errors = validate_author_json(cfg)
    assert any(e.startswith("output.max_tokens_per_node") for e in errors)
    cfg = base()
    assert only(validate_author_json(cfg), "max_tokens_per_node") == []


# ---------------- memory（docs memory 字段总表） ----------------

def test_memory_static_blocks_structure():
    # docs memory 表：static_blocks array 必填✓；块元素为 object
    cfg = base()
    del cfg["memory"]["static_blocks"]
    assert any(e.startswith("memory.static_blocks") for e in validate_author_json(cfg))
    cfg = base()
    cfg["memory"]["static_blocks"] = "not-a-list"
    assert any(e.startswith("memory.static_blocks") for e in validate_author_json(cfg))
    # 两个非 object 块：一次报全不短路（AC-10.1）——两块的错误都要报
    cfg = base()
    cfg["memory"]["static_blocks"] = [1, 2]
    errors = validate_author_json(cfg)
    assert any(e.startswith("memory.static_blocks[0]") for e in errors)
    assert any(e.startswith("memory.static_blocks[1]") for e in errors)


def test_memory_static_block_fields():
    # docs memory 表：块 = {id, text(逐字原文), source(定位), injection:{max_chars}}，
    # id/text/source 均 string 必填
    blk = {"id": "s1", "text": "x", "source": "tests", "injection": {"max_chars": 100}}
    for key in ("id", "text", "source"):
        cfg = base()
        bad = dict(blk)
        del bad[key]
        cfg["memory"]["static_blocks"] = [bad]
        errors = validate_author_json(cfg)
        assert any(e.startswith(f"memory.static_blocks[0].{key}") for e in errors), (key, errors)


def test_memory_block_duplicate_id_reported_at_second_block():
    # docs memory 表 static_blocks.id 块关联键 + 模块 docstring 无错返回空列表：
    # 重复 id 须报在第二块上（路径可核）
    blk = {"id": "dup1", "text": "x", "source": "tests", "injection": {"max_chars": 100}}
    cfg = base()
    cfg["memory"]["static_blocks"] = [blk, dict(blk)]
    errors = validate_author_json(cfg)
    assert any(e.startswith("memory.static_blocks[1].id") for e in errors)


def test_memory_block_missing_id_no_false_duplicate():
    # 模块 docstring：无错返回空列表/报该报的——缺 id 块不得把后续块的合法 id
    # 误判为重复（等价守护：seen 集合哨兵值不得与合法 id 撞车）
    no_id = {"text": "x", "source": "tests", "injection": {"max_chars": 100}}
    ok = {"id": "XXXX", "text": "x", "source": "tests", "injection": {"max_chars": 100}}
    cfg = base()
    cfg["memory"]["static_blocks"] = [no_id, ok]
    errors = validate_author_json(cfg)
    assert only(errors, "重复的块 id") == []
    assert any(e.startswith("memory.static_blocks[0].id") for e in errors)


def test_memory_block_injection():
    # docs memory 表：块 injection {max_chars} 必填
    blk = {"id": "s1", "text": "x", "source": "tests"}
    cfg = base()
    cfg["memory"]["static_blocks"] = [blk]
    assert any(e.startswith("memory.static_blocks[0].injection")
               for e in validate_author_json(cfg))
    cfg = base()
    cfg["memory"]["static_blocks"] = [dict(blk, injection={})]
    errors = validate_author_json(cfg)
    assert any(e.startswith("memory.static_blocks[0].injection.max_chars") for e in errors)
    # max_chars 类型错须报（数值边界无条款不钉；类型是 docs 钉面）
    cfg = base()
    cfg["memory"]["static_blocks"] = [dict(blk, injection={"max_chars": "lots"})]
    errors = validate_author_json(cfg)
    assert any(e.startswith("memory.static_blocks[0].injection.max_chars") for e in errors)


def test_memory_injection_section():
    # docs memory 表：injection 必填✓；max_slices_per_run/per_block_max_chars int✓；
    # selection ∈ round_robin|recency|relevant；position ∈ head|tail|u（偏离记录）
    cfg = base()
    del cfg["memory"]["injection"]
    assert any(e.startswith("memory.injection") for e in validate_author_json(cfg))
    cfg = base()
    cfg["memory"]["injection"]["max_slices_per_run"] = "ten"
    assert any(e.startswith("memory.injection.max_slices_per_run")
               for e in validate_author_json(cfg))
    cfg = base()
    del cfg["memory"]["injection"]["per_block_max_chars"]
    assert any(e.startswith("memory.injection.per_block_max_chars")
               for e in validate_author_json(cfg))
    cfg = base()
    cfg["memory"]["injection"]["selection"] = "random"
    errors = validate_author_json(cfg)
    assert any(e.startswith("memory.injection.selection") for e in errors)
    cfg = base()
    cfg["memory"]["injection"]["position"] = "middle"
    errors = validate_author_json(cfg)
    assert any(e.startswith("memory.injection.position") for e in errors)


def test_memory_dynamic_modules_int_values():
    # docs memory 表：dynamic_modules object 必填✓，键=模块名、值为 DB 载入条数（int）
    cfg = base()
    del cfg["memory"]["dynamic_modules"]
    assert any(e.startswith("memory.dynamic_modules") for e in validate_author_json(cfg))
    cfg = base()
    cfg["memory"]["dynamic_modules"] = "not-a-dict"
    assert any(e.startswith("memory.dynamic_modules") for e in validate_author_json(cfg))
    cfg = base()
    cfg["memory"]["dynamic_modules"] = {"feedback_memory": "5"}
    errors = validate_author_json(cfg)
    assert any(e.startswith("memory.dynamic_modules") for e in errors)


# ---------------- route.gates（docs route 表 gates 各行） ----------------

def test_gates_required_keys_and_unknown_name():
    # docs route 表：gates 必填✓，7 门禁键全✓（门禁开关须显式声明，可配 false/[] 关闭）；
    # 未知门禁名须报（路径 route.gates）
    cfg = base()
    del cfg["route"]["gates"]
    assert any(e.startswith("route.gates") for e in validate_author_json(cfg))
    for key in GATE_KEYS:
        cfg = base()
        del cfg["route"]["gates"][key]
        errors = validate_author_json(cfg)
        assert any(e.startswith(f"route.gates.{key}") for e in errors), (key, errors)
    cfg = base()
    cfg["route"]["gates"]["magic_gate"] = {}
    errors = validate_author_json(cfg)
    assert any(e.startswith("route.gates") and "magic_gate" in e for e in errors)


def test_gates_length_contract():
    # docs route 表：gates.length {min,max,unit:"chars"} 必填✓；本阶段仅 chars
    cfg = base()
    cfg["route"]["gates"]["length"] = {}
    errors = validate_author_json(cfg)
    assert any(e.startswith("route.gates.length.min") for e in errors)
    assert any(e.startswith("route.gates.length.max") for e in errors)
    cfg = base()
    cfg["route"]["gates"]["length"]["min"] = "short"
    assert any(e.startswith("route.gates.length.min") for e in validate_author_json(cfg))
    cfg = base()
    cfg["route"]["gates"]["length"]["max"] = "long"
    assert any(e.startswith("route.gates.length.max") for e in validate_author_json(cfg))
    cfg = base()
    cfg["route"]["gates"]["length"]["unit"] = "words"
    errors = validate_author_json(cfg)
    assert any(e.startswith("route.gates.length.unit") for e in errors)


def test_gates_fingerprint_echo_citation_copyright_types():
    # docs route 表：fingerprint {min_hits} / echo_check bool / citation {min_count} /
    # copyright {ngram} —— 类型错须报（数值边界无条款不钉）
    cfg = base()
    cfg["route"]["gates"]["fingerprint"]["min_hits"] = "two"
    assert any(e.startswith("route.gates.fingerprint.min_hits")
               for e in validate_author_json(cfg))
    cfg = base()
    cfg["route"]["gates"]["echo_check"] = "yes"
    assert any(e.startswith("route.gates.echo_check") for e in validate_author_json(cfg))
    cfg = base()
    cfg["route"]["gates"]["citation"]["min_count"] = "three"
    assert any(e.startswith("route.gates.citation.min_count")
               for e in validate_author_json(cfg))
    cfg = base()
    cfg["route"]["gates"]["copyright"]["ngram"] = "eight"
    assert any(e.startswith("route.gates.copyright.ngram")
               for e in validate_author_json(cfg))


def test_gates_topic_dedup_contract():
    # docs route 表 + 偏离记录2：topic_dedup {recent_n, threshold?}；
    # threshold 为 number（JSON number 不含 bool——沿模块 bool 非 int 纪律）
    cfg = base()
    cfg["route"]["gates"]["topic_dedup"]["recent_n"] = "many"
    assert any(e.startswith("route.gates.topic_dedup.recent_n")
               for e in validate_author_json(cfg))
    cfg = base()
    cfg["route"]["gates"]["topic_dedup"]["threshold"] = "high"
    errors = validate_author_json(cfg)
    assert any(e.startswith("route.gates.topic_dedup.threshold") for e in errors)
    cfg = base()
    cfg["route"]["gates"]["topic_dedup"]["threshold"] = True
    errors = validate_author_json(cfg)
    assert any(e.startswith("route.gates.topic_dedup.threshold") for e in errors)


def test_gates_topic_dedup_threshold_accepts_numbers():
    # 偏离记录2：threshold 可选 Dice 阈值——int 与 float 均为合法 JSON number
    for val in (1, 0.6):
        cfg = base()
        cfg["route"]["gates"]["topic_dedup"]["threshold"] = val
        assert only(validate_author_json(cfg), "topic_dedup") == [], (val,)


def test_gates_custom_array():
    # docs route 表：gates.custom array 必填✓
    cfg = base()
    cfg["route"]["gates"]["custom"] = "not-a-list"
    assert any(e.startswith("route.gates.custom") for e in validate_author_json(cfg))


def test_gates_rewrite_bounds_pinned():
    # docs route 表：rewrite.max_attempts int(1-10) 必填✓——本批唯一 docs 钉死数值边界；
    # 缺失须报、0 与 11 须报、1 与 10 边界合法
    cfg = base()
    del cfg["route"]["rewrite"]["max_attempts"]
    assert any(e.startswith("route.rewrite.max_attempts") for e in validate_author_json(cfg))
    for bad, expect in ((0, "route.rewrite.max_attempts"), (11, "route.rewrite.max_attempts")):
        cfg = base()
        cfg["route"]["rewrite"]["max_attempts"] = bad
        errors = validate_author_json(cfg)
        assert any(e.startswith(expect) for e in errors), (bad, errors)
    for good in (1, 10):
        cfg = base()
        cfg["route"]["rewrite"]["max_attempts"] = good
        assert only(validate_author_json(cfg), "max_attempts") == [], (good,)


def test_gates_rewrite_enums():
    # docs route 表：rewrite 必填✓；mode ∈ gated_retry|zero_revision；on_gate_fail ∈ revise|record
    cfg = base()
    del cfg["route"]["rewrite"]
    assert any(e.startswith("route.rewrite") for e in validate_author_json(cfg))
    cfg = base()
    cfg["route"]["rewrite"]["mode"] = "quantum"
    assert any(e.startswith("route.rewrite.mode") for e in validate_author_json(cfg))
    cfg = base()
    cfg["route"]["rewrite"]["on_gate_fail"] = "explode"
    assert any(e.startswith("route.rewrite.on_gate_fail") for e in validate_author_json(cfg))


# ---------------- route 其余（outline/draft/passes/think_routing，docs route 表） ----------------

def test_route_outline_contract():
    # docs route 表：outline 必填✓；outline.template 枚举必填✓；params object 必填（可空）
    cfg = base()
    del cfg["route"]["outline"]
    assert any(e.startswith("route.outline") for e in validate_author_json(cfg))
    cfg = base()
    cfg["route"]["outline"] = {}
    errors = validate_author_json(cfg)
    assert any(e.startswith("route.outline.template") for e in errors)
    assert any(e.startswith("route.outline.params") for e in errors)
    cfg = base()
    cfg["route"]["outline"]["params"] = "nope"
    errors = validate_author_json(cfg)
    assert any(e.startswith("route.outline.params") for e in errors)


def test_route_draft_contract():
    # docs route 表：draft.mode 枚举必填✓；params object 必填✓；
    # draft.params.max_tokens 可选（默认 4000）、think 可选兼容字段
    cfg = base()
    del cfg["route"]["draft"]
    assert any(e.startswith("route.draft") for e in validate_author_json(cfg))
    cfg = base()
    del cfg["route"]["draft"]["params"]
    assert any(e.startswith("route.draft.params") for e in validate_author_json(cfg))
    cfg = base()
    cfg["route"]["draft"]["params"] = {"max_tokens": "many"}
    errors = validate_author_json(cfg)
    # 模块对 max_tokens 的报错路径形态为 route.draft.max_tokens（dp 段）
    assert any(e.startswith("route.draft.max_tokens") for e in errors)
    cfg = base()
    cfg["route"]["draft"]["params"] = {}
    assert only(validate_author_json(cfg), "draft") == []
    cfg = base()
    cfg["route"]["draft"]["params"] = {"think": "deep"}
    errors = validate_author_json(cfg)
    assert any(e.startswith("route.draft.params.think") for e in errors)
    cfg = base()
    cfg["route"]["draft"]["params"] = {"max_tokens": 4000}
    assert only(validate_author_json(cfg), "think") == []


def test_route_passes_contract():
    # docs route 表：passes array 必填✓，元素 {type, params}；AC-11.1 rhythm 遍入序列
    cfg = base()
    del cfg["route"]["passes"]
    assert any(e.startswith("route.passes") for e in validate_author_json(cfg))
    cfg = base()
    cfg["route"]["passes"] = "not-a-list"
    assert any(e.startswith("route.passes") for e in validate_author_json(cfg))
    cfg = base()
    cfg["route"]["passes"] = ["nope"]
    errors = validate_author_json(cfg)
    assert any(e.startswith("route.passes[0]") for e in errors)
    cfg = base()
    cfg["route"]["passes"] = [{"type": "rhythm", "params": {}}]
    assert validate_author_json(cfg) == []


def test_route_think_routing_contract():
    # docs route 表：think_routing.default ∈ chat|reasoner 必填✓；
    # per_node 可选：值 ∈ chat|reasoner，键限 w_* 前缀或 writing
    cfg = base()
    del cfg["route"]["think_routing"]
    assert any(e.startswith("route.think_routing") for e in validate_author_json(cfg))
    cfg = base()
    cfg["route"]["think_routing"]["default"] = "quantum"
    errors = validate_author_json(cfg)
    assert any(e.startswith("route.think_routing.default") for e in errors)
    cfg = base()
    cfg["route"]["think_routing"]["per_node"] = {"w_x": "quantum"}
    errors = validate_author_json(cfg)
    assert any(e.startswith("route.think_routing.per_node") for e in errors)
    cfg = base()
    cfg["route"]["think_routing"]["per_node"] = {"bad_key": "chat"}
    errors = validate_author_json(cfg)
    assert any(e.startswith("route.think_routing.per_node") for e in errors)
    cfg = base()
    cfg["route"]["think_routing"]["per_node"] = {"w_draft": "reasoner", "writing": "chat"}
    assert only(validate_author_json(cfg), "think_routing") == []


# ---------------- 入口契约与缺省产物 ----------------

def test_load_author_config_raises_with_all_errors():
    # AC-10.1 一次报全不短路：多处错误一次报出，全部含字段路径
    cfg = base()
    cfg["template"] = "quantum"
    del cfg["identity"]["name"]
    cfg["route"]["rewrite"]["max_attempts"] = 99
    with pytest.raises(AuthorConfigError) as ei:
        load_author_config(cfg)
    msg = str(ei.value)
    assert "(root).template" in msg
    assert "identity.name" in msg
    assert "route.rewrite.max_attempts" in msg


def test_default_config_pinned_values():
    # schema 头部版本 `2026-09-29-a`（docs 权威描述）；docs route 表
    # draft.params.max_tokens 默认 4000；偏离记录/AC-11.4 版权 ngram=8 基线
    cfg = default_author_config("t1", "测试作者")
    assert cfg["version"] == "2026-09-29-a"
    assert cfg["route"]["draft"]["params"]["max_tokens"] == 4000
    assert cfg["route"]["gates"]["copyright"]["ngram"] == 8
