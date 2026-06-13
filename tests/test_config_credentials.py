import pytest

from ema_poc.config import (
    AppConfig,
    BrandConfig,
    ConfigError,
    LLMTargetConfig,
    PricingConfig,
    RateLimitConfig,
    Settings,
    validate_credentials,
)


def _target(name: str, api_key_env: str, enabled: bool = True) -> LLMTargetConfig:
    return LLMTargetConfig(
        name=name,
        adapter="openai",
        model_version="x",
        api_key_env=api_key_env,
        enabled=enabled,
        pricing=PricingConfig(input_per_1k=0.0, output_per_1k=0.0),
        rate_limit=RateLimitConfig(requests_per_minute=60, tokens_per_minute=1000),
    )


def _config(targets) -> AppConfig:
    return AppConfig(settings=Settings(), brands=BrandConfig(), targets=targets)


def test_passes_when_all_credentials_present():
    cfg = _config([_target("GPT-4o", "OPENAI_API_KEY")])
    env = {"ANTHROPIC_API_KEY": "sk-a", "OPENAI_API_KEY": "sk-o"}
    validate_credentials(cfg, env)  # should not raise


def test_raises_listing_missing_credentials():
    cfg = _config([_target("GPT-4o", "OPENAI_API_KEY")])
    env = {"OPENAI_API_KEY": "sk-o"}  # ANTHROPIC missing
    with pytest.raises(ConfigError) as exc:
        validate_credentials(cfg, env)
    assert "ANTHROPIC_API_KEY" in str(exc.value)


def test_ignores_disabled_targets():
    cfg = _config([_target("Gemini", "GOOGLE_API_KEY", enabled=False)])
    env = {"ANTHROPIC_API_KEY": "sk-a"}
    validate_credentials(cfg, env)  # disabled target's key not required
