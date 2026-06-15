from ema_poc.db import connect, init_schema


def test_sandbox_queries_has_job_columns(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(sandbox_queries)")}
    assert {"status", "target_count", "started_at", "finished_at", "error_text"} <= cols


def test_job_columns_added_to_preexisting_db(tmp_path):
    # Simulate an old DB created before the job columns existed.
    import sqlite3
    p = str(tmp_path / "old.sqlite")
    raw = sqlite3.connect(p)
    raw.execute(
        "CREATE TABLE sandbox_queries (query_id TEXT PRIMARY KEY, timestamp_utc TEXT, "
        "question_text TEXT, persona TEXT, brand_focus TEXT)"
    )
    raw.commit(); raw.close()
    conn = connect(p)
    init_schema(conn)  # additive migration must add the new columns
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(sandbox_queries)")}
    assert "status" in cols and "error_text" in cols


def test_connect_sets_busy_timeout(tmp_path, monkeypatch):
    import sqlite3
    from ema_poc import db as dbmod

    real_connect = sqlite3.connect

    def patched(*args, **kwargs):
        c = real_connect(*args, **kwargs)
        c.execute("PRAGMA busy_timeout = 0")  # force a non-5000 starting value
        return c

    monkeypatch.setattr(dbmod.sqlite3, "connect", patched)
    conn = dbmod.connect(str(tmp_path / "t.sqlite"))
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
