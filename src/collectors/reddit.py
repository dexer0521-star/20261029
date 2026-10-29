"""Reddit collector using the public JSON listing (no OAuth; be gentle with rate limits)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from src.analyzers.schemas import RawTrendItem
from src.collectors.base import BaseCollector, register


@register("reddit")
class RedditCollector(BaseCollector):
    async def fetch(self, client: httpx.AsyncClient) -> list[RawTrendItem]:
        sub = self.params.get("subreddit")
        if not sub:
            raise ValueError("reddit collector needs params.subreddit")
        sort = self.params.get("sort", "hot")
        url = f"https://www.reddit.com/r/{sub}/{sort}.json"
        data = (await self._get(client, url, params={"limit": min(self.limit, 100), "raw_json": 1})).json()
        items: list[RawTrendItem] = []
        for child in data.get("data", {}).get("children", []):
            p = child.get("data", {})
            if p.get("stickied") or p.get("removed_by_category"):
                continue
            permalink = f"https://www.reddit.com{p.get('permalink', '')}"
            items.append(
                self._item(
                    title=p.get("title", "").strip() or "(untitled)",
                    url=p.get("url") if not p.get("is_self") else permalink,
                    score=int(p.get("score", 0)),
                    comments=int(p.get("num_comments", 0)),
                    published_at=datetime.fromtimestamp(float(p.get("created_utc", 0)), tz=UTC),
                    summary=(p.get("selftext") or "")[:1000] or None,
                    tags=["reddit", f"r/{sub}", p.get("link_flair_text") or ""],
                    extra={"discussion": permalink, "subreddit": sub},
                )
            )
        return items

    def sample(self) -> list[RawTrendItem]:
        now = datetime.now(UTC)
        return [
            self._item(
                title="Which Korean toner actually changed your skin? (2026 edition)",
                url="https://example.com/reddit/toner",
                score=540,
                comments=210,
                published_at=now,
                tags=["reddit", "sample"],
            ),
            self._item(
                title="PSA: TikTok Shop K-beauty bundles are 30% cheaper than Amazon right now",
                url="https://example.com/reddit/tiktok-bundles",
                score=380,
                comments=95,
                published_at=now,
                tags=["reddit", "sample"],
            ),
        ]
