"""SMTP 配置布尔位测试：未配置域必须如实为 False。

覆盖口径（US-19 通知设置 + 凭据只出布尔位约定，设计依据见
docs/design-index.md「US-19」）：smtp_configured 是设置页唯一配置状态指示，
未配置 SMTP 时不得虚报已配置（布尔位语义本体——真实状态不伪装）。
"""


def test_smtp_configured_false_without_credentials(auth_client):
    r = auth_client.get("/api/settings/notify")
    assert r.status_code == 200
    assert r.json()["smtp_configured"] is False
