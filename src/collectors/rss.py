"""Generic RSS/Atom collector (feedparser). params.feeds: list of URLs."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import feedparser
import httpx

from src.analyzers.schemas import RawTrendItem
from src.collectors.base import BaseCollector, register


def _entry_time(entry: feedparser.FeedParserDict) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            return datetime.fromtimestamp(time.mktime(st), tz=UTC)
    return None


@register("rss")
class RSSCollector(BaseCollector):
    async def fetch(self, client: httpx.AsyncClient) -> list[RawTrendItem]:
        feeds = self.params.get("feeds") or []
        if not feeds:
            raise ValueError("rss collector needs params.feeds: [url, ...]")
        items: list[RawTrendItem] = []
        errors: list[str] = []
        for url in feeds:
            try:
                resp = await self._get(client, url)
                parsed = feedparser.parse(resp.content)
            except Exception as exc:  # noqa: BLE001 - one bad feed must not sink the others
                errors.append(f"{url}: {type(exc).__name__}")
                continue
            feed_title = str(parsed.feed.get("title", "")).strip()
            for e in parsed.entries[: self.limit]:
                link = e.get("link")
                if not link:
                    continue
                items.append(
                    self._item(
                        title=str(e.get("title", "")).strip() or "(untitled)",
                        url=link,
                        published_at=_entry_time(e),
                        summary=_clean(str(e.get("summary", "")))[:1000] or None,
                        tags=["rss"] + [t.get("term", "") for t in e.get("tags", [])][:5],
                        extra={"feed": feed_title or url},
                    )
                )
        if not items and errors:
            raise RuntimeError("all feeds failed: " + "; ".join(errors))
        return items

    def sample(self) -> list[RawTrendItem]:
        now = datetime.now(UTC)
        rows = [
            (
                "Startup raises $40M to automate research briefings for SMBs",
                "https://example.com/rss/raise-40m",
            ),
            (
                "Amazon beauty bestsellers: Korean sunscreen tops the chart again",
                "https://example.com/rss/kbeauty-sunscreen",
            ),
            ("Fed holds rates, signals one cut this year", "https://example.com/rss/fed-holds"),
            (
                "New open-source Slack Block Kit builder hits 2k stars in a week",
                "https://example.com/rss/blockkit",
            ),
        ]
        return [
            self._item(
                title=t,
                url=u,
                published_at=now,
                summary="Sample RSS entry for --dry-run.",
                tags=["rss", "sample"],
            )
            for t, u in rows
        ]


def _clean(html: str) -> str:
    import re

    return re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ").strip()
