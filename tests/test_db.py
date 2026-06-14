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
