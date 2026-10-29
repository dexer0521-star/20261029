"""Load + validate config.yaml (and presets) with Pydantic V2.

Rules:
- Secrets are NEVER stored in YAML. YAML only names the env var
  (e.g. `webhook_env: SLACK_WEBHOOK_URL`); `resolve_env()` reads it at runtime.
- A preset (`--preset ai-tech-news`) is just a YAML file under config/presets/.
- Unknown keys are rejected (extra="forbid") so typos fail fast.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
PRESET_DIR = CONFIG_DIR / "presets"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceConfig(_Strict):
    name: str = Field(..., min_length=1, description="Unique label shown in the brief")
    type: Literal["hackernews", "rss", "reddit", "apify"]
    enabled: bool = True
    limit: int = Field(default=30, ge=1, le=200)
    min_score: int = Field(default=0, ge=0)
    params: dict[str, Any] = Field(default_factory=dict, description="Collector-specific options")


class FilterConfig(_Strict):
    include_keywords: list[str] = Field(default_factory=list, description="Keep if ANY matches")
    exclude_keywords: list[str] = Field(default_factory=list, description="Drop if ANY matches")
    max_age_hours: int | None = Field(default=48, ge=1)
    max_items: int = Field(default=40, ge=1, le=300, description="Cap after merge+sort")
    only_fresh: bool = Field(default=False, description="Send only NEW/RISING items to the LLM")


class ProviderConfig(_Strict):
    provider: Literal["gemini", "claude", "openai", "mock"]
    model: str
    api_key_env: str | None = Field(default=None, description="Env var holding the API key")
    timeout_seconds: int = Field(default=60, ge=5, le=300)


class LLMConfig(_Strict):
    primary: ProviderConfig
    fallbacks: list[ProviderConfig] = Field(default_factory=list)
    language: str = Field(default="en", description="Output language code, e.g. 'ko'")
    audience: str = Field(default="developers and indie hackers")
    max_brief_items: int = Field(default=10, ge=1, le=30)
    temperature: float = Field(default=0.2, ge=0, le=2)
    extra_instructions: str = ""


class NotifierConfig(_Strict):
    type: Literal["slack", "notion", "markdown", "email"]
    enabled: bool = True
    webhook_env: str | None = None
    token_env: str | None = None
    database_id_env: str | None = None
    path: str | None = Field(default=None, description="markdown: output dir")
    params: dict[str, Any] = Field(default_factory=dict)


class StateConfig(_Strict):
    path: str = ".state/last_run.json"
    rising_score_delta: int = Field(default=50, ge=1)
    rising_rank_jump: int = Field(default=5, ge=1)
    keep_runs: int = Field(default=7, ge=1, description="Snapshots retained for keyword momentum")


class AppConfig(_Strict):
    name: str = "default"
    description: str = ""
    timezone: str = "UTC"
    sources: list[SourceConfig] = Field(..., min_length=1)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    llm: LLMConfig
    notifiers: list[NotifierConfig] = Field(default_factory=list)
    state: StateConfig = Field(default_factory=StateConfig)

    @field_validator("sources")
    @classmethod
    def _unique_names(cls, v: list[SourceConfig]) -> list[SourceConfig]:
        names = [s.name for s in v]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate source names: {sorted(dupes)}")
        return v

    @property
    def enabled_sources(self) -> list[SourceConfig]:
        return [s for s in self.sources if s.enabled]

    @property
    def enabled_notifiers(self) -> list[NotifierConfig]:
        return [n for n in self.notifiers if n.enabled]


class MissingSecret(RuntimeError):
    """Raised when a required env var named in the config is unset."""


def resolve_env(name: str | None, *, required: bool = True, what: str = "secret") -> str | None:
    """Read an env var named in the config. Never log the value."""
    if not name:
        if required:
            raise MissingSecret(f"{what}: no env var name configured")
        return None
    value = os.environ.get(name, "").strip()
    if not value and required:
        raise MissingSecret(f"{what}: env var {name} is not set")
    return value or None


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config root must be a mapping: {path}")
    return data


def list_presets() -> list[str]:
    if not PRESET_DIR.exists():
        return []
    return sorted(p.stem for p in PRESET_DIR.glob("*.yaml"))


def preset_path(name: str) -> Path:
    path = PRESET_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"unknown preset '{name}'. available: {list_presets()}")
    return path


def load_config(config_path: str | Path | None = None, preset: str | None = None) -> AppConfig:
    """Load config from an explicit path, a preset name, or config/config.yaml (fallback: example)."""
    if config_path and preset:
        raise ValueError("pass either --config or --preset, not both")
    if preset:
        path = preset_path(preset)
    elif config_path:
        path = Path(config_path)
    else:
        path = CONFIG_DIR / "config.yaml"
        if not path.exists():
            path = CONFIG_DIR / "config.example.yaml"
    cfg = AppConfig.model_validate(_read_yaml(path))
    if preset and cfg.name == "default":
        cfg.name = preset
    return cfg
