import json

import httpx
import pytest

from src.analyzers.llm_router import LLMRouter
from src.analyzers.providers import LLMProvider
from src.config_loader import LLMConfig, ProviderConfig


def _cfg(**kw) -> LLMConfig:
    return LLMConfig(primary=ProviderConfig(provider="mock", model="m"), **kw)


async def test_mock_provider_is_grounded(diff_items):
    brief = await LLMRouter(_cfg(), dry_run=True).analyze(diff_items, preset="t", rising_keywords=["llm"])
    assert brief.provider == "mock" and not brief.degraded
    assert {i.url for i in brief.items} <= {i.url for i in diff_items}
    assert brief.items[0].status.value in {"new", "rising"}


async def test_disabled_router_uses_extractive(diff_items):
    brief = await LLMRouter(_cfg(), disabled=True).analyze(diff_items, preset="t", rising_keywords=[])
    assert brief.degraded and brief.model == "extractive" and len(brief.items) == 3


async def test_hallucinated_urls_are_dropped(monkeypatch, diff_items):
    class Fake(LLMProvider):
        async def complete_json(self, client, system, user, temperature):
            return json.dumps(
                {
                    "headline": "h",
                    "overview": "o",
                    "items": [
                        {
                            "title": "real",
                            "url": "https://a.com/1",
                            "summary": "s",
                            "importance": 7,
                        },
                        {
                            "title": "fake",
                            "url": "https://made.up/x",
                            "summary": "s",
                            "importance": 9,
                        },
                    ],
                }
            )

    router = LLMRouter(_cfg())
    monkeypatch.setattr(router, "_providers", lambda: [Fake(ProviderConfig(provider="mock", model="f"), None)])
    brief = await router.analyze(diff_items, preset="t", rising_keywords=[])
    assert [i.title for i in brief.items] == ["real"]


async def test_all_providers_fail_falls_back(monkeypatch, diff_items):
    class Boom(LLMProvider):
        async def complete_json(self, client, system, user, temperature):
            raise httpx.ConnectError("down")

    router = LLMRouter(_cfg())
    monkeypatch.setattr(router, "_providers", lambda: [Boom(ProviderConfig(provider="mock", model="b"), None)])
    brief = await router.analyze(diff_items, preset="t", rising_keywords=[])
    assert brief.degraded and any("ConnectError" in a for a in router.attempts)


async def test_no_keys_means_extractive(monkeypatch, diff_items):
    for k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    cfg = LLMConfig(primary=ProviderConfig(provider="gemini", model="g", api_key_env="GEMINI_API_KEY"))
    brief = await LLMRouter(cfg).analyze(diff_items, preset="t", rising_keywords=[])
    assert brief.degraded


@pytest.mark.parametrize("fence", ["```json\n{}\n```", "{}"])
def test_parse_strips_fences(fence):
    from src.analyzers.providers import MockProvider

    prov = MockProvider(ProviderConfig(provider="mock", model="m"), None)
    raw = fence.replace("{}", json.dumps({"headline": "h", "overview": "o", "items": []}))
    brief = LLMRouter._parse(raw, set(), "t", prov, {})
    assert brief.headline == "h"
