"""T1 变异分诊批次 1 补强测试（认证域 45 幸存体中的 C 类：27 条测试缺口）。

> 追溯注记：本文件原名 tests/test_mutation_t1.py（原批次代号见文件名），按对象重命名于 F1⑫治理批。

每个测试的断言全部来自设计书明确条款（AC-xx.x / ADR-x / D-x / 错误码表），
命名 test_<function>_<mutant编号>_<断言点>（任务书 §3.3）。Given-When-Then。
"""
from datetime import datetime, timedelta, timezone

import app.api.auth as auth_mod
import app.config as cfg
from app import siteconfig
from app.api.deps import LoginRateLimiter, get_client_ip
from app.models import User


def _login(client, password=None):
    return client.post("/api/auth/login",
                       json={"username": "admin",
                             "password": password or cfg.NEWSWRIGHT_ADMIN_PASSWORD})


def _request(headers=None, client=("10.0.0.1", 50000)):
    """构造裸 starlette Request（unit 级调用 get_client_ip，绕过路由）。"""
    from starlette.requests import Request

    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {"type": "http", "method": "GET", "path": "/", "headers": raw}
    if client is not None:
        scope["client"] = list(client)
    return Request(scope)


def test_x_error_mutant_7_8_auth_invalid_full_body(api_client):
    """AC-01.2：401 错误体全量契约——code 与 message 措辞均被条款钉定。

    Given 账号 admin 存在；When 错误密码登录；Then 401
    {"code":"AUTH_INVALID","message":"用户名或密码错误"}（AC-01.2 Then 原文）。
    """
    r = _login(api_client, "wrong-pass")
    assert r.status_code == 401
    assert r.json() == {"code": "AUTH_INVALID", "message": "用户名或密码错误"}


def test_require_session_mutant_16_17_401_message_nonempty(api_client):
    """AC-01.3 + 产品书 §3 错误体统一约定：401 响应必须含非空人读 message。

    Given 未携带会话 cookie；When GET /items；Then 401 AUTH_REQUIRED，
    错误体为 {"code","message"} 两键（message = 人读信息，不得为空）。
    """
    r = api_client.get("/items")
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "AUTH_REQUIRED"
    assert isinstance(body["message"], str) and body["message"]


def test_require_session_mutant_28_29_403_message_nonempty(api_client):
    """AC-01.1 + 产品书 §3 错误体统一约定：首登门禁 403 须含非空人读 message。

    Given 初始 admin（must_change_password=true）；When GET /items；
    Then 403 PASSWORD_CHANGE_REQUIRED，错误体含非空 message。
    """
    assert _login(api_client).status_code == 200
    r = api_client.get("/items")
    assert r.status_code == 403
    body = r.json()
    assert body["code"] == "PASSWORD_CHANGE_REQUIRED"
    assert isinstance(body["message"], str) and body["message"]


def test_get_client_ip_mutant_1_2_3_5_8_9_11_12_13_configured_header_first(db_session):
    """ADR-5⑤：请求侧真实 IP 提取链 = site_config 配置头优先。

    Given site_config.client_ip_header 已配置；When 请求携带该头；
    Then 提取结果 = 头值而非直连地址（禁回退 request.client.host 直读）。
    """
    siteconfig.set_config(db_session, "client_ip_header", "X-Tenant-IP")
    request = _request({"X-Tenant-IP": "203.0.113.7"})
    assert get_client_ip(request, db_session) == "203.0.113.7"


def test_get_client_ip_mutant_10_unconfigured_ignores_headers(db_session):
    """ADR-5⑤：提取链唯一来源 = site_config 配置头；未配置时任何请求头不得被信任。

    Given client_ip_header 未配置（默认空 = 直连地址）；When 请求携带
    X-Forwarded-For 及任意自制头；Then 仍返回直连地址（防伪造头提取）。
    """
    request = _request({"X-Forwarded-For": "8.8.8.8",
                        "XXXX": "9.9.9.9", "X-Real-IP": "7.7.7.7"})
    assert get_client_ip(request, db_session) == "10.0.0.1"


