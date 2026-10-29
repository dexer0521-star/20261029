"""No-LLM extractive brief: used when every provider fails or no key is configured."""

from __future__ import annotations

from src.analyzers.schemas import AnalyzedTrendBrief, BriefItem, DiffStatus, DiffTrendItem


def _importance(i: DiffTrendItem, n: int) -> int:
    base = max(1, 10 - (i.rank - 1) * 9 // max(n, 1))
    if i.status == DiffStatus.RISING:
        base = min(10, base + 1)
    return base


def build_extractive_brief(
    items: list[DiffTrendItem], *, preset: str, max_items: int, rising_keywords: list[str]
) -> AnalyzedTrendBrief:
    chosen = items[:max_items]
    fresh = sum(1 for i in items if i.is_fresh)
    brief_items = [
        BriefItem(
            title=i.title,
            url=i.url,
            summary=(
                i.summary or f"{i.source} · rank #{i.rank}" + (f" · {i.score} pts" if i.score is not None else "")
            )[:600],
            insight="",
            importance=_importance(i, len(chosen)),
            category=i.source.split(":")[0],
            status=i.status,
        )
        for i in chosen
    ]
    return AnalyzedTrendBrief(
        preset=preset,
        headline=f"{len(items)} items collected · {fresh} new/rising (no-LLM mode)",
        overview=(
            "The LLM step was unavailable, so this is a ranked extract of the raw items. "
            "Links and scores are untouched source data."
        ),
        items=brief_items,
        rising_keywords=rising_keywords,
        provider="none",
        model="extractive",
        degraded=True,
    )
