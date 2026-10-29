# Technical Specification — cron-trend-agent

Maps 1:1 to the code. Read with `CLAUDE.md` for the rules behind the design.

## 1. Repository layout
```
src/
  main.py                 CLI: --config/--preset/--dry-run/--no-llm/--no-notify, exit codes 0/2/3
  config_loader.py        AppConfig (Pydantic, extra=forbid), load_config(), resolve_env()
  filters.py              dedupe(), apply_filters(), select_for_llm()
  collectors/             BaseCollector + registry; hackernews, rss, reddit, apify
  storage/state_manager.py  RunState JSON, diff(), rising_keywords()
  analyzers/
    schemas.py            RawTrendItem → DiffTrendItem → AnalyzedTrendBrief (+ grounding validator)
    prompts.py            SYSTEM_PROMPT, build_user_prompt(), repair_prompt()
    providers.py          Gemini / Claude / OpenAI REST adapters + MockProvider
    llm_router.py         primary → fallbacks → extractive; JSON repair; URL grounding
    fallback.py           build_extractive_brief() (no LLM)
  notifiers/              BaseNotifier + registry; markdown, slack, notion, email
config/config.example.yaml, config/presets/{ai-tech-news,kbeauty-commerce,quant-macro}.yaml
.github/workflows/daily-brief.yml
```

## 2. `config.yaml` schema (→ `config_loader.AppConfig`)
| Key | Type | Notes |
|---|---|---|
| `name`, `description`, `timezone` | str | `name` becomes the brief's preset label |
| `sources[]` | `SourceConfig` | `name` (unique), `type` ∈ hackernews/rss/reddit/apify, `enabled`, `limit`, `min_score`, `params{}` |
| `filters` | `FilterConfig` | `include_keywords[]` (ANY), `exclude_keywords[]`, `max_age_hours`, `max_items`, `only_fresh` |
| `llm.primary`, `llm.fallbacks[]` | `ProviderConfig` | `provider` ∈ gemini/claude/openai/mock, `model`, `api_key_env`, `timeout_seconds` |
| `llm.*` | | `language`, `audience`, `max_brief_items`, `temperature`, `extra_instructions` |
| `notifiers[]` | `NotifierConfig` | `type` ∈ markdown/slack/notion/email, `enabled`, `webhook_env`, `token_env`, `database_id_env`, `path`, `params{}` |
| `state` | `StateConfig` | `path`, `rising_score_delta`, `rising_rank_jump`, `keep_runs` |

Secrets: YAML holds **env var names** only; `resolve_env(name, required)` reads them and raises `MissingSecret`.

## 3. Data pipeline schemas (`analyzers/schemas.py`)
```
RawTrendItem      id(sha1(normalize_url)[:16]) source title url score? comments? published_at? summary? tags[] extra{}
DiffTrendItem     + status(NEW|RISING|STEADY|FALLING) rank prev_rank? prev_score? score_delta? rank_delta? seen_runs
BriefItem         title url summary insight importance(1-10) category status      ← url grounded via context
AnalyzedTrendBrief preset generated_at headline overview items[] rising_keywords[] source_errors[] provider model degraded stats{}
```
Grounding: `BriefItem.model_validate(row, context={"allowed_urls": {normalize_url(u) …}})`.
`normalize_url` lowercases host, strips fragment, trailing slash and `utm_*/fbclid/gclid/ref=` params.

## 4. StateManager algorithm (`storage/state_manager.py`)
```
load():   RunState.model_validate_json(path) or fresh RunState on missing/corrupt file
diff(items):
  ranked = sort by (score desc, published_at desc)
  for rank, item: old = prev[item.id]
    none      → NEW
    else      score_delta = score - old.score ; rank_delta = old.rank - rank
              RISING  if score_delta >= S or rank_delta >= R (and not falling)
              FALLING if score_delta <= -S or rank_delta <= -R (and not rising)
              STEADY  otherwise ; seen_runs = old.seen_runs + 1
rising_keywords(items): tokens in >=2 current titles whose count exceeds mean count over title_history
save(items): write RunState{run_at, items{id→ItemSnapshot}, title_history[-keep_runs:]}
```
Persistence in Actions: `actions/cache/restore` (prefix restore-key) before, `actions/cache/save` (`if: always()`)
after. Only saved when ≥1 source succeeded, so a fully-failed run never wipes good state.

## 5. Collector / Notifier plugin interface
```python
@register("mysource")  # collectors/base.py
class MyCollector(BaseCollector):
    async def fetch(self, client: httpx.AsyncClient) -> list[RawTrendItem]: ...  # may raise
    def sample(self) -> list[RawTrendItem]: ...  # offline fixture (--dry-run)


@register("mychannel")  # notifiers/base.py
class MyNotifier(BaseNotifier):
    needs_network = True  # False → also runs in --dry-run

    async def send(self, brief: AnalyzedTrendBrief, client: httpx.AsyncClient) -> str: ...  # may raise
```
`run_collectors()` / `run_notifiers()` gather all plugins concurrently and convert exceptions into
`CollectResult.error` / `NotifyResult.detail`. `MissingSecret` from a notifier = *skipped*, not failed.

## 6. LLM router (`analyzers/llm_router.py`)
1. Build provider chain `[primary, *fallbacks]`; drop entries whose key env var is unset (`dry_run` → Mock only).
2. For each provider: call (tenacity ×2 on transport/HTTP errors) → strip fences → `json.loads` →
   per-item grounding validation (bad URLs dropped; all bad = error) → `AnalyzedTrendBrief`.
   On parse/validation error send one `repair_prompt` to the same provider, then move on.
3. All failed → `build_extractive_brief()` with `degraded=True` (ranked raw items, no prose).
`LLMRouter.attempts` records the chain for the run summary.

## 7. CLI contract (`main.py`)
| Flag | Effect |
|---|---|
| `--config PATH` / `--preset NAME` | mutually exclusive; default `config/config.yaml` → falls back to the example |
| `--dry-run` | sample data, MockProvider, network notifiers skipped, exit 0 |
| `--no-llm` / `--no-notify` / `--no-state` | skip the respective step |
| `--state-path`, `--output-dir`, `--summary-json` | overrides for CI/tests |
Exit codes: `0` brief produced (may be degraded) · `2` every source failed · `3` config invalid.
Writes `$GITHUB_STEP_SUMMARY` when present.

## 8. Workflow (`.github/workflows/daily-brief.yml`)
schedule + `workflow_dispatch(preset, dry_run)` → setup-uv → restore state → run (`continue-on-error`) →
upload `output/` artifact (always) → save state (always, if file exists) → fail job only on agent exit ≠ 0.