def test_get_client_ip_mutant_14_blank_header_falls_back(db_session):
    """ADR-5⑤ + get_client_ip 契约（配置头优先，空 = 直连地址）：
    配置头存在但取值为空白时必须回退直连地址，不得返回空串作客户端身份。"""
    siteconfig.set_config(db_session, "client_ip_header", "X-Tenant-IP")
    request = _request({"X-Tenant-IP": "   "})
    assert get_client_ip(request, db_session) == "10.0.0.1"


def test_login_rate_limiter_mutant_1_2_3_4_init_and_lock_contract():
    """AC-01.2：限速器单元契约——初始放行、连续 5 次失败即起锁（注入时钟等价验证）。"""
    base = datetime.now(timezone.utc)
    clock = {"t": base}
    lrl = LoginRateLimiter(now=lambda: clock["t"])
    assert lrl.allow("ip-a") is True  # 首次尝试放行
    for _ in range(5):
        lrl.record_failure("ip-a")  # 第 5 次失败即起锁
    assert lrl.allow("ip-a") is False  # 冷却期内拒绝
    # 默认时钟路径同样可用（不注入 now）
    lrl2 = LoginRateLimiter()
    for _ in range(5):
        lrl2.record_failure("ip-b")
    assert lrl2.allow("ip-b") is False


def test_allow_mutant_12_cooldown_end_resets_count(api_client, monkeypatch):
    """AC-01.2："连续 5 次失败"——冷却结束后计数清零，一次新失败不立刻再锁。

    Given 已触发限速锁定；When 冷却 15 分钟结束；Then 重新计数：
    一次失败仅 401，正确密码仍可登录（不得立即回到 429）。
    """
    base = datetime.now(timezone.utc)
    clock = {"t": base}
    monkeypatch.setattr(auth_mod.login_limiter, "now", lambda: clock["t"])
    for _ in range(5):
        assert _login(api_client, "wrong-pass").status_code == 401
    assert _login(api_client).status_code == 429  # 第 6 次起 429
    clock["t"] = base + timedelta(minutes=16)  # 冷却结束
    assert _login(api_client, "wrong-pass").status_code == 401  # 新一轮第 1 次失败
    assert _login(api_client).status_code == 200  # 正确密码可登录


def test_record_success_mutant_1_success_resets_failures(api_client):
    """AC-01.2："连续"语义——成功登录清零该身份失败计数。

    Given 2 次失败后成功登录；When 再 3 次失败；Then 计数未达 5，正确密码可登录。
    """
    assert _login(api_client, "wrong-pass").status_code == 401
    assert _login(api_client, "wrong-pass").status_code == 401
    assert _login(api_client).status_code == 200  # 成功清零计数
    for _ in range(3):
        assert _login(api_client, "wrong-pass").status_code == 401
    assert _login(api_client).status_code == 200  # 3 次新失败 < 5，不锁


def test_bootstrap_admin_mutant_6_must_change_password_true(db_session):
    """AC-01.1（D18）：首次部署初始化创建 admin 且 must_change_password=true。"""
    from app.auth import bootstrap_admin

    bootstrap_admin(db_session)
    user = db_session.query(User).filter_by(username="admin").one()
    assert user.must_change_password is True


def test_set_config_mutant_1_3_13_upsert_overwrite(db_session):
    """AC-01.4 + 技术书 §4.1 site_config：写配置 upsert——已有键改值必须生效。

    Given session_duration_days 已有配置行；When 再次写该键；Then 新值生效
    （保持期限可配 = 改值后立即按新值读取）。
    """
    siteconfig.set_config(db_session, "session_duration_days", 7)
    siteconfig.set_config(db_session, "session_duration_days", -1)  # 更新路径
    assert siteconfig.get_config(db_session, "session_duration_days") == -1
