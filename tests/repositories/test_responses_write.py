import hashlib
import json

from ema_poc.adapters.base import LLMResponse
from ema_poc.db import connect, init_schema
from ema_poc.models import Question, Response, ResponseStatus
from ema_poc.repositories.responses import build_response, completed_keys, get_response, save_response
from ema_poc.repositories.runs import create_run

NOW = "2026-06-13T02:00:00+00:00"


class _FakeAdapter:
    def __init__(self, name="GPT-4o", model_version="gpt-4o-2024-11-20",
                 params=None, grounded=False):
        self.name = name
        self.model_version = model_version
        self.params = params or {}
        self.grounded = grounded


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
    assert keys == {("Q1", "GPT-4o", 0), ("Q3", "Gemini", 0)}  # FAILED Q2 excluded
    conn.close()


# ---------------------------------------------------------------------------
# Provenance tests (FR-304)
# ---------------------------------------------------------------------------

def test_build_response_provenance_contains_all_four_keys():
    """build_response with system_prompt produces a Response whose provenance
    JSON contains model_version, params, grounded, and system_prompt_sha256."""
    adapter = _FakeAdapter(
        name="Claude", model_version="claude-3-sonnet",
        params={"temperature": 0.0, "max_tokens": 1024},
        grounded=True,
    )
    llm = LLMResponse(text="resp", finish_reason="stop", status="SUCCESS",
                      prompt_tokens=5, completion_tokens=8)
    r = build_response(
        run_id="r1", question=_q(), adapter=adapter, llm_response=llm,
        now=NOW, response_id="resp-prov-1", system_prompt="SYS",
    )
    assert r.provenance is not None
    prov = json.loads(r.provenance)
    assert prov["model_version"] == "claude-3-sonnet"
    assert prov["params"] == {"temperature": 0.0, "max_tokens": 1024}
    assert prov["grounded"] is True
    expected_sha = hashlib.sha256("SYS".encode("utf-8")).hexdigest()
    assert prov["system_prompt_sha256"] == expected_sha


def test_build_response_provenance_empty_system_prompt():
    """Default (no system_prompt kwarg) hashes the empty string."""
    adapter = _FakeAdapter()
    llm = LLMResponse(text="x", finish_reason="stop", status="SUCCESS")
    r = build_response(
        run_id="r1", question=_q(), adapter=adapter, llm_response=llm,
        now=NOW, response_id="resp-prov-2",
    )
    prov = json.loads(r.provenance)
    expected_sha = hashlib.sha256(b"").hexdigest()
    assert prov["system_prompt_sha256"] == expected_sha
    assert prov["grounded"] is False
    assert prov["params"] == {}


def test_provenance_json_is_deterministic():
    """Calling build_response twice with the same inputs produces identical
    provenance strings (sort_keys ensures stable serialisation)."""
    adapter = _FakeAdapter(params={"z": 1, "a": 2})
    llm = LLMResponse(text="x", finish_reason="stop", status="SUCCESS")
    r1 = build_response(run_id="r1", question=_q(), adapter=adapter,
                        llm_response=llm, now=NOW, response_id="p1",
                        system_prompt="hello")
    r2 = build_response(run_id="r1", question=_q(), adapter=adapter,
                        llm_response=llm, now=NOW, response_id="p2",
                        system_prompt="hello")
    assert r1.provenance == r2.provenance


def test_save_response_round_trip_preserves_provenance(tmp_path):
    """Provenance written by save_response is readable back from the DB."""
    conn = _conn(tmp_path)
    adapter = _FakeAdapter(
        model_version="gpt-4o-2024-11-20",
        params={"temperature": 0.5},
        grounded=False,
    )
    llm = LLMResponse(text="ans", finish_reason="stop", status="SUCCESS",
                      completion_tokens=10)
    r = build_response(run_id="r1", question=_q(), adapter=adapter,
                       llm_response=llm, now=NOW, response_id="resp-rt-1",
                       system_prompt="You are a helpful assistant.")
    save_response(conn, r)

    row = conn.execute(
        "SELECT provenance FROM responses WHERE response_id='resp-rt-1'"
    ).fetchone()
    assert row["provenance"] is not None
    prov = json.loads(row["provenance"])
    assert prov["model_version"] == "gpt-4o-2024-11-20"
    assert prov["params"] == {"temperature": 0.5}
    assert prov["grounded"] is False
    expected_sha = hashlib.sha256(
        "You are a helpful assistant.".encode("utf-8")
    ).hexdigest()
    assert prov["system_prompt_sha256"] == expected_sha
    conn.close()


