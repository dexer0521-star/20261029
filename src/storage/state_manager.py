"""StateManager: diff this run against the previous snapshot without a database.

Storage is a single JSON file (default `.state/last_run.json`). In GitHub Actions it is
restored/saved with actions/cache (see .github/workflows/daily-brief.yml). Locally it just
lives on disk. Item identity = sha1(normalized_url)[:16] (see schemas.item_id_for).

Diff rules (per item id):
  NEW      : id not in previous snapshot
  RISING   : score grew >= rising_score_delta OR rank moved up >= rising_rank_jump
  FALLING  : score dropped >= rising_score_delta OR rank moved down >= rising_rank_jump
  STEADY   : otherwise
Rising keywords = tokens whose frequency in current titles grew vs the rolling window.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from src.analyzers.schemas import DiffStatus, DiffTrendItem, RawTrendItem
from src.config_loader import StateConfig

log = logging.getLogger(__name__)

_STOP = set(
    "the a an and or of to in on for with by from at is are was were be as it its this that these "
    "those vs via new how why what when your you we our i my me they them he she his her up out "
    "about into over after before than then so not no yes just more most less very can could "
    "will would should has have had do does did also one two three show ask hn tell".split()
)
_TOKEN = re.compile(r"[a-zA-Z][a-zA-Z0-9\-\+\.#]{2,}|[가-힣]{2,}")


class ItemSnapshot(BaseModel):
    id: str
    title: str
    url: str
    score: int | None = None
    rank: int
    seen_runs: int = 1
    first_seen: datetime


class RunState(BaseModel):
    version: int = 1
    run_at: datetime | None = None
    preset: str = "default"
    items: dict[str, ItemSnapshot] = Field(default_factory=dict)
    title_history: list[list[str]] = Field(default_factory=list, description="rolling titles per run")


def tokenize(text: str) -> set[str]:
    return {t.lower().strip(".") for t in _TOKEN.findall(text) if t.lower() not in _STOP}


def rank_items(items: list[RawTrendItem]) -> list[RawTrendItem]:
    """Sort by score desc, then recency desc. Items without score go after scored ones."""
    far_past = datetime.min.replace(tzinfo=UTC)
    return sorted(
        items,
        key=lambda i: (i.score if i.score is not None else -1, i.published_at or far_past),
        reverse=True,
    )


class StateManager:
    def __init__(self, config: StateConfig, path: str | Path | None = None) -> None:
        self.config = config
        self.path = Path(path or config.path)
        self.state = RunState()

    # ---- persistence -----------------------------------------------------
    def load(self) -> RunState:
        if self.path.exists():
            try:
                self.state = RunState.model_validate_json(self.path.read_text(encoding="utf-8"))
                log.info("state loaded: %d items from %s", len(self.state.items), self.state.run_at)
            except Exception as exc:  # noqa: BLE001 - corrupt state must not block the run
                log.warning("state file unreadable (%s); starting fresh", exc)
                self.state = RunState()
        else:
            log.info("no previous state at %s (first run)", self.path)
        return self.state

    def save(self, items: list[DiffTrendItem], preset: str = "default") -> Path:
        history = (self.state.title_history + [[i.title for i in items]])[-self.config.keep_runs :]
        new_state = RunState(
            run_at=datetime.now(UTC),
            preset=preset,
            items={
                i.id: ItemSnapshot(
                    id=i.id,
                    title=i.title,
                    url=i.url,
                    score=i.score,
                    rank=i.rank,
                    seen_runs=i.seen_runs,
                    first_seen=self._first_seen(i.id),
                )
                for i in items
            },
            title_history=history,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(new_state.model_dump_json(indent=2), encoding="utf-8")
        self.state = new_state
        return self.path

    def _first_seen(self, item_id: str) -> datetime:
        prev = self.state.items.get(item_id)
        return prev.first_seen if prev else datetime.now(UTC)

    # ---- diff ------------------------------------------------------------
    def diff(self, items: list[RawTrendItem]) -> list[DiffTrendItem]:
        prev = self.state.items
        ranked = rank_items(items)
        out: list[DiffTrendItem] = []
        for rank, item in enumerate(ranked, start=1):
            old = prev.get(item.id)
            data = item.model_dump()
            data["rank"] = rank
            if old is None:
                data["status"] = DiffStatus.NEW
            else:
                score_delta = (item.score - old.score) if (item.score is not None and old.score is not None) else None
                rank_delta = old.rank - rank
                data.update(
                    prev_rank=old.rank,
                    prev_score=old.score,
                    score_delta=score_delta,
                    rank_delta=rank_delta,
                    seen_runs=old.seen_runs + 1,
                    status=self._classify(score_delta, rank_delta),
                )
            out.append(DiffTrendItem.model_validate(data))
        return out

    def _classify(self, score_delta: int | None, rank_delta: int) -> DiffStatus:
        up = (score_delta or 0) >= self.config.rising_score_delta or rank_delta >= self.config.rising_rank_jump
        down = (score_delta or 0) <= -self.config.rising_score_delta or rank_delta <= -self.config.rising_rank_jump
        if up and not down:
            return DiffStatus.RISING
        if down and not up:
            return DiffStatus.FALLING
        return DiffStatus.STEADY

    def rising_keywords(self, items: list[RawTrendItem], top_n: int = 10) -> list[str]:
        """Tokens that appear in >=2 current titles and are new or growing vs the rolling window."""
        now = Counter(tok for i in items for tok in tokenize(i.title))
        past: Counter[str] = Counter()
        for titles in self.state.title_history:
            past.update(tok for t in titles for tok in tokenize(t))
        runs = max(len(self.state.title_history), 1)
        scored = [
            (count - past[tok] / runs, count, tok)
            for tok, count in now.items()
            if count >= 2 and count > past[tok] / runs
        ]
        scored.sort(reverse=True)
        return [tok for _, _, tok in scored[:top_n]]
