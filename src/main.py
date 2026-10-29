"""CLI entrypoint.

    python -m src.main --dry-run                 # no keys, no network, writes output/latest_brief.md
    python -m src.main --preset ai-tech-news     # real run with a bundled preset
    python -m src.main --config config/my.yaml   # real run with your own config

Exit codes: 0 = brief produced (possibly degraded), 2 = every source failed, 3 = config error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from src import __version__
from src.analyzers.llm_router import LLMRouter
from src.analyzers.schemas import AnalyzedTrendBrief, SourceError
from src.collectors import run_collectors
from src.config_loader import AppConfig, list_presets, load_config
from src.filters import apply_filters, select_for_llm
from src.notifiers import run_notifiers
from src.storage.state_manager import StateManager

log = logging.getLogger("cron_trend_agent")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="cron-trend-agent", description="Zero-server AI trend briefing agent")
    p.add_argument("--config", help="path to a config YAML (default: config/config.yaml or the example)")
    p.add_argument("--preset", choices=list_presets() or None, help="bundled preset name")
    p.add_argument("--dry-run", action="store_true", help="offline mode: sample data, mock LLM, markdown only")
    p.add_argument("--no-llm", action="store_true", help="skip the LLM step (extractive brief)")
    p.add_argument("--no-notify", action="store_true", help="skip every notifier except markdown")
    p.add_argument("--no-state", action="store_true", help="do not persist state after this run")
    p.add_argument("--state-path", help="override state file path")
    p.add_argument("--output-dir", help="override markdown output dir")
    p.add_argument("--summary-json", help="write a machine-readable run summary here")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args(argv)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def run_pipeline(cfg: AppConfig, args: argparse.Namespace) -> tuple[AnalyzedTrendBrief, dict]:
    dry_run = bool(args.dry_run)
    summary: dict = {"preset": cfg.name, "dry_run": dry_run, "sources": {}, "notifiers": {}}

    # 1) collect (never raises; each source reports ok/error)
    results = await run_collectors(cfg.enabled_sources, dry_run=dry_run)
    raw = [i for r in results for i in r.items]
    errors = [SourceError(source=r.source, error=r.error) for r in results if r.error]
    summary["sources"] = {r.source: (r.error or f"{len(r.items)} items") for r in results}
    ok_sources = sum(1 for r in results if r.ok)

    # 2) filter + 3) diff against last run
    filtered = apply_filters(raw, cfg.filters)
    state = StateManager(cfg.state, args.state_path)
    state.load()
    diffed = state.diff(filtered)
    rising = state.rising_keywords(filtered)
    for_llm = select_for_llm(diffed, cfg.filters)

    # 4) analyze (primary -> fallbacks -> extractive)
    router = LLMRouter(cfg.llm, dry_run=dry_run, disabled=bool(args.no_llm))
    brief = await router.analyze(for_llm, preset=cfg.name, rising_keywords=rising)
    brief.source_errors = errors
    brief.stats = {
        "collected": len(raw),
        "after_filters": len(filtered),
        "new": sum(1 for i in diffed if i.status == "new"),
        "rising": sum(1 for i in diffed if i.status == "rising"),
        "sources_ok": ok_sources,
        "sources_failed": len(errors),
    }
    summary["llm_attempts"] = router.attempts
    summary["degraded"] = brief.degraded

    # 5) notify (markdown always; network notifiers skipped in dry-run / --no-notify)
    notifier_cfgs = cfg.enabled_notifiers
    if not any(n.type == "markdown" for n in notifier_cfgs):
        from src.config_loader import NotifierConfig

        notifier_cfgs = [NotifierConfig(type="markdown", path="output"), *notifier_cfgs]
    if args.output_dir:
        for n in notifier_cfgs:
            if n.type == "markdown":
                n.path = args.output_dir
    if args.no_notify:
        notifier_cfgs = [n for n in notifier_cfgs if n.type == "markdown"]
    notify_results = await run_notifiers(notifier_cfgs, brief, dry_run=dry_run)
    summary["notifiers"] = {
        r.notifier: ("skipped: " if r.skipped else "") + (r.detail or ("ok" if r.ok else "failed"))
        for r in notify_results
    }

    # 6) persist state only when at least one source succeeded (never overwrite good state with nothing)
    if ok_sources and not args.no_state:
        state.save(diffed, preset=cfg.name)
        summary["state_path"] = str(state.path)
    summary["ok_sources"] = ok_sources
    summary["brief_items"] = len(brief.items)
    return brief, summary


def _write_github_summary(brief: AnalyzedTrendBrief, summary: dict) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    from src.notifiers.markdown_notifier import render_markdown

    with open(path, "a", encoding="utf-8") as fh:
        fh.write(render_markdown(brief))
        fh.write("\n\n<details><summary>run summary</summary>\n\n```json\n")
        fh.write(json.dumps(summary, indent=2, ensure_ascii=False))
        fh.write("\n```\n</details>\n")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _setup_logging(args.verbose)
    try:
        cfg = load_config(args.config, args.preset)
    except Exception as exc:  # noqa: BLE001
        log.error("config error: %s", exc)
        return 3
    log.info("cron-trend-agent %s · preset=%s · dry_run=%s", __version__, cfg.name, args.dry_run)
    brief, summary = asyncio.run(run_pipeline(cfg, args))
    _write_github_summary(brief, summary)
    if args.summary_json:
        Path(args.summary_json).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if summary["ok_sources"] == 0 and not args.dry_run:
        log.error("every source failed; nothing to brief")
        return 2
    return 0


def cli() -> None:  # console_scripts entry
    raise SystemExit(main())


if __name__ == "__main__":
    raise SystemExit(main())
