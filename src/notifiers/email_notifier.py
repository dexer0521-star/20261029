"""Email notifier via SMTP (stdlib smtplib). Env var names come from params.*_env."""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

import httpx

from src.analyzers.schemas import AnalyzedTrendBrief
from src.config_loader import resolve_env
from src.notifiers.base import BaseNotifier, register
from src.notifiers.markdown_notifier import render_markdown


@register("email")
class EmailNotifier(BaseNotifier):
    async def send(self, brief: AnalyzedTrendBrief, client: httpx.AsyncClient) -> str:
        p = self.config.params
        host = resolve_env(p.get("host_env", "SMTP_HOST"), what="smtp host")
        port = int(resolve_env(p.get("port_env", "SMTP_PORT"), required=False, what="smtp port") or 587)
        user = resolve_env(p.get("user_env", "SMTP_USER"), what="smtp user")
        password = resolve_env(p.get("password_env", "SMTP_PASSWORD"), what="smtp password")
        to = resolve_env(p.get("to_env", "EMAIL_TO"), what="email recipient")
        msg = EmailMessage()
        msg["Subject"] = f"[{brief.preset}] {brief.headline}"
        msg["From"], msg["To"] = user, to
        msg.set_content(render_markdown(brief))

        def _send() -> None:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.starttls()
                smtp.login(user, password)
                smtp.send_message(msg)

        await asyncio.to_thread(_send)
        return f"sent to {to}"
