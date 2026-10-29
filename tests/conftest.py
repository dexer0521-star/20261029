from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.analyzers.schemas import DiffStatus, DiffTrendItem, RawTrendItem


@pytest.fixture
def raw_items() -> list[RawTrendItem]:
    now = datetime.now(UTC)
    return [
        RawTrendItem(
            source="hackernews",
            title="LLM agents everywhere",
            url="https://a.com/1",
            score=100,
            published_at=now,
        ),
        RawTrendItem(
            source="hackernews",
            title="Rust 2.0 released",
            url="https://a.com/2",
            score=50,
            published_at=now,
        ),
        RawTrendItem(source="rss:x", title="Fed holds rates", url="https://b.com/fed", published_at=now),
    ]


@pytest.fixture
def diff_items(raw_items: list[RawTrendItem]) -> list[DiffTrendItem]:
    out = []
    for rank, it in enumerate(raw_items, 1):
        out.append(
            DiffTrendItem(
                **it.model_dump(),
                rank=rank,
                status=DiffStatus.NEW if rank != 2 else DiffStatus.RISING,
            )
        )
    return out
