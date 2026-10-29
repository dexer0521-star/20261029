"""Notion notifier: creates one page per run inside a database (token_env / database_id_env).

The database needs a title property (any name; defaults to 'Name'). Optional properties
'Date' (date) and 'Preset' (rich_text) are filled when `params.date_property` /
`params.preset_property` are set.
"""

from __future__ import annotations

import httpx

from src.analyzers.schemas import AnalyzedTrendBrief
from src.config_loader import resolve_env
from src.notifiers.base import STATUS_ICON, BaseNotifier, register

NOTION_VERSION = "2022-06-28"


def _rt(text: str, link: str | None = None, bold: bool = False) -> dict:
    obj: dict = {"type": "text", "text": {"content": text[:1900]}, "annotations": {"bold": bold}}
    if link:
        obj["text"]["link"] = {"url": link}
    return obj


def _para(*rich: dict) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": list(rich)}}


def build_children(brief: AnalyzedTrendBrief, max_items: int = 15) -> list[dict]:
    children: list[dict] = [_para(_rt(brief.overview))]
    if brief.rising_keywords:
        children.append(_para(_rt("Rising: ", bold=True), _rt(", ".join(brief.rising_keywords))))
    children.append({"object": "block", "type": "divider", "divider": {}})
    for it in brief.items[:max_items]:
        icon = STATUS_ICON.get(it.status, "")
        children.append(
            {
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [_rt(f"{icon} {it.title}", it.url)]},
            }
        )
        children.append(_para(_rt(f"[{it.importance}/10 · {it.category}] ", bold=True), _rt(it.summary)))
        if it.insight:
            children.append({"object": "block", "type": "quote", "quote": {"rich_text": [_rt(it.insight)]}})
    if brief.source_errors:
        children.append(
            _para(
                _rt("Source warnings: ", bold=True),
                _rt("; ".join(f"{e.source}: {e.error}" for e in brief.source_errors)),
            )
        )
    return children[:95]  # Notion caps children at 100 per request


@register("notion")
class NotionNotifier(BaseNotifier):
    async def send(self, brief: AnalyzedTrendBrief, client: httpx.AsyncClient) -> str:
        token = resolve_env(self.config.token_env, what="notion token")
        database_id = resolve_env(self.config.database_id_env, what="notion database id")
        p = self.config.params
        title_prop = p.get("title_property", "Name")
        props: dict = {title_prop: {"title": [_rt(f"{brief.generated_at:%Y-%m-%d} · {brief.headline}")]}}
        if p.get("date_property"):
            props[p["date_property"]] = {"date": {"start": brief.generated_at.date().isoformat()}}
        if p.get("preset_property"):
            props[p["preset_property"]] = {"rich_text": [_rt(brief.preset)]}
        body = {
            "parent": {"database_id": database_id},
            "properties": props,
            "children": build_children(brief),
        }
        headers = {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION}
        resp = await client.post("https://api.notion.com/v1/pages", headers=headers, json=body)
        if resp.status_code >= 400:
            raise RuntimeError(f"notion {resp.status_code}: {resp.text[:160]}")
        return f"created page {resp.json().get('url', '')}"
