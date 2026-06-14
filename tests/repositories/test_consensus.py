"""Tests for ema_poc.repositories.consensus."""

from ema_poc.db import connect, init_schema
from ema_poc.repositories import consensus as C


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


NOW = "2026-06-14T00:00:00+00:00"


def test_save_and_list_consensus_round_trip(tmp_path):
    conn = _conn(tmp_path)

    # Row with all fields populated
    cid1 = C.save_consensus(
        conn,
        consensus_id="c001",
        run_id="run1",
        question_id="q1",
        llm_name="gpt-4",
        canonical_position="POSITIVE",
        agreement=0.9,
        sentiment_mean=0.75,
        sentiment_stdev=0.05,
        sample_count=3,
        now=NOW,
    )

    # Row with canonical_position=None and null sentiment fields
    cid2 = C.save_consensus(
        conn,
        run_id="run1",
        question_id="q2",
        llm_name="claude-3",
        canonical_position=None,
        agreement=0.5,
        sentiment_mean=None,
        sentiment_stdev=None,
        sample_count=3,
        now=NOW,
    )

    rows = C.list_consensus(conn)
    assert len(rows) == 2

    r1 = rows[0]
    assert r1.consensus_id == "c001"
    assert r1.run_id == "run1"
    assert r1.question_id == "q1"
    assert r1.llm_name == "gpt-4"
    assert r1.canonical_position == "POSITIVE"
    assert r1.agreement == 0.9
    assert r1.sentiment_mean == 0.75
    assert r1.sentiment_stdev == 0.05
    assert r1.sample_count == 3
    assert r1.created_at == NOW

    r2 = rows[1]
    assert r2.canonical_position is None
    assert r2.sentiment_mean is None
    assert r2.sentiment_stdev is None
    assert r2.agreement == 0.5

    # Verify returned IDs
    assert cid1 == "c001"
    assert len(cid2) == 32  # uuid4().hex is 32 chars


def test_existing_groups_empty_initially(tmp_path):
    conn = _conn(tmp_path)
    assert C.existing_groups(conn) == set()


def test_existing_groups_returns_saved_tuples(tmp_path):
    conn = _conn(tmp_path)

    C.save_consensus(
        conn,
        run_id="run1", question_id="q1", llm_name="gpt-4",
        canonical_position="POSITIVE", agreement=0.9,
        sentiment_mean=0.7, sentiment_stdev=0.1, sample_count=3, now=NOW,
    )
    C.save_consensus(
        conn,
        run_id="run1", question_id="q2", llm_name="claude-3",
        canonical_position=None, agreement=0.6,
        sentiment_mean=None, sentiment_stdev=None, sample_count=3, now=NOW,
    )

    groups = C.existing_groups(conn)
    assert groups == {
        ("run1", "q1", "gpt-4"),
        ("run1", "q2", "claude-3"),
    }


def test_save_consensus_uses_provided_consensus_id(tmp_path):
    conn = _conn(tmp_path)
    returned = C.save_consensus(
        conn,
        consensus_id="explicit-id",
        run_id="run1", question_id="q1", llm_name="gpt-4",
        canonical_position="NEUTRAL", agreement=0.7,
        sentiment_mean=0.5, sentiment_stdev=0.2, sample_count=3, now=NOW,
    )
    assert returned == "explicit-id"
    rows = C.list_consensus(conn)
    assert rows[0].consensus_id == "explicit-id"


def test_save_consensus_generates_id_when_not_provided(tmp_path):
    conn = _conn(tmp_path)
    returned = C.save_consensus(
        conn,
        run_id="run1", question_id="q1", llm_name="gpt-4",
        canonical_position="NEGATIVE", agreement=0.8,
        sentiment_mean=None, sentiment_stdev=None, sample_count=3, now=NOW,
    )
    assert isinstance(returned, str)
    assert len(returned) == 32  # uuid4().hex
