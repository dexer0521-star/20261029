"""Pydantic V2 data pipeline schemas.

Pipeline: RawTrendItem (collect) -> DiffTrendItem (diff vs last run)
          -> AnalyzedTrendBrief (LLM output, grounded to input URLs).

Groundedness: `BriefItem.url` must be one of the URLs passed in via
`model_validate(..., context={"allowed_urls": {...}})`. The LLM can never
invent a link that survives validation.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

_TRACKING_PARAMS = ("utm_", "ref=", "fbclid", "gclid")


def normalize_url(url: str) -> str:
    """Strip fragments and common tracking params, lowercase host, drop trailing slash."""
    parts = urlsplit(url.strip())
    query = "&".join(kv for kv in parts.query.split("&") if kv and not kv.lower().startswith(_TRACKING_PARAMS))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def item_id_for(url: str) -> str:
    """Stable 16-char id derived from the normalized URL (used for diffing across runs)."""
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()[:16]


class RawTrendItem(BaseModel):
    """One collected item, straight from a collector."""

    id: str = ""
    source: str = Field(..., description="Collector name, e.g. 'hackernews' or 'rss:techcrunch'")
    title: str = Field(..., min_length=1, max_length=500)
    url: str = Field(..., min_length=8)
    score: int | None = Field(default=None, description="Upvotes / points if the source has them")
    comments: int | None = None
    published_at: datetime | None = None
    summary: str | None = Field(default=None, max_length=2000)
    tags: list[str] = Field(default_factory=list)
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def _must_be_http(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v

    @model_validator(mode="after")
    def _fill_id(self) -> RawTrendItem:
        if not self.id:
            self.id = item_id_for(self.url)
        return self


class DiffStatus(StrEnum):
    NEW = "new"
    RISING = "rising"
    STEADY = "steady"
    FALLING = "falling"


class DiffTrendItem(RawTrendItem):
    """RawTrendItem enriched with deltas against the previous run snapshot."""

    status: DiffStatus = DiffStatus.NEW
    rank: int = Field(..., ge=1, description="1-based rank within this run (by score, then recency)")
    prev_rank: int | None = None
    prev_score: int | None = None
    score_delta: int | None = None
    rank_delta: int | None = Field(default=None, description="positive = moved up")
    seen_runs: int = Field(default=1, ge=1, description="How many consecutive runs this item appeared")

    @property
    def is_fresh(self) -> bool:
        return self.status in (DiffStatus.NEW, DiffStatus.RISING)


class SourceError(BaseModel):
    source: str
    error: str


class BriefItem(BaseModel):
    """One analyzed entry inside the brief. URL is grounded to collected inputs."""

    title: str = Field(..., min_length=1, max_length=300)
    url: str
    summary: str = Field(..., min_length=1, max_length=600)
    insight: str = Field(default="", max_length=600, description="Why it matters for the reader")
    importance: int = Field(..., ge=1, le=10)
    category: str = Field(default="general", max_length=60)
    status: DiffStatus = DiffStatus.NEW

    @field_validator("url")
    @classmethod
    def _grounded(cls, v: str, info: ValidationInfo) -> str:
        ctx = info.context or {}
        allowed: set[str] | None = ctx.get("allowed_urls")
        if allowed is not None and normalize_url(v) not in allowed:
            raise ValueError(f"url not in collected inputs (hallucination guard): {v}")
        return v


class AnalyzedTrendBrief(BaseModel):
    """Final briefing document produced by the LLM (or the extractive fallback)."""

    preset: str = "default"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    headline: str = Field(..., min_length=1, max_length=200)
    overview: str = Field(..., min_length=1, max_length=1500)
    items: list[BriefItem] = Field(default_factory=list)
    rising_keywords: list[str] = Field(default_factory=list, max_length=20)
    source_errors: list[SourceError] = Field(default_factory=list)
    provider: str = Field(default="none", description="LLM provider that produced this brief")
    model: str = "none"
    degraded: bool = Field(default=False, description="True if produced without an LLM")
    stats: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sort_items(self) -> AnalyzedTrendBrief:
        self.items.sort(key=lambda i: i.importance, reverse=True)
        return self


def allowed_url_set(items: list[RawTrendItem]) -> set[str]:
    return {normalize_url(i.url) for i in items}
