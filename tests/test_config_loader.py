import pytest
from pydantic import ValidationError

from src.config_loader import AppConfig, MissingSecret, list_presets, load_config, resolve_env


def test_example_and_presets_load():
    cfg = load_config()
    assert cfg.enabled_sources and cfg.llm.primary.provider
    assert set(list_presets()) >= {"ai-tech-news", "kbeauty-commerce", "quant-macro"}
    for p in list_presets():
        c = load_config(preset=p)
        assert c.name == p and c.enabled_sources


def test_unknown_key_rejected():
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {
                "sources": [{"name": "a", "type": "rss"}],
                "llm": {"primary": {"provider": "mock", "model": "m"}},
                "bogus": 1,
            }
        )


def test_duplicate_source_names_rejected():
    with pytest.raises(ValidationError, match="duplicate"):
        AppConfig.model_validate(
            {
                "sources": [{"name": "a", "type": "rss"}, {"name": "a", "type": "rss"}],
                "llm": {"primary": {"provider": "mock", "model": "m"}},
            }
        )


def test_resolve_env(monkeypatch):
    monkeypatch.delenv("CTA_TEST_KEY", raising=False)
    with pytest.raises(MissingSecret):
        resolve_env("CTA_TEST_KEY")
    assert resolve_env("CTA_TEST_KEY", required=False) is None
    monkeypatch.setenv("CTA_TEST_KEY", " v ")
    assert resolve_env("CTA_TEST_KEY") == "v"
