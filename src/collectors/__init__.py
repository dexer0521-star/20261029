"""Collectors: one file per data source. Register with @register("type")."""

# Import built-in collectors so they self-register.
from src.collectors import apify, hackernews, reddit, rss  # noqa: E402, F401
from src.collectors.base import BaseCollector, CollectResult, register, run_collectors  # noqa: F401
