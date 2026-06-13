from ema_poc.adapters.base import LLMResponse
from ema_poc.agent.runner import run
from ema_poc.config import (
    AppConfig, BrandConfig, LLMTargetConfig, PricingConfig, RateLimitConfig, Settings,
)
from ema_poc.db import connect, init_schema
from ema_poc.repositories.questions import add_question, approve_question
from ema_poc.repositories.responses import query_responses

NOW = "2026-06-13T02:00:00+00:00"


class _Adapter:
    model_version = "m"

    def __init__(self, name):
        self.name = name

    def query(self, system_prompt, question_text):
        return LLMResponse("x", "stop", "SUCCESS", prompt_tokens=1, completion_tokens=1)


def _config():
    return AppConfig(
        settings=Settings(system_prompts={"default": "ctx"}),
        brands=BrandConfig(),
        targets=[LLMTargetConfig(
            name="GPT-4o", adapter="openai", model_version="m", api_key_env="K",
            pricing=PricingConfig(input_per_1k=0.0, output_per_1k=0.0),
            rate_limit=RateLimitConfig(requests_per_minute=60, tokens_per_minute=1000),
        )],
    )


def _ids():
    n = {"i": 0}

    def f():
        n["i"] += 1
        return f"id-{n['i']}"

    return f


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def _seed(conn):
    add_question(conn, question_id="P1", question_text="a", persona="Provider",
                 domain="Safety", therapeutic_area="Immunology", now=NOW)
    approve_question(conn, "P1", approver_name="R", now=NOW)
    add_question(conn, question_id="P2", question_text="b", persona="Patient",
                 domain="Efficacy", therapeutic_area="Oncology", now=NOW)
    approve_question(conn, "P2", approver_name="R", now=NOW)


def test_run_filters_by_persona(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    run(conn, [_Adapter("GPT-4o")], _config(), run_id="run-1", persona="Provider",
        id_factory=_ids(), now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)
    qids = {r.question_id for r in query_responses(conn)}
    assert qids == {"P1"}  # only the Provider question ran
    conn.close()


def test_run_filters_by_domain_and_ta(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    run(conn, [_Adapter("GPT-4o")], _config(), run_id="run-1", domain="Efficacy",
        id_factory=_ids(), now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)
    assert {r.question_id for r in query_responses(conn)} == {"P2"}
    conn.close()


def test_run_no_filter_runs_all(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    run(conn, [_Adapter("GPT-4o")], _config(), run_id="run-1",
        id_factory=_ids(), now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)
    assert {r.question_id for r in query_responses(conn)} == {"P1", "P2"}
    conn.close()
