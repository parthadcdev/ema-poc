from ema_poc.db import connect, init_schema
from ema_poc.repositories import sandbox as S


def _conn(tmp_path):
    c = connect(str(tmp_path / "s.sqlite")); init_schema(c); return c


def test_create_query_records_running_status(tmp_path):
    c = _conn(tmp_path)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None,
                         now="2026-06-15T00:00:00+00:00", status="RUNNING",
                         target_count=3, started_at="2026-06-15T00:00:00+00:00")
    q = S.get_query(c, qid)
    assert q.status == "RUNNING" and q.target_count == 3
    assert q.started_at == "2026-06-15T00:00:00+00:00"


def test_get_query_unknown_returns_none(tmp_path):
    assert S.get_query(_conn(tmp_path), "nope") is None


def test_mark_done_and_failed(tmp_path):
    c = _conn(tmp_path)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None,
                         now="t0", status="RUNNING", target_count=1, started_at="t0")
    S.mark_query_done(c, qid, finished_at="t1")
    q = S.get_query(c, qid)
    assert q.status == "DONE"
    assert q.finished_at == "t1"
    qid2 = S.create_query(c, question_text="q2", persona=None, brand_focus=None,
                          now="t0", status="RUNNING", target_count=1, started_at="t0")
    S.mark_query_failed(c, qid2, finished_at="t1", error_text="boom")
    q2 = S.get_query(c, qid2)
    assert q2.status == "FAILED" and q2.error_text == "boom"


def test_mark_query_done_unknown_raises(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        S.mark_query_done(_conn(tmp_path), "missing", finished_at="t1")


def test_sweep_stale_running_marks_failed(tmp_path):
    c = _conn(tmp_path)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None,
                         now="t0", status="RUNNING", target_count=1, started_at="t0")
    n = S.sweep_stale_running(c, finished_at="t9")
    assert n == 1
    q = S.get_query(c, qid)
    assert q.status == "FAILED" and q.error_text == "interrupted by restart"


def test_list_recent_queries_returns_status_and_counts(tmp_path):
    c = _conn(tmp_path)
    qid = S.create_query(c, question_text="q", persona="Provider", brand_focus="Skyrizi",
                         now="2026-06-15T00:00:00+00:00", status="RUNNING",
                         target_count=2, started_at="2026-06-15T00:00:00+00:00")
    S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v", grounded=False,
                    answer_text="a", response_tokens=1, finish_reason="stop",
                    status="SUCCESS", now="t1")
    rows = S.list_recent_queries(c)
    assert len(rows) == 1
    assert rows[0].status == "RUNNING"
    assert rows[0].done_count == 1 and rows[0].total_count == 2


def test_legacy_null_status_reads_as_done(tmp_path):
    c = _conn(tmp_path)
    # Insert a row with NULL status (legacy), bypassing create_query.
    c.execute("INSERT INTO sandbox_queries (query_id, timestamp_utc, question_text, "
              "persona, brand_focus) VALUES ('L','t','q',NULL,NULL)")
    c.commit()
    assert S.get_query(c, "L").status == "DONE"
    assert S.list_recent_queries(c)[0].status == "DONE"
