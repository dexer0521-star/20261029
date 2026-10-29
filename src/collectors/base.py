"""Abstract collector + registry + graceful parallel runner.

To add a source: create `src/collectors/<name>.py`, subclass BaseCollector,
decorate with `@register("<type>")`, and import it in `collectors/__init__.py`.
A collector that raises never kills the run; its error is attached to the brief.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.analyzers.schemas import RawTrendItem
from src.config_loader import SourceConfig

log = logging.getLogger(__name__)

USER_AGENT = "cron-trend-agent/0.1 (+https://github.com/cron-trend-agent)"
DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)

_REGISTRY: dict[str, type[BaseCollector]] = {}


def register(source_type: str) -> Callable[[type[BaseCollector]], type[BaseCollector]]:
    def deco(cls: type[BaseCollector]) -> type[BaseCollector]:
        _REGISTRY[source_type] = cls
        cls.source_type = source_type
        return cls

    return deco


def get_collector_class(source_type: str) -> type[BaseCollector]:
    try:
        return _REGISTRY[source_type]
    except KeyError as exc:
        raise KeyError(f"no collector registered for type '{source_type}'") from exc


class CollectResult(BaseModel):
    source: str
    items: list[RawTrendItem] = Field(default_factory=list)
    error: str | None = None
    elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None


class BaseCollector(ABC):
    """Base class for all collectors."""

    source_type: str = "base"

    def __init__(self, config: SourceConfig) -> None:
        self.config = config
        self.name = config.name
        self.limit = config.limit
        self.params = config.params

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient) -> list[RawTrendItem]:
        """Hit the network and return raw items. Raise on hard failure."""

    @abstractmethod
    def sample(self) -> list[RawTrendItem]:
        """Offline fixture used by --dry-run (no network, no keys)."""

    def _item(self, **kwargs: object) -> RawTrendItem:
        kwargs.setdefault("source", self.name)
        return RawTrendItem.model_validate(kwargs)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        reraise=True,
    )
    async def _get(self, client: httpx.AsyncClient, url: str, **kw: object) -> httpx.Response:
        resp = await client.get(url, **kw)  # type: ignore[arg-type]
        resp.raise_for_status()
        return resp

    def _postfilter(self, items: list[RawTrendItem]) -> list[RawTrendItem]:
        out = [i for i in items if (i.score or 0) >= self.config.min_score]
        return out[: self.limit]

    async def collect(self, client: httpx.AsyncClient, *, dry_run: bool = False) -> CollectResult:
        started = datetime.now(UTC)
        try:
            items = self.sample() if dry_run else await self.fetch(client)
            items = self._postfilter(items)
            ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
            log.info("collector %s: %d items (%d ms)", self.name, len(items), ms)
            return CollectResult(source=self.name, items=items, elapsed_ms=ms)
        except Exception as exc:  # noqa: BLE001 - graceful degradation by design
            ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
            msg = f"{type(exc).__name__}: {str(exc)[:200]}"
            log.warning("collector %s FAILED: %s", self.name, msg)
            return CollectResult(source=self.name, error=msg, elapsed_ms=ms)


async def run_collectors(
    configs: list[SourceConfig], *, dry_run: bool = False, concurrency: int = 4
) -> list[CollectResult]:
    """Run every enabled collector concurrently; never raises."""
    sem = asyncio.Semaphore(concurrency)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, application/xml, */*"}

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=headers, follow_redirects=True) as client:

        async def _one(cfg: SourceConfig) -> CollectResult:
            async with sem:
                try:
                    collector = get_collector_class(cfg.type)(cfg)
                except KeyError as exc:
                    return CollectResult(source=cfg.name, error=str(exc))
                return await collector.collect(client, dry_run=dry_run)

        return list(await asyncio.gather(*(_one(c) for c in configs)))
