"""Configuration schema, loading, and credential validation (spec §3, §7)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError


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
    try:
        settings_raw = yaml.safe_load((config_dir / "settings.yaml").read_text()) or {}
        targets_raw = yaml.safe_load((config_dir / "llm_targets.yaml").read_text()) or {}
    except FileNotFoundError as exc:
        raise ConfigError(f"Missing config file: {exc.filename}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Malformed YAML: {exc}") from exc

    try:
        return AppConfig(
            settings=Settings(**settings_raw.get("settings", {})),
            brands=BrandConfig(**settings_raw.get("brands", {})),
            targets=[LLMTargetConfig(**t) for t in targets_raw.get("targets", [])],
        )
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc


def validate_credentials(
    config: AppConfig, env: Mapping[str, str] | None = None
) -> None:
    """Verify every required credential is present, else raise ConfigError (IN-502)."""
    if env is None:
        env = os.environ

    missing: list[str] = []
    if not env.get(config.settings.anthropic_api_key_env):
        missing.append(config.settings.anthropic_api_key_env)
    for target in config.targets:
        if target.enabled and not env.get(target.api_key_env):
            missing.append(target.api_key_env)

    if missing:
        raise ConfigError(
            "Missing required credentials: " + ", ".join(sorted(set(missing)))
        )
