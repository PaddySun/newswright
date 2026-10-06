"""SMTP 通知通道（首个 Notifier 子类）：SMTP_SSL + 站点配置化凭据。

凭据纪律：SMTP 参数全部存 site_config（smtp_* 键）；凭据不回显、不落日志；
发送失败 WARN 不抛。
设计依据见 docs/design-index.md「AC-19.1」。
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from ..siteconfig import get_config
from . import Notifier, register

log = logging.getLogger("newswright.notify")


class SMTPNotifier(Notifier):
    name = "smtp"

    def _cfg(self, key):
        return get_config(self.db, f"smtp_{key}")

    def configured(self) -> bool:
        """必填四项（host/port/发信人/收件列表）齐备即视为已配置；账号密码可选。"""
        to_addrs = self._cfg("to") or self._cfg("to_addrs")
        return bool(self._cfg("host") and self._cfg("port")
                    and self._cfg("from") and to_addrs)

    def _deliver(self, subject: str, body: str) -> None:
        host = str(self._cfg("host"))
        port = int(self._cfg("port") or 465)
        user = self._cfg("user")
        password = self._cfg("pass")
        from_addr = str(self._cfg("from"))
        to_addrs = self._cfg("to") or self._cfg("to_addrs")
        if isinstance(to_addrs, str):
            to_addrs = [to_addrs]
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_addrs)
        with smtplib.SMTP_SSL(host, port, timeout=30) as server:
            if user and password:
                server.login(str(user), str(password))
            server.sendmail(from_addr, list(to_addrs), msg.as_string())


register("smtp", SMTPNotifier)
