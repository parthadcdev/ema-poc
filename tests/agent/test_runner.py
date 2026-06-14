import hashlib
import json

import pytest

from ema_poc.adapters.base import LLMResponse
from ema_poc.agent.runner import run
from ema_poc.config import (
    AppConfig,
    BrandConfig,
    LLMTargetConfig,
    PricingConfig,
    RateLimitConfig,
    Settings,
)
from ema_poc.db import connect, init_schema
from ema_poc.prompts import resolve_system_prompt
from ema_poc.repositories.questions import add_question, approve_question
from ema_poc.repositories.responses import completed_keys, query_responses
from ema_poc.repositories.runs import get_run

NOW = "2026-06-13T02:00:00+00:00"


class _Adapter:
    """Fake adapter: returns a canned LLMResponse, or raises if behavior is an
    Exception. Records call count."""

    model_version = "m"

    def __init__(self, name, behavior):
        self.name = name
        self._behavior = behavior
        self.calls = 0

    def query(self, system_prompt, question_text):
        self.calls += 1
        if isinstance(self._behavior, Exception):
            raise self._behavior
        return self._behavior


def _config(names, *, in_price=0.001, out_price=0.002):
    targets = [
        LLMTargetConfig(
            name=n, adapter="openai", model_version="m", api_key_env="K",
            pricing=PricingConfig(input_per_1k=in_price, output_per_1k=out_price),
            rate_limit=RateLimitConfig(requests_per_minute=60, tokens_per_minute=1000),
        )
        for n in names
    ]
    return AppConfig(
        settings=Settings(system_prompts={"default": "ctx"}),
        brands=BrandConfig(),
        targets=targets,
    )


def _ids():
    counter = {"n": 0}

    def factory():
        counter["n"] += 1
        return f"id-{counter['n']}"

    return factory


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def _seed_two_approved(conn):
    add_question(conn, question_id="Q1", question_text="a", persona="Provider",
                 domain="Safety", now=NOW)
    approve_question(conn, "Q1", approver_name="R", now=NOW)
    add_question(conn, question_id="Q2", question_text="b", persona="Patient",
                 domain="Efficacy", now=NOW)
    approve_question(conn, "Q2", approver_name="R", now=NOW)


def test_run_fans_out_to_all_adapters_and_saves(tmp_path):
    conn = _conn(tmp_path)
    _seed_two_approved(conn)
    a1 = _Adapter("GPT-4o", LLMResponse("x", "stop", "SUCCESS", prompt_tokens=10, completion_tokens=20))
    a2 = _Adapter("Gemini", LLMResponse("y", "stop", "SUCCESS", prompt_tokens=5, completion_tokens=5))
    cfg = _config(["GPT-4o", "Gemini"])
    summary = run(conn, [a1, a2], cfg, run_id="run-1", id_factory=_ids(),
                  now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)
    assert summary.responses_captured == 4
    assert summary.by_status["SUCCESS"] == 4
    assert summary.failure_count == 0
    assert summary.questions_attempted == 2
    assert summary.total_tokens == (10 + 20 + 5 + 5) * 2  # both questions
    assert completed_keys(conn, "run-1") == {
        ("Q1", "GPT-4o"), ("Q1", "Gemini"), ("Q2", "GPT-4o"), ("Q2", "Gemini"),
    }
    row = get_run(conn, "run-1")
    assert row.status == "COMPLETED"
    assert row.responses_captured == 4
    conn.close()


def test_run_records_failed_responses(tmp_path):
    conn = _conn(tmp_path)
    _seed_two_approved(conn)
    good = _Adapter("GPT-4o", LLMResponse("x", "stop", "SUCCESS", prompt_tokens=1, completion_tokens=1))
    bad = _Adapter("Gemini", RuntimeError("down"))
    cfg = _config(["GPT-4o", "Gemini"])
    summary = run(conn, [good, bad], cfg, run_id="run-1", id_factory=_ids(),
                  now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)
    assert summary.by_status["SUCCESS"] == 2
    assert summary.by_status["FAILED"] == 2
    assert summary.failure_count == 2
    assert completed_keys(conn, "run-1") == {("Q1", "GPT-4o"), ("Q2", "GPT-4o")}
    conn.close()