# ---------------------------------------------------------------------------
# sample_index tests (consensus groundwork)
# ---------------------------------------------------------------------------

def test_build_response_sample_index_set():
    """build_response with sample_index=2 returns Response.sample_index == 2."""
    llm = LLMResponse(text="ans", finish_reason="stop", status="SUCCESS",
                      prompt_tokens=5, completion_tokens=10)
    r = build_response(
        run_id="r1", question=_q(), adapter=_FakeAdapter(),
        llm_response=llm, now=NOW, response_id="resp-si-1",
        sample_index=2,
    )
    assert r.sample_index == 2


def test_build_response_sample_index_default():
    """build_response without sample_index defaults to 0."""
    llm = LLMResponse(text="ans", finish_reason="stop", status="SUCCESS")
    r = build_response(
        run_id="r1", question=_q(), adapter=_FakeAdapter(),
        llm_response=llm, now=NOW, response_id="resp-si-0",
    )
    assert r.sample_index == 0


def test_save_response_persists_sample_index(tmp_path):
    """save_response stores sample_index; get_response round-trips it."""
    conn = _conn(tmp_path)
    llm = LLMResponse(text="ans", finish_reason="stop", status="SUCCESS",
                      completion_tokens=5)
    r = build_response(run_id="r1", question=_q(), adapter=_FakeAdapter(),
                       llm_response=llm, now=NOW, response_id="resp-si-rt-1",
                       sample_index=3)
    save_response(conn, r)
    retrieved = get_response(conn, "resp-si-rt-1")
    assert retrieved is not None
    assert retrieved.sample_index == 3
    conn.close()


def test_save_response_default_sample_index_zero(tmp_path):
    """Omitting sample_index persists 0 to the DB."""
    conn = _conn(tmp_path)
    llm = LLMResponse(text="ans", finish_reason="stop", status="SUCCESS")
    r = build_response(run_id="r1", question=_q(), adapter=_FakeAdapter(),
                       llm_response=llm, now=NOW, response_id="resp-si-def-1")
    save_response(conn, r)
    row = conn.execute(
        "SELECT sample_index FROM responses WHERE response_id='resp-si-def-1'"
    ).fetchone()
    assert row["sample_index"] == 0
    conn.close()


def test_completed_keys_returns_3_tuples_with_sample_index(tmp_path):
    """completed_keys returns (question_id, llm_name, sample_index) triples."""
    conn = _conn(tmp_path)
    ok = LLMResponse(text="a", finish_reason="stop", status="SUCCESS")
    save_response(conn, build_response(run_id="r1", question=_q("Q1"),
                  adapter=_FakeAdapter("GPT-4o"), llm_response=ok, now=NOW,
                  response_id="ck-1", sample_index=0))
    save_response(conn, build_response(run_id="r1", question=_q("Q1"),
                  adapter=_FakeAdapter("GPT-4o"), llm_response=ok, now=NOW,
                  response_id="ck-2", sample_index=1))
    keys = completed_keys(conn, "r1")
    assert ("Q1", "GPT-4o", 0) in keys
    assert ("Q1", "GPT-4o", 1) in keys
    conn.close()


def test_completed_keys_excludes_failed_sample(tmp_path):
    """FAILED sample_index is not included in completed_keys."""
    conn = _conn(tmp_path)
    ok = LLMResponse(text="a", finish_reason="stop", status="SUCCESS")
    failed = LLMResponse(text="", finish_reason="error", status="FAILED")
    save_response(conn, build_response(run_id="r1", question=_q("Q1"),
                  adapter=_FakeAdapter("GPT-4o"), llm_response=ok, now=NOW,
                  response_id="ck-ok-1", sample_index=0))
    save_response(conn, build_response(run_id="r1", question=_q("Q1"),
                  adapter=_FakeAdapter("GPT-4o"), llm_response=failed, now=NOW,
                  response_id="ck-fail-1", sample_index=1))
    keys = completed_keys(conn, "r1")
    assert ("Q1", "GPT-4o", 0) in keys
    assert ("Q1", "GPT-4o", 1) not in keys  # FAILED excluded
    conn.close()
