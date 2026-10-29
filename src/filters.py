"""Keyword / age / cap filters applied after merge, before diff + LLM."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from src.analyzers.schemas import DiffTrendItem, RawTrendItem
from src.config_loader import FilterConfig

log = logging.getLogger(__name__)


def _matches(text: str, keywords: list[str]) -> bool:
    low = text.lower()
    return any(k.lower() in low for k in keywords)


def dedupe(items: list[RawTrendItem]) -> list[RawTrendItem]:
    """Keep the highest-scored copy of each normalized URL across sources."""
    best: dict[str, RawTrendItem] = {}
    for it in items:
        cur = best.get(it.id)
        if cur is None or (it.score or 0) > (cur.score or 0):
            best[it.id] = it
    return list(best.values())


def apply_filters(items: list[RawTrendItem], cfg: FilterConfig, *, now: datetime | None = None) -> list[RawTrendItem]:
    now = now or datetime.now(UTC)
    out: list[RawTrendItem] = []
    cutoff = now - timedelta(hours=cfg.max_age_hours) if cfg.max_age_hours else None
    for it in dedupe(items):
        haystack = f"{it.title} {it.summary or ''} {' '.join(it.tags)}"
        if cfg.include_keywords and not _matches(haystack, cfg.include_keywords):
            continue
        if cfg.exclude_keywords and _matches(haystack, cfg.exclude_keywords):
            continue
        if cutoff and it.published_at and it.published_at < cutoff:
            continue
        out.append(it)
    log.info("filters: %d -> %d items", len(items), len(out))
    return out


def select_for_llm(items: list[DiffTrendItem], cfg: FilterConfig) -> list[DiffTrendItem]:
    """Cap and (optionally) keep only NEW/RISING items for the LLM step."""
    chosen = [i for i in items if i.is_fresh] if cfg.only_fresh else list(items)
    if cfg.only_fresh and not chosen:  # nothing fresh: fall back to the full ranked list
        chosen = list(items)
    return chosen[: cfg.max_items]
