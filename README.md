<h1 align="center">cron-trend-agent</h1>
<p align="center">
  <b>Zero-server AI trend briefing agent.</b><br/>
  Fork it · add one API key to Secrets · get a ranked, diffed, LLM-written brief in Slack / Notion / email every morning.<br/>
  Runs entirely on the free GitHub Actions scheduler. No VPS, no Zapier, no database.
</p>
<p align="center">
  <a href="#-5-minute-quickstart">Quickstart</a> ·
  <a href="#-presets">Presets</a> ·
  <a href="#-configuration">Config</a> ·
  <a href="#-extend-in-one-file">Extend</a> ·
  <a href="README.ko.md">한국어</a>
</p>

---

## Why this and not "an RSS summary script"?

| | cron-trend-agent | typical digest script |
|---|---|---|
| **Diff vs. yesterday** | 🆕 NEW / 🔥 RISING / 🔻 FALLING per item, score & rank deltas, rising keywords | re-sends the same list |
| **Works with zero keys** | `--dry-run` produces a real brief from bundled samples | crashes on missing key |
| **Hallucination guard** | every link in the brief must exist in the collected inputs (Pydantic validator) | trusts the model |
| **Never dies** | per-source & per-notifier isolation, LLM primary → fallback → no-LLM extract | one 429 kills the run |
| **State without a DB** | one JSON file persisted with Actions cache | needs Redis / S3 |
| **Extend** | one file + `@register("type")` | edit the main loop |

```
collect (HN · RSS · Reddit · Apify)  →  filter  →  diff vs last run  →  LLM (Gemini → Claude → OpenAI → extractive)
      →  Slack Block Kit · Notion page · Markdown · Email  →  save state (.state/last_run.json)
```

## ⚡ 5-minute quickstart

**0. Try it without any keys (local, offline)**
```bash
git clone https://github.com/<you>/cron-trend-agent && cd cron-trend-agent
uv venv && uv pip install -e .            # or: pip install -e .
python -m src.main --dry-run              # → output/latest_brief.md
```

**1. Fork** this repo (or *Use this template*).

**2. Dry-run in the cloud**: *Actions* → **Daily Trend Brief** → *Run workflow* → tick `dry_run`.
The job is green with no secrets; download the `trend-brief-*` artifact to see the sample brief.

**3. Add one LLM key** in *Settings → Secrets and variables → Actions*:
`GEMINI_API_KEY` (free tier) — or `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`. The router uses whichever exists.

**4. Add a channel**: `SLACK_WEBHOOK_URL` (Incoming Webhook). Optional: `NOTION_TOKEN` + `NOTION_DATABASE_ID`,
SMTP vars for email (see `config/config.example.yaml`).

**5. Run workflow again** (untick dry_run). Your first real brief lands in Slack. The schedule
(`30 22 * * *` UTC = 07:30 KST) now runs daily — edit the cron in `.github/workflows/daily-brief.yml`.

## 🎛 Presets

| Preset | Sources | Audience |
|---|---|---|
| `ai-tech-news` | Hacker News, TechCrunch AI, The Verge AI | engineers tracking AI tooling |
| `kbeauty-commerce` | r/AsianBeauty, Google News (K-beauty, Amazon beauty), Apify (opt-in) | K-beauty sellers & marketers (Korean output) |
| `quant-macro` | Fed press releases, CNBC Economy, Google News (CPI/FOMC/yields) | systematic traders |

```bash
python -m src.main --preset ai-tech-news            # real run
python -m src.main --preset quant-macro --no-notify # LLM yes, delivery no (markdown only)
```
In the workflow pick the preset from the *Run workflow* dropdown, or copy one to `config/config.yaml`.

## ⚙️ Configuration

`config/config.yaml` (copy from `config.example.yaml`). Secrets are **never** in YAML — only the env var *name*:

```yaml
sources:
  - { name: hackernews, type: hackernews, limit: 30, min_score: 50, params: { feed: top } }
  - { name: rss:techcrunch, type: rss, params: { feeds: [https://techcrunch.com/feed/] } }
filters: { exclude_keywords: [hiring, sponsored], max_age_hours: 48, max_items: 40, only_fresh: false }
llm:
  primary:   { provider: gemini, model: gemini-2.5-flash, api_key_env: GEMINI_API_KEY }
  fallbacks: [{ provider: claude, model: claude-haiku-5-5, api_key_env: ANTHROPIC_API_KEY }]
  language: en
  audience: "developers and indie hackers"
notifiers:
  - { type: markdown, path: output }
  - { type: slack, webhook_env: SLACK_WEBHOOK_URL }
state: { path: .state/last_run.json, rising_score_delta: 50, rising_rank_jump: 5 }
```
Unknown keys fail fast with a clear Pydantic error. Full reference: [`docs/TECH_SPEC.md`](docs/TECH_SPEC.md).

### CLI
| Flag | Effect |
|---|---|
| `--config PATH` / `--preset NAME` | which YAML to load |
| `--dry-run` | offline: sample data, mock LLM, markdown only — always exit 0 |
| `--no-llm` · `--no-notify` · `--no-state` | skip a stage |
| `--summary-json PATH` | machine-readable run summary (also printed) |
Exit codes: `0` brief produced (possibly degraded) · `2` every source failed · `3` invalid config.

## 🛡 What happens when things break

| Failure | Behaviour |
|---|---|
| One feed 429s / times out | other sources continue; brief footer lists `⚠️ sources failed` |
| Primary LLM down or key missing | next provider; if all fail → ranked *extractive* brief marked `degraded` |
| Model invents a URL | item dropped by the grounding validator; logged |
| Model returns broken JSON | one repair prompt, then next provider |
| Every source failed | state is **not** overwritten; job exits 2 so GitHub emails you |
| Slack down | Notion/markdown still delivered; artifact always uploaded |

## 🧩 Extend in one file

```python
# src/collectors/producthunt.py
from src.collectors.base import BaseCollector, register


@register("producthunt")
class ProductHuntCollector(BaseCollector):
    async def fetch(self, client):  # may raise – the runner isolates it
        data = (await self._get(client, "https://api.producthunt.com/...")).json()
        return [self._item(title=p["name"], url=p["url"], score=p["votes"]) for p in data]

    def sample(self):  # offline fixture for --dry-run
        return [self._item(title="Sample PH launch", url="https://example.com/ph/1", score=42)]
```
Add `from src.collectors import producthunt` to `src/collectors/__init__.py`, then
`- { name: ph, type: producthunt }` in your YAML. Notifiers work the same way (`src/notifiers/base.py`).

## 🧪 Development
```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest -q            # offline test-suite (respx mocks)
uv run ruff check . && uv run ruff format .
```
`CLAUDE.md` holds the architecture rules if you develop with Claude Code.

## Roadmap
- [ ] Commit state to a `state` branch (opt-in) for history beyond cache retention
- [ ] Discord / Telegram notifiers
- [ ] Product Hunt, GitHub Trending, YouTube collectors
- [ ] Weekly roll-up brief

## License
MIT — see [LICENSE](LICENSE). If this saved you a server bill, a ⭐ helps others find it.
