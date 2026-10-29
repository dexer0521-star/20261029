"""Notifiers: one file per channel. Register with @register("type")."""

from src.notifiers import email_notifier, markdown_notifier, notion_notifier, slack_notifier  # noqa: E402, F401
from src.notifiers.base import BaseNotifier, NotifyResult, register, run_notifiers  # noqa: F401
