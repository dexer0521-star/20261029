"""Apify Actor collector: runs an Actor synchronously and maps dataset items.

params:
  actor_id: "owner/actor-name"
  token_env: APIFY_TOKEN          # env var name only
  input: {...}                    # Actor input
  title_field / url_field / score_field: override dataset field names
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from src.analyzers.schemas import RawTrendItem
from src.collectors.base import BaseCollector, register
from src.config_loader import resolve_env

API = "https://api.apify.com/v2"


@register("apify")
class ApifyCollector(BaseCollector):
    async def fetch(self, client: httpx.AsyncClient) -> list[RawTrendItem]:
        actor_id = self.params.get("actor_id")
        if not actor_id:
            raise ValueError("apify collector needs params.actor_id")
        token = resolve_env(self.params.get("token_env", "APIFY_TOKEN"), what="apify token")
        actor_path = str(actor_id).replace("/", "~")
        url = f"{API}/acts/{actor_path}/run-sync-get-dataset-items"
        resp = await client.post(
            url,
            params={
                "token": token,
                "timeout": int(self.params.get("timeout", 120)),
                "clean": "true",
            },
            json=self.params.get("input", {}),
            timeout=httpx.Timeout(180.0, connect=10.0),
        )
        resp.raise_for_status()
        rows = resp.json()
        if not isinstance(rows, list):
            raise RuntimeError("unexpected apify response shape")
        tf = self.params.get("title_field", "title")
        uf = self.params.get("url_field", "url")
        sf = self.params.get("score_field")
        items: list[RawTrendItem] = []
        for r in rows[: self.limit]:
            title, link = r.get(tf), r.get(uf)
            if not title or not link:
                continue
            score = r.get(sf) if sf else None
            items.append(
                self._item(
                    title=str(title)[:500],
                    url=str(link),
                    score=int(score) if isinstance(score, int | float) else None,
                    published_at=datetime.now(UTC),
                    tags=["apify", str(actor_id)],
                    extra={k: v for k, v in r.items() if isinstance(v, str | int | float) and k not in (tf, uf)},
                )
            )
        return items

    def sample(self) -> list[RawTrendItem]:
        return [
            self._item(
                title="Sample Apify dataset row (dry-run)",
                url="https://example.com/apify/row-1",
                score=10,
                tags=["apify", "sample"],
            ),
        ]
