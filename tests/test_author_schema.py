"""M14 单元测试：author.json 校验器 + 导入导出 round-trip。"""
import pytest

from app.authors.importer import import_author_json, roundtrip_check
from app.authors.schema import (
    AuthorConfigError,
    default_author_config,
    load_author_config,
    validate_author_json,
)


def test_default_config_valid():
    assert validate_author_json(default_author_config("t1", "测试作者")) == []


def test_missing_required_field():
    cfg = default_author_config("t1", "测试作者")
    del cfg["identity"]["style_anchor"]
    del cfg["route"]["gates"]["copyright"]
    errors = validate_author_json(cfg)
    assert any("identity.style_anchor" in e and "缺失" in e for e in errors)
    assert any("route.gates.copyright" in e and "缺失" in e for e in errors)


def test_type_error_reported():
    cfg = default_author_config("t1", "测试作者")
    cfg["route"]["rewrite"]["max_attempts"] = "three"
    cfg["memory"]["injection"]["max_slices_per_run"] = True  # bool 不是 int
    errors = validate_author_json(cfg)
    assert any("rewrite.max_attempts" in e for e in errors)
    assert any("max_slices_per_run" in e for e in errors)


def test_unknown_enum_and_gate():
    cfg = default_author_config("t1", "测试作者")
    cfg["route"]["draft"]["mode"] = "quantum"
    cfg["route"]["gates"]["magic_gate"] = {}
    errors = validate_author_json(cfg)
    assert any("draft.mode" in e and "quantum" in e for e in errors)
    assert any("未知门禁名" in e and "magic_gate" in e for e in errors)


def test_duplicate_block_id_and_nonroot():
    cfg = default_author_config("t1", "测试作者")
    blk = {"id": "s1", "text": "x", "source": "f", "injection": {"max_chars": 500}}
    cfg["memory"]["static_blocks"] = [blk, dict(blk)]
    errors = validate_author_json(cfg)
    assert any("重复的块 id" in e for e in errors)
    assert validate_author_json(["not", "a", "dict"])[0].startswith("(root)")


def test_load_raises_with_all_errors():
    cfg = default_author_config("t1", "测试作者")
    del cfg["identity"]["name"]
    del cfg["route"]["outline"]["template"]
    with pytest.raises(AuthorConfigError) as ei:
        load_author_config(cfg)
    msg = str(ei.value)
    assert "identity.name" in msg and "outline.template" in msg


def test_import_roundtrip(db_session):
    cfg = default_author_config("luxun_t", "测试·鲁迅")
    cfg["identity"]["description"] = "绍兴人，弃医从文"
    cfg["memory"]["static_blocks"] = [
        {"id": "s1", "text": "大约孔乙己的确死了", "source": "tests", "injection": {"max_chars": 500}}
    ]
    author = import_author_json(db_session, cfg, model="test-model",
                                readable_directions=[{"direction_id": 1, "threshold": 60}])
    assert author.model == "test-model"  # 模型只来自绑定参数
    assert author.author_json == cfg
    ok, diffs = roundtrip_check(author, cfg)
    assert ok, diffs
    # 派生字段
    assert author.memory_config == {"feedback_memory": 5, "topic_memory": 5}
    assert "luxun_t" in author.persona_prompt and "single" in author.persona_prompt


def test_import_new_author_requires_model(db_session):
    with pytest.raises(AuthorConfigError):
        import_author_json(db_session, default_author_config("t9", "无名作者"))


def test_optional_object_explicit_null_treated_as_absent():
    """可选 object 字段显式 null = 未写该键（宽松归一）：output.max_tokens_per_node
    与 route.think_routing.per_node 置 null 均不报类型错，校验零错误。"""
    cfg = default_author_config("t1", "空值作者")
    cfg["output"]["max_tokens_per_node"] = None
    cfg["route"]["think_routing"]["per_node"] = None
    assert validate_author_json(cfg) == []


def test_bio_public_visible_roundtrip(db_session):
    """呈现层两列随 author.json 文档 round-trip：导入时映射到 DB 列、导出时
    回填进文档；导出文档再导入即恢复同一作者的完整呈现配置（幂等一致，
    设计依据见 docs/design-index.md「AC-10.1」呈现层增补）。"""
    from app.authors.importer import export_author_json

    cfg = default_author_config("tanya_t", "测试·谭雅")
    cfg["bio"] = "退役情报官，以冷笔写作。"
    cfg["public_visible"] = True
    author = import_author_json(db_session, cfg, model="test-model")
    assert author.bio == "退役情报官，以冷笔写作。"
    assert author.public_visible is True

    exported = export_author_json(author)
    assert exported["bio"] == "退役情报官，以冷笔写作。"
    assert exported["public_visible"] is True
    assert roundtrip_check(author, exported)[0] is True

    # 导出文档再导入（同名 upsert）：呈现两列保持恢复一致
    again = import_author_json(db_session, exported, model="test-model")
    assert again.bio == "退役情报官，以冷笔写作。"
    assert again.public_visible is True


def test_bio_public_visible_optional_and_type_checked():
    """缺省合法（可增不可减原则下的可选项）；类型错报字段路径。"""
    cfg = default_author_config("t1", "无呈现键作者")
    assert validate_author_json(cfg) == []
    bad = default_author_config("t2", "类型错作者")
    bad["bio"] = 123
    bad["public_visible"] = "yes"
    errors = validate_author_json(bad)
    assert any(e.startswith("bio") for e in errors)
    assert any(e.startswith("public_visible") for e in errors)
