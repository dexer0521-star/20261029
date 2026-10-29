import pytest
from pydantic import ValidationError

from src.analyzers.schemas import (
    AnalyzedTrendBrief,
    BriefItem,
    RawTrendItem,
    item_id_for,
    normalize_url,
)


def test_normalize_url_strips_tracking_and_case():
    assert normalize_url("https://Example.com/a/?utm_source=x&id=1#frag") == "https://example.com/a?id=1"
    assert item_id_for("https://example.com/a/?utm_source=x") == item_id_for("https://EXAMPLE.com/a")


def test_raw_item_rejects_non_http():
    with pytest.raises(ValidationError):
        RawTrendItem(source="s", title="t", url="ftp://nope.example/x")


def test_brief_item_grounding_guard():
    allowed = {normalize_url("https://a.com/1")}
    BriefItem.model_validate(
        {"title": "ok", "url": "https://a.com/1/", "summary": "s", "importance": 5},
        context={"allowed_urls": allowed},
    )
    with pytest.raises(ValidationError, match="hallucination guard"):
        BriefItem.model_validate(
            {"title": "bad", "url": "https://evil.com/x", "summary": "s", "importance": 5},
            context={"allowed_urls": allowed},
        )


def test_brief_sorts_by_importance():
    b = AnalyzedTrendBrief(
        headline="h",
        overview="o",
        items=[
            BriefItem(title="low", url="https://a.com/1", summary="s", importance=2),
            BriefItem(title="high", url="https://a.com/2", summary="s", importance=9),
        ],
    )
    assert [i.title for i in b.items] == ["high", "low"]
