"""Hacker News collector via the official Firebase API (no key, generous limits)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx

from src.analyzers.schemas import RawTrendItem
from src.collectors.base import BaseCollector, register

API = "https://hacker-news.firebaseio.com/v0"
FEEDS = {
    "top": "topstories",
    "new": "newstories",
    "best": "beststories",
    "ask": "askstories",
    "show": "showstories",
}


@register("hackernews")
class HackerNewsCollector(BaseCollector):
    async def fetch(self, client: httpx.AsyncClient) -> list[RawTrendItem]:
        feed = FEEDS.get(str(self.params.get("feed", "top")), "topstories")
        ids: list[int] = (await self._get(client, f"{API}/{feed}.json")).json()[: self.limit * 2]
        sem = asyncio.Semaphore(8)

        async def one(item_id: int) -> dict | None:
            async with sem:
                try:
                    return (await self._get(client, f"{API}/item/{item_id}.json")).json()
                except httpx.HTTPError:
                    return None

        stories = await asyncio.gather(*(one(i) for i in ids))
        items: list[RawTrendItem] = []
        for s in stories:
            if not s or s.get("type") != "story" or s.get("dead") or s.get("deleted"):
                continue
            url = s.get("url") or f"https://news.ycombinator.com/item?id={s['id']}"
            items.append(
                self._item(
                    title=s.get("title", "").strip() or "(untitled)",
                    url=url,
                    score=int(s.get("score", 0)),
                    comments=int(s.get("descendants", 0)),
                    published_at=datetime.fromtimestamp(int(s.get("time", 0)), tz=UTC),
                    tags=["hackernews", feed],
                    extra={
                        "hn_id": s["id"],
                        "discussion": f"https://news.ycombinator.com/item?id={s['id']}",
                    },
                )
            )
        return items

    def sample(self) -> list[RawTrendItem]:
        now = datetime.now(UTC)
        rows = [
            (
                "Show HN: I built a zero-server trend agent on GitHub Actions",
                "https://example.com/hn/trend-agent",
                412,
                98,
            ),
            (
                "Gemini 2.5 Flash gets structured output and 1M context",
                "https://example.com/hn/gemini-flash",
                350,
                142,
            ),
            (
                "Why we moved our cron jobs to GitHub Actions (and what broke)",
                "https://example.com/hn/cron-actions",
                287,
                76,
            ),
            (
                "uv 0.5: a single tool for Python packaging",
                "https://example.com/hn/uv-05",
                265,
                110,
            ),
            (
                "Pydantic V2 validators: context-aware grounding tricks",
                "https://example.com/hn/pydantic-ctx",
                140,
                31,
            ),
            (
                "Ask HN: Cheapest way to run a daily LLM pipeline?",
                "https://news.ycombinator.com/item?id=1",
                98,
                64,
            ),
        ]
        return [
            self._item(title=t, url=u, score=s, comments=c, published_at=now, tags=["hackernews", "sample"])
            for t, u, s, c in rows
        ]
