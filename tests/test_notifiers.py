import json

import httpx
import pytest
import respx

from src.analyzers.schemas import AnalyzedTrendBrief, BriefItem, SourceError
from src.config_loader import NotifierConfig
from src.notifiers import run_notifiers
from src.notifiers.markdown_notifier import render_markdown
from src.notifiers.notion_notifier import build_children
from src.notifiers.slack_notifier import build_blocks


@pytest.fixture
def brief() -> AnalyzedTrendBrief:
    return AnalyzedTrendBrief(
        preset="t",
        headline="Headline",
        overview="Overview text",
        rising_keywords=["llm"],
        items=[
            BriefItem(
                title=f"item {i}",
                url=f"https://a.com/{i}",
                summary="s",
                insight="why",
                importance=min(i, 10),
            )
            for i in range(1, 13)
        ],
        source_errors=[SourceError(source="reddit:x", error="HTTP 429")],
    )


def test_markdown_render_contains_links_and_warnings(brief):
    md = render_markdown(brief)
    assert "[item 12](https://a.com/12)" in md and "Source warnings" in md and "`llm`" in md


def test_slack_blocks_within_limits(brief):
    blocks = build_blocks(brief, max_items=10)
    assert blocks[0]["type"] == "header" and len(blocks) <= 50
    assert json.dumps(blocks)  # serialisable


def test_notion_children_capped(brief):
    assert 0 < len(build_children(brief)) <= 100


async def test_markdown_notifier_writes_files(tmp_path, brief):
    res = await run_notifiers([NotifierConfig(type="markdown", path=str(tmp_path))], brief, dry_run=True)
    assert res[0].ok and (tmp_path / "latest_brief.md").exists() and (tmp_path / "latest_brief.json").exists()


async def test_slack_missing_secret_is_skipped_not_fatal(monkeypatch, brief):
    monkeypatch.delenv("CTA_SLACK", raising=False)
    res = await run_notifiers([NotifierConfig(type="slack", webhook_env="CTA_SLACK")], brief, dry_run=False)
    assert res[0].skipped and not res[0].ok


@respx.mock
async def test_slack_posts_webhook(monkeypatch, brief):
    monkeypatch.setenv("CTA_SLACK", "https://hooks.slack.com/services/T/B/x")
    route = respx.post("https://hooks.slack.com/services/T/B/x").mock(return_value=httpx.Response(200, text="ok"))
    res = await run_notifiers([NotifierConfig(type="slack", webhook_env="CTA_SLACK")], brief, dry_run=False)
    assert route.called and res[0].ok


@respx.mock
async def test_slack_http_error_reported(monkeypatch, brief):
    monkeypatch.setenv("CTA_SLACK", "https://hooks.slack.com/services/T/B/y")
    respx.post("https://hooks.slack.com/services/T/B/y").mock(return_value=httpx.Response(500, text="boom"))
    res = await run_notifiers([NotifierConfig(type="slack", webhook_env="CTA_SLACK")], brief, dry_run=False)
    assert not res[0].ok and "500" in res[0].detail
