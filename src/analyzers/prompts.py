"""Prompt builders. The LLM only ever sees collected items; output must cite their URLs."""

from __future__ import annotations

import json

from src.analyzers.schemas import DiffTrendItem
from src.config_loader import LLMConfig

SYSTEM_PROMPT = """You are a sharp research analyst writing a daily trend brief.
Rules (strict):
1. Use ONLY the items provided. Every `url` in your output MUST be copied verbatim from the input.
   Never invent links, numbers, dates, or sources. If unsure, omit the item.
2. Return ONLY a single JSON object matching the schema. No markdown fences, no commentary.
3. `summary` <= 2 sentences, factual. `insight` = why it matters / what to do, <= 2 sentences.
4. `importance` 1-10: 10 = must-read for this audience today. Prefer NEW and RISING items.
5. Write in the requested language. Keep titles close to the original."""

OUTPUT_SCHEMA = {
    "headline": "string, <= 120 chars, the single most important takeaway",
    "overview": "string, 2-4 sentences summarising the day",
    "items": [
        {
            "title": "string",
            "url": "string (verbatim from input)",
            "summary": "string",
            "insight": "string",
            "importance": "integer 1-10",
            "category": "short string, e.g. 'ai-models', 'funding', 'macro', 'product'",
        }
    ],
    "rising_keywords": ["string"],
}


def _item_row(i: DiffTrendItem) -> dict:
    row: dict = {
        "rank": i.rank,
        "status": i.status.value,
        "source": i.source,
        "title": i.title,
        "url": i.url,
    }
    if i.score is not None:
        row["score"] = i.score
    if i.score_delta:
        row["score_delta"] = i.score_delta
    if i.rank_delta:
        row["rank_delta"] = i.rank_delta
    if i.comments:
        row["comments"] = i.comments
    if i.published_at:
        row["published_at"] = i.published_at.isoformat(timespec="minutes")
    if i.summary:
        row["snippet"] = i.summary[:300]
    return row


def build_user_prompt(items: list[DiffTrendItem], cfg: LLMConfig, rising_keywords: list[str], preset: str) -> str:
    payload = {
        "preset": preset,
        "audience": cfg.audience,
        "language": cfg.language,
        "max_items": cfg.max_brief_items,
        "rising_keywords_detected": rising_keywords,
        "items": [_item_row(i) for i in items],
    }
    extra = f"\nAdditional instructions: {cfg.extra_instructions}" if cfg.extra_instructions else ""
    return (
        f"Produce the brief for audience='{cfg.audience}' in language='{cfg.language}'. "
        f"Select at most {cfg.max_brief_items} items.{extra}\n\n"
        f"OUTPUT JSON SCHEMA:\n{json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, indent=1)}\n\n"
        f"INPUT:\n{json.dumps(payload, ensure_ascii=False, indent=1)}"
    )


def repair_prompt(error: str) -> str:
    return (
        "Your previous JSON was rejected by the validator:\n"
        f"{error[:1500]}\n"
        "Fix it. Remember: urls must be copied verbatim from INPUT; return JSON only."
    )
