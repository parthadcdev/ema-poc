import sqlite3
import pytest

from ema_poc.db import connect, init_schema
from ema_poc.adapters.base import Citation
from ema_poc.repositories import citations as C


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    # response_citations has an FK to responses; insert a minimal parent run+response.
    conn.execute(
        "INSERT INTO runs (run_id, started_at) VALUES ('r1', '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        """INSERT INTO responses (response_id, run_id, timestamp_utc, llm_name,
           llm_model_version, persona, question_id, question_text, domain,
           response_text, status, created_at)
           VALUES ('resp1','r1','2026-01-01T00:00:00+00:00','L','m','Provider',
           'Q1','q','General','ans','SUCCESS','2026-01-01T00:00:00+00:00')"""
    )
    conn.commit()
    return conn


def test_save_and_list_citations(tmp_path):
    conn = _conn(tmp_path)
    C.save_citations(
        conn, response_id="resp1",
        citations=[
            Citation(title="A", url="https://a", snippet="sa"),
            Citation(title="B", url="https://b"),
        ],
        now="2026-01-01T00:00:00+00:00",
        id_factory=iter(["c1", "c2"]).__next__,
    )
    rows = C.list_citations(conn, "resp1")
    assert [(r.title, r.url, r.snippet) for r in rows] == [
        ("A", "https://a", "sa"), ("B", "https://b", None)
    ]


def test_save_empty_citations_is_noop(tmp_path):
    conn = _conn(tmp_path)
    C.save_citations(conn, response_id="resp1", citations=[], now="2026-01-01T00:00:00+00:00")
    assert C.list_citations(conn, "resp1") == []


def test_citation_fk_rejects_unknown_response(tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        C.save_citations(
            conn, response_id="nope", citations=[Citation(title="A", url="https://a")],
            now="2026-01-01T00:00:00+00:00", id_factory=iter(["c1"]).__next__,
        )
