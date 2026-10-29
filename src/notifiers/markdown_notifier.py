"""Markdown notifier: writes output/latest_brief.md + a dated archive. Works offline."""

from __future__ import annotations

from pathlib import Path

import httpx

from src.analyzers.schemas import AnalyzedTrendBrief
from src.notifiers.base import STATUS_ICON, BaseNotifier, register


def render_markdown(brief: AnalyzedTrendBrief) -> str:
    ts = brief.generated_at.strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# {brief.headline}",
        "",
        f"_{brief.preset} · {ts} · {brief.provider}/{brief.model}_",
        "",
    ]
    if brief.degraded:
        lines += ["> ⚠️ Generated without an LLM (extractive mode).", ""]
    lines += [brief.overview, ""]
    if brief.rising_keywords:
        lines += ["**Rising keywords:** " + ", ".join(f"`{k}`" for k in brief.rising_keywords), ""]
    lines += ["## Top items", ""]
    for n, it in enumerate(brief.items, 1):
        icon = STATUS_ICON.get(it.status, "")
        lines.append(f"### {n}. {icon} [{it.title}]({it.url})")
        lines.append(f"**Importance {it.importance}/10** · `{it.category}`  ")
        lines.append(it.summary)
        if it.insight:
            lines.append(f"\n> 💡 {it.insight}")
        lines.append("")
    if brief.source_errors:
        lines += ["## ⚠️ Source warnings", ""]
        lines += [f"- `{e.source}`: {e.error}" for e in brief.source_errors]
        lines.append("")
    if brief.stats:
        lines += ["---", "", " · ".join(f"{k}: {v}" for k, v in brief.stats.items()), ""]
    return "\n".join(lines)


@register("markdown")
class MarkdownNotifier(BaseNotifier):
    needs_network = False

    async def send(self, brief: AnalyzedTrendBrief, client: httpx.AsyncClient) -> str:
        out_dir = Path(self.config.path or "output")
        out_dir.mkdir(parents=True, exist_ok=True)
        text = render_markdown(brief)
        latest = out_dir / "latest_brief.md"
        latest.write_text(text, encoding="utf-8")
        dated = out_dir / f"brief_{brief.generated_at.strftime('%Y-%m-%d')}.md"
        dated.write_text(text, encoding="utf-8")
        (out_dir / "latest_brief.json").write_text(brief.model_dump_json(indent=2), encoding="utf-8")
        return f"wrote {latest} (+ {dated.name}, latest_brief.json)"
