"""文档面门禁与挂载契约（app.main）：P1-8 补面 + 挂载结构。

四面：
- /docs 生产门禁真值域：DOCS_ENABLED 的全部显式开启形态（1/true/yes/on）
  都打开文档面（既有测试只覆盖了 "true" 一种——真值集合是 as-implemented
  契约，与采集侧布尔开关同族）；
- 关闭态三件套：docs/redoc/openapi 全部不挂载（FastAPI 缺省路径即
  "/docs"/"/redoc"——关闭不是靠缺省值碰巧，显式 None 才是门禁）；
- 开启态 redoc 可达：显式开启时文档面完整提供（/redoc 标准路径）；
- 契约挂载与静态面：/api 前缀契约形态在挂载点产生；静态资源挂载在
  /static 路径并指向真实静态目录（SPA 与 P2-4 路径判定域的消费前提）。
设计依据见 docs/design-index.md「P1-8」「ADR-11」与《技术设计书-正式-TDD》
§3 OpenAPI 契约（/api 前缀形态）。
"""
import pytest
from fastapi.testclient import TestClient

from app.main import _docs_enabled, create_app


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_docs_enabled_accepts_all_explicit_on_forms(monkeypatch, value):
    """DOCS_ENABLED 显式开启真值域：1/true/yes/on 四形态全部识别为开
    （与配置布尔开关同族的真值集合——缺一即「设了却不生效」）。"""
    monkeypatch.setenv("DOCS_ENABLED", value)
    assert _docs_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "off", ""])
def test_docs_enabled_rejects_off_forms(monkeypatch, value):
    """关闭/非法值形态不开启文档面（门禁单向：默认关）。"""
    monkeypatch.setenv("DOCS_ENABLED", value)
    assert _docs_enabled() is False


def test_docs_disabled_state_mounts_nothing(db_session, monkeypatch):
    """关闭态三件套全不挂载：docs_url/redoc_url/openapi_url 显式 None
    （不得回落 FastAPI 缺省路径——缺省即生产泄露）。"""
    from app.auth import bootstrap_admin
    bootstrap_admin(db_session)
    monkeypatch.delenv("DOCS_ENABLED", raising=False)
    app = create_app()
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None


def test_docs_enabled_state_provides_redoc(db_session, monkeypatch):
    """开启态文档面完整：/redoc 在标准路径提供（docs 面三件套同门禁、
    开启即提供）。"""
    from app.auth import bootstrap_admin
    bootstrap_admin(db_session)
    monkeypatch.setenv("DOCS_ENABLED", "true")
    app = create_app()
    assert app.redoc_url == "/redoc"
    client = TestClient(app)
    assert client.get("/redoc").status_code == 200


def test_api_prefix_contract_mount_exists(db_session):
    """/api 前缀契约形态：契约路由经挂载点 prefix 产生（技术书 §3
    OpenAPI 契约与 SPA 消费面——demo 无前缀形态之外必须有 /api 形态）。
    行为断言：/api/items 走守卫生效返回 401（404=契约形态消失）。"""
    from app.auth import bootstrap_admin
    bootstrap_admin(db_session)
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/items")
    assert resp.status_code == 401  # 挂载且守卫生效（404=契约形态消失）


def test_static_mount_path_and_directory(db_session):
    """静态资源挂载：/static 路径、指向应用静态目录，真实文件可取
    （目录不得为空值/字面串——静态服务是 SPA 与响应头契约路径判定域
    的前提）。"""
    from app.auth import bootstrap_admin
    bootstrap_admin(db_session)
    from app.main import _static_dir
    app = create_app()
    mounts = [r for r in app.routes if type(r).__name__ == "Mount"]
    static = [m for m in mounts if getattr(m, "path", "") == "/static"]
    assert static, "static 挂载必须在 /static 路径"
    served_dir = str(static[0].app.directory).rstrip("/\\")
    assert served_dir.endswith("static")
    assert served_dir == str(_static_dir()).rstrip("/\\")
    client = TestClient(app)
    assert client.get("/static/app/api.js").status_code == 200
