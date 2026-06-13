from pathlib import Path

import pytest

from ema_poc.config import load_config, ConfigError, LLMTargetConfig


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    (tmp_path / "settings.yaml").write_text(
        """
settings:
  db_path: test.sqlite
  schedule_cron: "0 2 * * *"
  max_retries: 3
  backoff_seconds: [2, 4, 8]
  orchestrator_model: claude-opus-4-8
  scoring_model: claude-opus-4-8
  anthropic_api_key_env: ANTHROPIC_API_KEY
brands:
  abbvie_brands: ["Skyrizi", "Rinvoq"]
  competitor_brands: ["Humira-biosimilar", "Stelara"]
"""
    )
    (tmp_path / "llm_targets.yaml").write_text(
        """
targets:
  - name: GPT-4o
    adapter: openai
    model_version: gpt-4o-2024-11-20
    api_key_env: OPENAI_API_KEY
    params: {temperature: 0.3, max_tokens: 1024}
    pricing: {input_per_1k: 0.0025, output_per_1k: 0.01}
    rate_limit: {requests_per_minute: 60, tokens_per_minute: 90000}
  - name: Gemini-1.5-Pro
    adapter: gemini
    model_version: gemini-1.5-pro
    api_key_env: GOOGLE_API_KEY
    enabled: false
    params: {temperature: 0.3, max_output_tokens: 1024}
    pricing: {input_per_1k: 0.00125, output_per_1k: 0.005}
    rate_limit: {requests_per_minute: 60, tokens_per_minute: 90000}
"""
    )
    return tmp_path


def test_load_config_parses_settings_targets_and_brands(config_dir: Path):
    cfg = load_config(config_dir)

    assert cfg.settings.db_path == "test.sqlite"
    assert cfg.settings.backoff_seconds == [2, 4, 8]
    assert cfg.brands.abbvie_brands == ["Skyrizi", "Rinvoq"]

    assert len(cfg.targets) == 2
    gpt = cfg.targets[0]
    assert gpt.name == "GPT-4o"
    assert gpt.adapter == "openai"
    assert gpt.enabled is True
    assert gpt.rate_limit.requests_per_minute == 60
    assert gpt.params["temperature"] == 0.3

    gemini = cfg.targets[1]
    assert gemini.enabled is False


def test_load_config_uses_defaults_when_optional_keys_absent(tmp_path: Path):
    (tmp_path / "settings.yaml").write_text("settings:\n  db_path: x.sqlite\n")
    (tmp_path / "llm_targets.yaml").write_text("targets: []\n")
    cfg = load_config(tmp_path)
    assert cfg.settings.max_retries == 3
    assert cfg.settings.backoff_seconds == [2, 4, 8]
    assert cfg.brands.abbvie_brands == []
    assert cfg.targets == []


def test_load_config_raises_config_error_on_missing_file(tmp_path: Path):
    (tmp_path / "settings.yaml").write_text("settings: {}\n")
    # llm_targets.yaml intentionally absent
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_load_config_raises_config_error_on_malformed_yaml(tmp_path: Path):
    (tmp_path / "settings.yaml").write_text("foo: [bar\n")  # unterminated flow seq
    (tmp_path / "llm_targets.yaml").write_text("targets: []\n")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_target_grounded_defaults_false_and_parses_true():
    t = LLMTargetConfig(
        name="X", adapter="openai", model_version="m", api_key_env="K",
        pricing={"input_per_1k": 0.0, "output_per_1k": 0.0},
        rate_limit={"requests_per_minute": 1, "tokens_per_minute": 1},
    )
    assert t.grounded is False
    t2 = LLMTargetConfig(
        name="Xg", adapter="openai", model_version="m", api_key_env="K", grounded=True,
        pricing={"input_per_1k": 0.0, "output_per_1k": 0.0},
        rate_limit={"requests_per_minute": 1, "tokens_per_minute": 1},
    )
    assert t2.grounded is True
