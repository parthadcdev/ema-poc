from ema_poc.adapters.base import LLMResponse
from ema_poc.db import connect, init_schema
from ema_poc.models import Question, ResponseStatus
from ema_poc.repositories.responses import build_response, completed_keys, save_response
from ema_poc.repositories.runs import create_run

NOW = "2026-06-13T02:00:00+00:00"


class _FakeAdapter:
    def __init__(self, name="GPT-4o", model_version="gpt-4o-2024-11-20"):
        self.name = name
        self.model_version = model_version


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=NOW)
    return conn


def _q(qid="Q1"):
    return Question(
        question_id=qid, question_text="t", persona="Provider", domain="Safety",
        therapeutic_area="Immunology", brand_focus="Skyrizi",
    )


def test_build_response_maps_question_adapter_and_llm():
    llm = LLMResponse(
        text="ans", finish_reason="stop", status="SUCCESS",
        prompt_tokens=10, completion_tokens=20,
    )
    r = build_response(
        run_id="r1", question=_q(), adapter=_FakeAdapter(),
        llm_response=llm, now=NOW, response_id="resp-1",
    )
    assert r.run_id == "r1"
    assert r.llm_name == "GPT-4o"
    assert r.llm_model_version == "gpt-4o-2024-11-20"
    assert r.question_id == "Q1"
    assert r.question_text == "t"
    assert r.therapeutic_area == "Immunology"
    assert r.response_text == "ans"
    assert r.response_tokens == 20  # completion tokens
    assert r.status is ResponseStatus.SUCCESS
    assert r.sentiment_score is None  # scored later
    assert r.alert_triggered is False


def test_save_response_persists_and_is_queryable(tmp_path):
    conn = _conn(tmp_path)
    llm = LLMResponse(text="ans", finish_reason="stop", status="SUCCESS",
                      prompt_tokens=10, completion_tokens=20)
    r = build_response(run_id="r1", question=_q(), adapter=_FakeAdapter(),
                       llm_response=llm, now=NOW, response_id="resp-1")
    save_response(conn, r)
    row = conn.execute(
        "SELECT llm_name, status, response_text FROM responses WHERE response_id='resp-1'"
    ).fetchone()
    assert row["llm_name"] == "GPT-4o"
    assert row["status"] == "SUCCESS"
    assert row["response_text"] == "ans"
    conn.close()


def test_completed_keys_includes_non_failed_only(tmp_path):
    conn = _conn(tmp_path)
    ok = LLMResponse(text="a", finish_reason="stop", status="SUCCESS")
    failed = LLMResponse(text="", finish_reason="error", status="FAILED")
    blocked = LLMResponse(text="", finish_reason="blocked", status="BLOCKED")
    save_response(conn, build_response(run_id="r1", question=_q("Q1"),
                  adapter=_FakeAdapter("GPT-4o"), llm_response=ok, now=NOW, response_id="r-1"))
    save_response(conn, build_response(run_id="r1", question=_q("Q2"),
                  adapter=_FakeAdapter("GPT-4o"), llm_response=failed, now=NOW, response_id="r-2"))
    save_response(conn, build_response(run_id="r1", question=_q("Q3"),
                  adapter=_FakeAdapter("Gemini"), llm_response=blocked, now=NOW, response_id="r-3"))
    keys = completed_keys(conn, "r1")
    assert keys == {("Q1", "GPT-4o"), ("Q3", "Gemini")}  # FAILED Q2 excluded
    conn.close()
