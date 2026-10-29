"""Slack notifier using an Incoming Webhook + Block Kit (webhook_env names the secret)."""

from __future__ import annotations

import httpx

from src.analyzers.schemas import AnalyzedTrendBrief
from src.config_loader import resolve_env
from src.notifiers.base import STATUS_ICON, BaseNotifier, register

MAX_BLOCKS = 45  # Slack hard limit is 50 blocks per message


def _trim(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def build_blocks(brief: AnalyzedTrendBrief, max_items: int = 10) -> list[dict]:
    ts = brief.generated_at.strftime("%Y-%m-%d %H:%M UTC")
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": _trim(brief.headline, 150), "emoji": True},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"*{brief.preset}* · {ts} · {brief.provider}/{brief.model}",
                }
            ],
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": _trim(brief.overview, 2900)}},
    ]
    if brief.degraded:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "⚠️ LLM unavailable: extractive mode"}],
            }
        )
    if brief.rising_keywords:
        kws = " ".join(f"`{k}`" for k in brief.rising_keywords[:10])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"📈 *Rising:* {kws}"}})
    blocks.append({"type": "divider"})
    for it in brief.items[:max_items]:
        icon = STATUS_ICON.get(it.status, "")
        body = f"{icon} *<{it.url}|{_trim(it.title, 120)}>*  `{it.importance}/10`\n{_trim(it.summary, 400)}"
        if it.insight:
            body += f"\n_💡 {_trim(it.insight, 300)}_"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body}})
        if len(blocks) >= MAX_BLOCKS - 2:
            break
    if brief.source_errors:
        errs = ", ".join(f"`{e.source}`" for e in brief.source_errors[:5])
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"⚠️ sources failed: {errs}"}],
            }
        )
    return blocks


@register("slack")
class SlackNotifier(BaseNotifier):
    async def send(self, brief: AnalyzedTrendBrief, client: httpx.AsyncClient) -> str:
        webhook = resolve_env(self.config.webhook_env, what="slack webhook")
        max_items = int(self.config.params.get("max_items", 10))
        payload = {"text": brief.headline, "blocks": build_blocks(brief, max_items)}
        resp = await client.post(webhook, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"slack webhook {resp.status_code}: {resp.text[:120]}")
        return f"posted {min(len(brief.items), max_items)} items"
