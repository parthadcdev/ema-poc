from ema_poc.db import connect, init_schema
from ema_poc.repositories.runs import create_run, finish_run, get_run, list_runs

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


def test_create_run_with_backfill_for(tmp_path):
    conn = _conn(tmp_path)
    create_run(conn, "r1", started_at=NOW, backfill_for="2026-06-10")
    run = get_run(conn, "r1")
    assert run.backfill_for == "2026-06-10"
    conn.close()


def test_create_run_without_backfill_for_is_none(tmp_path):
    conn = _conn(tmp_path)
    create_run(conn, "r2", started_at=NOW)
    run = get_run(conn, "r2")
    assert run.backfill_for is None
    conn.close()


def test_list_runs_returns_ordered_by_started_at(tmp_path):
    conn = _conn(tmp_path)
    create_run(conn, "r2", started_at="2026-06-02T08:00:00+00:00")
    create_run(conn, "r1", started_at="2026-06-01T08:00:00+00:00")
    runs = list_runs(conn)
    assert len(runs) == 2
    assert runs[0].run_id == "r1"
    assert runs[1].run_id == "r2"
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
