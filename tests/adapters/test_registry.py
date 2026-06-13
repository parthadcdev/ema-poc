import pytest

from ema_poc.adapters.claude_adapter import ClaudeTargetAdapter
from ema_poc.adapters.gemini_adapter import GeminiAdapter
from ema_poc.adapters.openai_adapter import OpenAIAdapter
from ema_poc.adapters.registry import build_adapters
from ema_poc.config import (
    AppConfig,
    BrandConfig,
    LLMTargetConfig,
    PricingConfig,
    RateLimitConfig,
    Settings,
)


def _target(name, adapter, enabled=True):
    return LLMTargetConfig(
        name=name,
        adapter=adapter,
        model_version="m",
        api_key_env=f"{adapter.upper()}_KEY",
        enabled=enabled,
        pricing=PricingConfig(input_per_1k=0.0, output_per_1k=0.0),
        rate_limit=RateLimitConfig(requests_per_minute=60, tokens_per_minute=1000),
    )


def _config(targets):
    return AppConfig(settings=Settings(), brands=BrandConfig(), targets=targets)


def _fake_factories():
    seen = {}

    def openai_factory(api_key):
        seen["openai"] = api_key
        return f"openai-client::{api_key}"

    def gemini_factory(api_key, model_version, system_instruction=None):
        seen.setdefault("gemini", []).append((api_key, model_version, system_instruction))
        return f"gemini-model::{system_instruction}"

    def anthropic_factory(api_key):
        seen["anthropic"] = api_key
        return f"anthropic-client::{api_key}"

    return seen, openai_factory, gemini_factory, anthropic_factory


def test_builds_one_adapter_per_enabled_target():
    cfg = _config([
        _target("GPT-4o", "openai"),
        _target("Gemini", "gemini"),
        _target("Claude", "claude"),
    ])
    env = {"OPENAI_KEY": "k-o", "GEMINI_KEY": "k-g", "CLAUDE_KEY": "k-c"}
    seen, of, gf, af = _fake_factories()
    adapters = build_adapters(
        cfg, env,
        openai_client_factory=of, gemini_model_factory=gf, anthropic_client_factory=af,
    )
    assert [type(a) for a in adapters] == [
        OpenAIAdapter, GeminiAdapter, ClaudeTargetAdapter
    ]
    assert seen["openai"] == "k-o"
    assert seen["anthropic"] == "k-c"


def test_skips_disabled_targets():
    cfg = _config([
        _target("GPT-4o", "openai"),
        _target("Gemini", "gemini", enabled=False),
    ])
    env = {"OPENAI_KEY": "k-o", "GEMINI_KEY": "k-g"}
    seen, of, gf, af = _fake_factories()
    adapters = build_adapters(
        cfg, env,
        openai_client_factory=of, gemini_model_factory=gf, anthropic_client_factory=af,
    )
    assert [a.name for a in adapters] == ["GPT-4o"]


def test_gemini_model_factory_binds_key_and_passes_system_per_query():
    cfg = _config([_target("Gemini", "gemini")])
    env = {"GEMINI_KEY": "k-g"}
    seen, of, gf, af = _fake_factories()
    [gemini] = build_adapters(
        cfg, env,
        openai_client_factory=of, gemini_model_factory=gf, anthropic_client_factory=af,
    )
    model = gemini._model_factory("PERSONA SYSTEM")
    assert model == "gemini-model::PERSONA SYSTEM"
    assert seen["gemini"][-1] == ("k-g", "m", "PERSONA SYSTEM")


def test_unknown_adapter_raises():
    cfg = _config([_target("Mystery", "mystery")])
    env = {"MYSTERY_KEY": "k"}
    seen, of, gf, af = _fake_factories()
    with pytest.raises(ValueError):
        build_adapters(
            cfg, env,
            openai_client_factory=of, gemini_model_factory=gf, anthropic_client_factory=af,
        )


def test_build_adapters_propagates_grounded_flag():
    cfg = AppConfig(
        settings=Settings(),
        brands=BrandConfig(),
        targets=[LLMTargetConfig(
            name="GPT-4o-Grounded", adapter="openai", model_version="gpt-4o",
            api_key_env="OPENAI_API_KEY", grounded=True,
            pricing={"input_per_1k": 0.0, "output_per_1k": 0.0},
            rate_limit={"requests_per_minute": 1, "tokens_per_minute": 1},
        )],
    )
    adapters = build_adapters(
        cfg, {"OPENAI_API_KEY": "k"},
        openai_client_factory=lambda key: object(),
    )
    assert adapters[0].grounded is True
