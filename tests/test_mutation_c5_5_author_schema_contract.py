"""author.json 校验错误的字段路径契约（模型绑定分层纪律面——作者 W0
面回归族分诊补面）。

覆盖：文档携带 model 键的拒绝错误携带字段路径前缀「model」（校验错误
一律「{字段路径}: {说明}」形态——含字段路径是契约，说明措辞不钉）。
设计依据见 docs/design-index.md「AC-10.1」「AC-10.2」。
"""
from app.authors.schema import default_author_config, validate_author_json


def test_model_key_rejection_carries_field_path():
    """文档内含 model 键 → 拒绝错误的路径前缀为「model」（模型不在 JSON
    中——绑定只走导入请求参数/后台配置；错误含字段路径，一次报全）。"""
    doc = default_author_config("c5-5-schema", "路径作者")
    doc["model"] = "smuggled-model"
    errors = validate_author_json(doc)
    assert any(e.startswith("model") for e in errors)
