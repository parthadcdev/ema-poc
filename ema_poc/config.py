"""Configuration schema, loading, and credential validation (spec §3, §7)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ConfigError(Exception):
    """Raised when configuration or required credentials are invalid/missing."""


class RateLimitConfig(BaseModel):
    requests_per_minute: int
    tokens_per_minute: int


class PricingConfig(BaseModel):
    input_per_1k: float
    output_per_1k: float


class LLMTargetConfig(BaseModel):
    name: str
    adapter: str  # openai | gemini | claude | open_evidence
    model_version: str
    api_key_env: str
    enabled: bool = True
    params: dict = Field(default_factory=dict)
    pricing: PricingConfig
    rate_limit: RateLimitConfig


class Settings(BaseModel):
    db_path: str = "ema.sqlite"
    schedule_cron: str = "0 2 * * *"
    max_retries: int = 3
    backoff_seconds: list[int] = Field(default_factory=lambda: [2, 4, 8])
    max_tokens_per_run: int | None = None
    orchestrator_model: str = "claude-opus-4-8"
    scoring_model: str = "claude-opus-4-8"
    anthropic_api_key_env: str = "ANTHROPIC_API_KEY"


class BrandConfig(BaseModel):
    abbvie_brands: list[str] = Field(default_factory=list)
    competitor_brands: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    settings: Settings
    brands: BrandConfig
    targets: list[LLMTargetConfig]


def load_config(config_dir: Path | str) -> AppConfig:
    config_dir = Path(config_dir)
    settings_raw = yaml.safe_load((config_dir / "settings.yaml").read_text()) or {}
    targets_raw = yaml.safe_load((config_dir / "llm_targets.yaml").read_text()) or {}

    return AppConfig(
        settings=Settings(**settings_raw.get("settings", {})),
        brands=BrandConfig(**settings_raw.get("brands", {})),
        targets=[LLMTargetConfig(**t) for t in targets_raw.get("targets", [])],
    )
