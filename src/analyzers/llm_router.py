"""LLMRouter: primary -> fallbacks -> extractive. Output validated + URL-grounded."""

from __future__ import annotations

import json
import logging

import httpx
from pydantic import ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.analyzers.fallback import build_extractive_brief
from src.analyzers.prompts import SYSTEM_PROMPT, build_user_prompt, repair_prompt
from src.analyzers.providers import LLMProvider, build_provider
from src.analyzers.schemas import (
    AnalyzedTrendBrief,
    BriefItem,
    DiffStatus,
    DiffTrendItem,
    allowed_url_set,
    normalize_url,
)
from src.config_loader import LLMConfig, MissingSecret

log = logging.getLogger(__name__)


class LLMRouter:
    def __init__(self, cfg: LLMConfig, *, dry_run: bool = False, disabled: bool = False) -> None:
        self.cfg = cfg
        self.dry_run = dry_run
        self.disabled = disabled
        self.attempts: list[str] = []

    def _providers(self) -> list[LLMProvider]:
        chain = [self.cfg.primary] + self.cfg.fallbacks
        if self.dry_run:
            return [build_provider(chain[0], dry_run=True)]
        built: list[LLMProvider] = []
        for pc in chain:
            try:
                built.append(build_provider(pc))
            except MissingSecret as exc:
                log.info("skip %s/%s: %s", pc.provider, pc.model, exc)
                self.attempts.append(f"{pc.provider}: no key")
        return built

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        reraise=True,
    )
    async def _call(self, provider: LLMProvider, client: httpx.AsyncClient, system: str, user: str) -> str:
        return await provider.complete_json(client, system, user, self.cfg.temperature)

    @staticmethod
    def _parse(
        raw: str,
        allowed: set[str],
        preset: str,
        provider: LLMProvider,
        status_by_url: dict[str, DiffStatus],
    ) -> AnalyzedTrendBrief:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`").split("\n", 1)[1] if "\n" in text else text.strip("`")
            text = text.removesuffix("```").strip()
        data = json.loads(text)
        data.setdefault("preset", preset)
        data["provider"], data["model"] = provider.name, provider.model
        items = data.get("items") or []
        # Drop items with hallucinated urls instead of failing the whole brief; fail only if all are bad.
        kept, dropped = [], []
        for row in items:
            try:
                parsed = BriefItem.model_validate(row, context={"allowed_urls": allowed})
                parsed.status = status_by_url.get(normalize_url(parsed.url), parsed.status)
                kept.append(parsed.model_dump())
            except ValidationError as exc:
                dropped.append(f"{row.get('url')}: {exc.errors()[0]['msg']}")
        if items and not kept:
            raise ValueError("every item was rejected by the grounding validator: " + "; ".join(dropped[:5]))
        if dropped:
            log.warning("grounding guard dropped %d item(s): %s", len(dropped), dropped[:3])
        data["items"] = kept
        return AnalyzedTrendBrief.model_validate(data, context={"allowed_urls": allowed})

    async def analyze(
        self, items: list[DiffTrendItem], *, preset: str, rising_keywords: list[str]
    ) -> AnalyzedTrendBrief:
        allowed = allowed_url_set(items)
        status_by_url = {normalize_url(i.url): i.status for i in items}
        if self.disabled or not items:
            return build_extractive_brief(
                items,
                preset=preset,
                max_items=self.cfg.max_brief_items,
                rising_keywords=rising_keywords,
            )
        user = build_user_prompt(items, self.cfg, rising_keywords, preset)
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0)) as client:
            for provider in self._providers():
                label = f"{provider.name}/{provider.model}"
                try:
                    raw = await self._call(provider, client, SYSTEM_PROMPT, user)
                    try:
                        brief = self._parse(raw, allowed, preset, provider, status_by_url)
                    except (ValueError, ValidationError, KeyError) as exc:
                        log.warning("%s produced invalid JSON (%s); asking for a repair", label, exc)
                        raw = await self._call(provider, client, SYSTEM_PROMPT, f"{user}\n\n{repair_prompt(str(exc))}")
                        brief = self._parse(raw, allowed, preset, provider, status_by_url)
                    self.attempts.append(f"{label}: ok")
                    log.info("LLM brief produced by %s (%d items)", label, len(brief.items))
                    return brief
                except Exception as exc:  # noqa: BLE001 - try the next provider
                    msg = f"{type(exc).__name__}: {str(exc)[:160]}"
                    self.attempts.append(f"{label}: {msg}")
                    log.warning("%s failed: %s", label, msg)
        log.error("all LLM providers failed (%s); using extractive fallback", self.attempts)
        return build_extractive_brief(
            items,
            preset=preset,
            max_items=self.cfg.max_brief_items,
            rising_keywords=rising_keywords,
        )
