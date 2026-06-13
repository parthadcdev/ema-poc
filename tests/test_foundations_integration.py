"""End-to-end wiring of the foundation layer with no LLM calls."""

from pathlib import Path

from ema_poc.audit import list_events, record_event
from ema_poc.config import load_config, validate_credentials
from ema_poc.db import connect, init_schema


def _write_config(d: Path) -> None:
    (d / "settings.yaml").write_text(
        """
settings:
  db_path: ema.sqlite
brands:
  abbvie_brands: ["Skyrizi"]
  competitor_brands: ["Stelara"]
"""
    )
    (d / "llm_targets.yaml").write_text(
        """
targets:
  - name: GPT-4o
    adapter: openai
    model_version: gpt-4o-2024-11-20
    api_key_env: OPENAI_API_KEY
    pricing: {input_per_1k: 0.0025, output_per_1k: 0.01}
    rate_limit: {requests_per_minute: 60, tokens_per_minute: 90000}
"""
    )


def test_config_db_and_audit_wire_together(tmp_path):
    _write_config(tmp_path)

    cfg = load_config(tmp_path)
    validate_credentials(
        cfg, {"ANTHROPIC_API_KEY": "sk-a", "OPENAI_API_KEY": "sk-o"}
    )

    conn = connect(str(tmp_path / cfg.settings.db_path))
    init_schema(conn)

    record_event(
        conn,
        event_type="STARTUP",
        detail=f"loaded {len(cfg.targets)} target(s)",
        timestamp="2026-06-13T02:00:00+00:00",
    )
    events = list_events(conn)
    assert events[0]["event_type"] == "STARTUP"
    assert "1 target" in events[0]["detail"]
    conn.close()
