from ema_poc.db import connect, init_schema

EXPECTED_TABLES = {
    "questions",
    "runs",
    "responses",
    "scores",
    "alerts",
    "audit_log",
}


def test_init_schema_creates_all_tables(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)

    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r["name"] for r in rows}
    assert EXPECTED_TABLES <= names
    conn.close()


def test_init_schema_is_idempotent(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    init_schema(conn)  # second call must not raise
    conn.close()


def test_row_factory_returns_mappings(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    conn.execute(
        "INSERT INTO runs (run_id, started_at) VALUES (?, ?)",
        ("run-1", "2026-06-13T02:00:00+00:00"),
    )
    conn.commit()
    row = conn.execute("SELECT run_id, status FROM runs").fetchone()
    assert row["run_id"] == "run-1"
    assert row["status"] == "RUNNING"
    conn.close()


def test_scores_table_has_new_columns(tmp_path):
    """scores table must expose confidence_level and citation_quality TEXT columns."""
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(scores)")}
    assert "confidence_level" in cols
    assert "citation_quality" in cols
    conn.close()


def test_response_embeddings_table_exists(tmp_path):
    """init_schema creates response_embeddings with expected columns."""
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(response_embeddings)")}
    assert cols == {"response_id", "model", "vector", "created_at"}
    conn.close()


def test_drift_baselines_table_exists(tmp_path):
    """init_schema creates drift_baselines with expected columns."""
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(drift_baselines)")}
    assert cols == {"question_id", "llm_name", "response_id", "competitive_position", "frozen_at"}
    conn.close()


def test_hallucination_checks_table_exists(tmp_path):
    """init_schema creates hallucination_checks with expected columns."""
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(hallucination_checks)")}
    assert cols == {"response_id", "risk_level", "rationale", "model", "created_at"}
    conn.close()


def test_hallucination_flags_table_exists(tmp_path):
    """init_schema creates hallucination_flags with expected columns."""
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(hallucination_flags)")}
    assert cols == {"flag_id", "response_id", "claim", "conflicts_with", "severity", "created_at"}
    conn.close()


def test_consensus_table_exists(tmp_path):
    """init_schema creates consensus table with the expected columns."""
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(consensus)")}
    assert cols == {
        "consensus_id",
        "run_id",
        "question_id",
        "llm_name",
        "canonical_position",
        "agreement",
        "sentiment_mean",
        "sentiment_stdev",
        "sample_count",
        "created_at",
    }
    conn.close()


def test_init_schema_migrates_missing_columns(tmp_path):
    """init_schema must ALTER in additive columns missing from a pre-existing DB."""
    import sqlite3 as _sqlite3

    p = str(tmp_path / "old.sqlite")
    # create a minimal OLD-style responses + scores table WITHOUT the new columns
    raw = _sqlite3.connect(p)
    raw.execute(
        "CREATE TABLE responses ("
        "response_id TEXT PRIMARY KEY, run_id TEXT, timestamp_utc TEXT, "
        "llm_name TEXT, llm_model_version TEXT, persona TEXT, question_id TEXT, "
        "question_text TEXT, domain TEXT, response_text TEXT, status TEXT, "
        "created_at TEXT)"
    )
    raw.execute(
        "CREATE TABLE scores ("
        "score_id TEXT PRIMARY KEY, response_id TEXT, version INTEGER, "
        "sentiment_score REAL, competitive_position TEXT, brand_mentions TEXT, "
        "key_claims TEXT, scoring_rationale TEXT, scoring_model TEXT, "
        "human_override INTEGER, override_rationale TEXT, created_at TEXT)"
    )
    raw.commit()
    raw.close()

    conn = connect(p)
    init_schema(conn)  # should ALTER in the missing columns, no error

    rcols = {r["name"] for r in conn.execute("PRAGMA table_info(responses)")}
    scols = {r["name"] for r in conn.execute("PRAGMA table_info(scores)")}
    assert "provenance" in rcols
    assert "sample_index" in rcols
    assert "confidence_level" in scols
    assert "citation_quality" in scols

    # idempotent: running again is fine
    init_schema(conn)
    conn.close()
