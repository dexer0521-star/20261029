"""Abstract notifier + registry + graceful runner (one channel failing never blocks others)."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable

import httpx
from pydantic import BaseModel

from src.analyzers.schemas import AnalyzedTrendBrief, DiffStatus
from src.config_loader import MissingSecret, NotifierConfig

log = logging.getLogger(__name__)
_REGISTRY: dict[str, type[BaseNotifier]] = {}

STATUS_ICON = {
    DiffStatus.NEW: "🆕",
    DiffStatus.RISING: "🔥",
    DiffStatus.STEADY: "▫️",
    DiffStatus.FALLING: "🔻",
}


def register(kind: str) -> Callable[[type[BaseNotifier]], type[BaseNotifier]]:
    def deco(cls: type[BaseNotifier]) -> type[BaseNotifier]:
        _REGISTRY[kind] = cls
        cls.kind = kind
        return cls

    return deco


class NotifyResult(BaseModel):
    notifier: str
    ok: bool
    detail: str = ""
    skipped: bool = False


class BaseNotifier(ABC):
    kind: str = "base"
    needs_network: bool = True

    def __init__(self, config: NotifierConfig) -> None:
        self.config = config

    @abstractmethod
    async def send(self, brief: AnalyzedTrendBrief, client: httpx.AsyncClient) -> str:
        """Deliver the brief. Return a short human-readable detail. Raise on failure."""

    async def run(self, brief: AnalyzedTrendBrief, client: httpx.AsyncClient, *, dry_run: bool) -> NotifyResult:
        if dry_run and self.needs_network:
            return NotifyResult(
                notifier=self.kind,
                ok=True,
                skipped=True,
                detail="dry-run: network notifier skipped",
            )
        try:
            detail = await self.send(brief, client)
            log.info("notifier %s: %s", self.kind, detail)
            return NotifyResult(notifier=self.kind, ok=True, detail=detail)
        except MissingSecret as exc:
            log.warning("notifier %s skipped: %s", self.kind, exc)
            return NotifyResult(notifier=self.kind, ok=False, skipped=True, detail=str(exc))
        except Exception as exc:  # noqa: BLE001 - graceful degradation
            msg = f"{type(exc).__name__}: {str(exc)[:200]}"
            log.error("notifier %s FAILED: %s", self.kind, msg)
            return NotifyResult(notifier=self.kind, ok=False, detail=msg)


async def run_notifiers(
    configs: list[NotifierConfig], brief: AnalyzedTrendBrief, *, dry_run: bool
) -> list[NotifyResult]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        tasks = []
        for cfg in configs:
            cls = _REGISTRY.get(cfg.type)
            if cls is None:
                tasks.append(
                    asyncio.sleep(
                        0,
                        result=NotifyResult(notifier=cfg.type, ok=False, detail="unknown notifier type"),
                    )
                )
                continue
            tasks.append(cls(cfg).run(brief, client, dry_run=dry_run))
        return list(await asyncio.gather(*tasks))
