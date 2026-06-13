from ema_poc.db import connect, init_schema
from ema_poc.repositories.runs import create_run, finish_run, get_run

NOW = "2026-06-13T02:00:00+00:00"
LATER = "2026-06-13T03:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def test_create_and_get_run(tmp_path):
    conn = _conn(tmp_path)
    create_run(conn, "r1", started_at=NOW)
    run = get_run(conn, "r1")
    assert run.run_id == "r1"
    assert run.status == "RUNNING"
    assert run.responses_captured == 0
    assert get_run(conn, "missing") is None
    conn.close()


def test_finish_run_updates_summary_fields(tmp_path):
    conn = _conn(tmp_path)
    create_run(conn, "r1", started_at=NOW)
    finish_run(
        conn,
        "r1",
        ended_at=LATER,
        questions_attempted=10,
        responses_captured=28,
        failure_count=2,
        total_tokens=1234,
        est_cost=0.56,
    )
    run = get_run(conn, "r1")
    assert run.status == "COMPLETED"
    assert run.ended_at is not None
    assert run.questions_attempted == 10
    assert run.responses_captured == 28
    assert run.failure_count == 2
    assert run.total_tokens == 1234
    assert run.est_cost == 0.56
    conn.close()
