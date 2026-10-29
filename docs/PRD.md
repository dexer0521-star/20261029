# PRD — cron-trend-agent

> Zero-server AI trend briefing agent. Fork → add API keys to Secrets → get a daily brief in Slack/Notion/email.

## 1. Problem
People who need to watch a niche every day (AI tooling, K-beauty commerce, macro data) either pay for a server/Zapier
or hand-roll a fragile script that silently dies the first time a site blocks them or an LLM times out.

## 2. Target users
| Persona | Need | Why existing tools fail |
|---|---|---|
| Indie hacker / dev | Daily HN + RSS digest in Slack, zero ops | Cron on a VPS = cost + upkeep |
| Commerce marketer (K-beauty, Amazon) | Rising product/keyword signals | No-code tools are per-task priced |
| Quant / macro researcher | Fed, CPI, rates headlines at 7am | RSS readers don't rank or diff |

## 3. Core value
"Fork the repo, paste one API key into Secrets, and in 5 minutes you have a private AI research agent that
runs every morning for free."

## 4. Killer features (vs. "RSS summary script")
1. **Diff engine, not a digest** — every run is compared to the previous snapshot (`.state/last_run.json`,
   persisted via Actions cache). Items are tagged 🆕 NEW / 🔥 RISING / ▫️ STEADY / 🔻 FALLING with score and
   rank deltas, and *rising keywords* are computed from a rolling 7-run title window.
2. **`--dry-run` that actually works with zero keys** — every collector ships an offline `sample()`,
   the LLM has a `MockProvider`, network notifiers skip. New users see a real `output/latest_brief.md`
   before they configure anything. This is also the CI contract.
3. **Hallucination-proof briefs** — the LLM returns JSON validated by Pydantic; every `url` must match a
   collected URL (validator context). Fabricated links are dropped, never delivered.
4. **Never-dies pipeline** — per-source and per-notifier isolation, LLM primary → fallback → extractive
   (no-LLM) brief. A partial brief with a warning footer beats no brief.
5. **Plugin-in-one-file** — `@register("type")` on a `BaseCollector`/`BaseNotifier` subclass is the entire
   extension API.

## 5. 5-minute onboarding funnel
| Step | User action | Friction killer |
|---|---|---|
| 0 | Land on README | GIF of a Slack card + "Use this template" button |
| 1 | Fork / use template | No code change required; presets bundled |
| 2 | Actions tab → *Daily Trend Brief* → Run workflow → `dry_run: true` | Works with **no secrets**; artifact shows the sample brief |
| 3 | Add `GEMINI_API_KEY` (free tier) | Router works with any one provider key |
| 4 | Add `SLACK_WEBHOOK_URL` | Re-run workflow; first real card arrives |
| 5 | Pick a preset or edit `config/config.yaml` | YAML is validated; typos fail with a clear message |

## 6. Failure-tolerant Actions architecture
- `concurrency` group → one run at a time, state never written twice.
- `actions/cache/restore` + `restore-keys` prefix → previous state on every run; cache miss = first run.
- Agent step `continue-on-error: true`; artifact upload and state save run `if: always()`.
- Job fails only if the agent exits non-zero (all sources dead / config invalid) → you get an email from
  GitHub precisely when it matters, not on every flaky feed.
- Secrets are passed as env vars; the config names env vars only.

## 7. Non-goals (MVP)
Web UI, multi-tenant hosting, paid data sources by default, per-user auth, sending to >1 Slack workspace.

## 8. Success metrics
Time-to-first-brief < 5 min (measured via issue template), dry-run green on every PR, ≥3 presets,
≥2 community collectors within 3 months.

## 9. Open questions (answered defaults in parentheses)
1. Primary LLM for the default preset? (Gemini 2.5 Flash — free tier, JSON mode)
2. State storage: Actions cache vs. committed `state` branch? (cache; branch commit is an opt-in later)
3. Default run time? (22:30 UTC = 07:30 KST, user-editable cron)
4. Email: SMTP only or a provider API? (SMTP via stdlib, no new dependency)
5. Should Reddit/Apify be on by default? (off; both are rate-limited or keyed)
