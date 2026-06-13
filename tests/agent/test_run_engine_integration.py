"""End-to-end run: one approved question fanned out to three adapters returning
SUCCESS / TRUNCATED / BLOCKED, asserting persisted statuses, the run summary,
cost/token accounting, and one audit entry per call."""

import pytest

from ema_poc.adapters.base import LLMResponse
from ema_poc.agent.runner import run
from ema_poc.audit import list_events
from ema_poc.config import (
    AppConfig,
    BrandConfig,
    LLMTargetConfig,
    PricingConfig,
    RateLimitConfig,
    Settings,
)
from ema_poc.db import connect, init_schema
from ema_poc.repositories.questions import add_question, approve_question
from ema_poc.repositories.runs import get_run

NOW = "2026-06-13T02:00:00+00:00"


class _Adapter:
    model_version = "m"

    def __init__(self, name, response):
        self.name = name
        self._response = response

    def query(self, system_prompt, question_text):
        return self._response


def _ids():
    counter = {"n": 0}

    def factory():
        counter["n"] += 1
        return f"id-{counter['n']}"

    return factory


def _config(names):
    targets = [
        LLMTargetConfig(
            name=n, adapter="openai", model_version="m", api_key_env="K",
            pricing=PricingConfig(input_per_1k=0.001, output_per_1k=0.002),
            rate_limit=RateLimitConfig(requests_per_minute=60, tokens_per_minute=1000),
        )
        for n in names
    ]
    return AppConfig(settings=Settings(system_prompts={"default": "ctx"}),
                     brands=BrandConfig(), targets=targets)


def test_full_run_persists_all_statuses_summary_and_audit(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    add_question(conn, question_id="Q1", question_text="Is drug X first-line?",
                 persona="Provider", domain="Comparative", now=NOW)
    approve_question(conn, "Q1", approver_name="Dr. A", now=NOW)

    adapters = [
        _Adapter("GPT-4o", LLMResponse("ok", "stop", "SUCCESS",
                                       prompt_tokens=100, completion_tokens=200)),
        _Adapter("Gemini", LLMResponse("cut", "length", "TRUNCATED",
                                       prompt_tokens=10, completion_tokens=1024)),
        _Adapter("Claude", LLMResponse("", "blocked", "BLOCKED",
                                       prompt_tokens=5, completion_tokens=0)),
    ]
    cfg = _config(["GPT-4o", "Gemini", "Claude"])

    summary = run(conn, adapters, cfg, run_id="run-1", id_factory=_ids(),
                  now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)

    assert summary.responses_captured == 3
    assert summary.by_status == {"SUCCESS": 1, "TRUNCATED": 1, "BLOCKED": 1, "FAILED": 0}
    assert summary.failure_count == 0

    assert summary.total_tokens == 100 + 200 + 10 + 1024 + 5 + 0
    expected_cost = (
        (100 / 1000 * 0.001 + 200 / 1000 * 0.002)   # GPT-4o
        + (10 / 1000 * 0.001 + 1024 / 1000 * 0.002)  # Gemini
        + (5 / 1000 * 0.001 + 0 / 1000 * 0.002)      # Claude
    )
    assert summary.est_cost == pytest.approx(expected_cost)

    statuses = {
        row["llm_name"]: row["status"]
        for row in conn.execute("SELECT llm_name, status FROM responses").fetchall()
    }
    assert statuses == {"GPT-4o": "SUCCESS", "Gemini": "TRUNCATED", "Claude": "BLOCKED"}

    assert get_run(conn, "run-1").status == "COMPLETED"

    llm_events = [e for e in list_events(conn) if e["event_type"] == "LLM_RESPONSE"]
    assert len(llm_events) == 3
    assert {e["llm_target"] for e in llm_events} == {"GPT-4o", "Gemini", "Claude"}

    conn.close()