def test_resume_skips_completed_and_retries_failed(tmp_path):
    conn = _conn(tmp_path)
    _seed_two_approved(conn)
    ids = _ids()  # shared across both runs so response_ids stay unique (PK)
    # First run: GPT-4o succeeds, Gemini fails
    run(conn,
        [_Adapter("GPT-4o", LLMResponse("x", "stop", "SUCCESS", prompt_tokens=1, completion_tokens=1)),
         _Adapter("Gemini", RuntimeError("down"))],
        _config(["GPT-4o", "Gemini"]), run_id="run-1", id_factory=ids,
        now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)
    # Resume: GPT-4o already done both Qs -> skipped; Gemini now healthy -> retried
    gpt = _Adapter("GPT-4o", LLMResponse("x2", "stop", "SUCCESS", prompt_tokens=1, completion_tokens=1))
    gem = _Adapter("Gemini", LLMResponse("y2", "stop", "SUCCESS", prompt_tokens=2, completion_tokens=2))
    run(conn, [gpt, gem], _config(["GPT-4o", "Gemini"]), run_id="run-1", id_factory=ids,
        now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)
    assert gpt.calls == 0   # already completed both questions -> skipped
    assert gem.calls == 2   # retried for both questions
    # The prior FAILED Gemini rows are preserved (append-only); the new SUCCESS
    # rows make those keys complete.
    assert completed_keys(conn, "run-1") == {
        ("Q1", "GPT-4o"), ("Q1", "Gemini"), ("Q2", "GPT-4o"), ("Q2", "Gemini"),
    }
    conn.close()


def test_run_persists_citations_from_grounded_response(tmp_path):
    from ema_poc.adapters.base import Citation
    from ema_poc.repositories.citations import list_citations

    conn = _conn(tmp_path)
    add_question(conn, question_id="Q1", question_text="a", persona="Provider",
                 domain="Safety", now=NOW)
    approve_question(conn, "Q1", approver_name="R", now=NOW)

    cite_resp = LLMResponse(
        text="ans", finish_reason="stop", status="SUCCESS", completion_tokens=3,
        citations=[Citation(title="X", url="https://src/x")],
    )
    adapter = _Adapter("GPT-4o", cite_resp)
    cfg = _config(["GPT-4o"])
    ids = _ids()
    run(conn, [adapter], cfg, run_id="run-1", id_factory=ids,
        now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)

    row = conn.execute(
        "SELECT response_id FROM responses WHERE llm_name=? AND question_id=?",
        ("GPT-4o", "Q1"),
    ).fetchone()
    assert row is not None, "response row not saved"
    rid = row[0]

    cites = list_citations(conn, rid)
    assert [c.url for c in cites] == ["https://src/x"]
    conn.close()


def test_run_marks_run_failed_when_a_db_write_raises(tmp_path, monkeypatch):
    import sqlite3

    conn = _conn(tmp_path)
    _seed_two_approved(conn)

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr("ema_poc.agent.runner.save_response", boom)
    a = _Adapter("GPT-4o", LLMResponse("x", "stop", "SUCCESS", prompt_tokens=1, completion_tokens=1))
    with pytest.raises(sqlite3.OperationalError):
        run(conn, [a], _config(["GPT-4o"]), run_id="run-1", id_factory=_ids(),
            now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)
    # the run row is finalized to FAILED, not left stuck in RUNNING
    assert get_run(conn, "run-1").status == "FAILED"
    conn.close()


def test_run_saves_provenance_on_each_response(tmp_path):
    """After a successful run, every response row has a non-null provenance
    JSON blob with all four keys, and system_prompt_sha256 matches what the
    runner would have computed from resolve_system_prompt."""
    conn = _conn(tmp_path)
    # Seed one approved question with persona=Provider
    add_question(conn, question_id="Q1", question_text="a", persona="Provider",
                 domain="Safety", now=NOW)
    approve_question(conn, "Q1", approver_name="R", now=NOW)

    cfg = _config(["GPT-4o"])
    a = _Adapter("GPT-4o", LLMResponse("x", "stop", "SUCCESS", prompt_tokens=1, completion_tokens=1))
    run(conn, [a], cfg, run_id="run-p", id_factory=_ids(),
        now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)

    responses = query_responses(conn, llm="GPT-4o")
    assert len(responses) == 1
    resp = responses[0]

    # provenance must be non-null and parseable
    assert resp.provenance is not None
    prov = json.loads(resp.provenance)

    # all four required keys must be present
    assert set(prov.keys()) == {"model_version", "params", "grounded", "system_prompt_sha256"}

    # system_prompt_sha256 must match what resolve_system_prompt returns for
    # persona=Provider with this config's system_prompts={"default": "ctx"}
    from ema_poc.models import Persona
    expected_prompt = resolve_system_prompt(Persona.PROVIDER, cfg.settings)
    expected_sha = hashlib.sha256(expected_prompt.encode("utf-8")).hexdigest()
    assert prov["system_prompt_sha256"] == expected_sha

    conn.close()
