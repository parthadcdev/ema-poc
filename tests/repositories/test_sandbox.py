import sqlite3
import pytest

from ema_poc.db import connect, init_schema
from ema_poc.adapters.base import Citation
from ema_poc.repositories import sandbox as S


def _conn(tmp_path):
    conn = connect(str(tmp_path / "s.sqlite"))
    init_schema(conn)
    return conn


def test_create_query_and_save_response_with_citations(tmp_path):
    conn = _conn(tmp_path)
    qid = S.create_query(
        conn, question_text="What treats psoriasis?", persona="Provider",
        brand_focus="Skyrizi", now="2026-01-01T00:00:00+00:00",
        id_factory=lambda: "q1",
    )
    assert qid == "q1"
    rid = S.save_response(
        conn, query_id=qid, llm_name="GPT-4o", llm_model_version="gpt-4o",
        grounded=False, answer_text="Biologics.", response_tokens=12,
        finish_reason="stop", status="SUCCESS", now="2026-01-01T00:00:00+00:00",
        id_factory=lambda: "sr1",
    )
    S.save_response_citations(
        conn, sandbox_response_id=rid,
        citations=[Citation(title="A", url="https://a", snippet="x")],
        now="2026-01-01T00:00:00+00:00", id_factory=iter(["sc1"]).__next__,
    )
    S.set_response_score(
        conn, sandbox_response_id=rid, sentiment_score=0.4,
        competitive_position="AMONG_OPTIONS", scoring_rationale="ok",
    )

    rows = S.list_query_responses(conn, qid)
    assert len(rows) == 1
    r = rows[0]
    assert r.llm_name == "GPT-4o"
    assert r.sentiment_score == 0.4
    assert r.competitive_position == "AMONG_OPTIONS"
    assert [(c.title, c.url, c.snippet) for c in r.citations] == [("A", "https://a", "x")]


def test_list_recent_queries_newest_first(tmp_path):
    conn = _conn(tmp_path)
    S.create_query(conn, question_text="q1", persona=None, brand_focus=None,
                   now="2026-01-01T00:00:00+00:00", id_factory=lambda: "a")
    S.create_query(conn, question_text="q2", persona=None, brand_focus=None,
                   now="2026-01-02T00:00:00+00:00", id_factory=lambda: "b")
    recent = S.list_recent_queries(conn, limit=10)
    assert [q.question_text for q in recent] == ["q2", "q1"]


def test_response_fk_requires_existing_query(tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        S.save_response(
            conn, query_id="missing", llm_name="L", llm_model_version="m",
            grounded=False, answer_text="x", response_tokens=None,
            finish_reason="stop", status="SUCCESS",
            now="2026-01-01T00:00:00+00:00", id_factory=lambda: "sr1",
        )
