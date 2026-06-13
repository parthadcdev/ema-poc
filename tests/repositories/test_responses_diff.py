from ema_poc.db import connect, init_schema
from ema_poc.models import Response
from ema_poc.repositories.responses import detect_change, latest_responses, save_response
from ema_poc.repositories.runs import create_run

T1 = "2026-06-13T01:00:00+00:00"
T2 = "2026-06-13T02:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=T1)
    return conn


def _save(conn, rid, *, ts, text, question_id="Q1", llm="GPT-4o"):
    save_response(conn, Response(
        response_id=rid, run_id="r1", timestamp_utc=ts, llm_name=llm,
        llm_model_version="m", persona="Provider", question_id=question_id,
        question_text="q", domain="Safety", response_text=text, response_tokens=1,
        finish_reason="stop", status="SUCCESS", created_at=ts,
    ))


def test_latest_responses_returns_newest_first(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "old", ts=T1, text="v1")
    _save(conn, "new", ts=T2, text="v2")
    latest = latest_responses(conn, "Q1", "GPT-4o", limit=2)
    assert [r.response_id for r in latest] == ["new", "old"]
    conn.close()


def test_detect_change_flags_difference_with_diff(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "old", ts=T1, text="Drug X is first-line.")
    _save(conn, "new", ts=T2, text="Drug X is second-line.")
    change = detect_change(conn, "Q1", "GPT-4o")
    assert change.changed is True
    assert change.previous_text == "Drug X is first-line."
    assert change.current_text == "Drug X is second-line."
    assert "second-line" in change.diff
    conn.close()


def test_detect_change_false_when_identical(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "old", ts=T1, text="same")
    _save(conn, "new", ts=T2, text="same")
    change = detect_change(conn, "Q1", "GPT-4o")
    assert change.changed is False
    assert change.diff == ""
    conn.close()


def test_detect_change_no_previous_returns_unchanged(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "only", ts=T1, text="first ever")
    change = detect_change(conn, "Q1", "GPT-4o")
    assert change.changed is False
    assert change.previous_text is None
    assert change.current_text == "first ever"
    conn.close()


def test_detect_change_no_responses_at_all(tmp_path):
    conn = _conn(tmp_path)
    change = detect_change(conn, "Q-none", "GPT-4o")
    assert change.changed is False
    assert change.previous_text is None
    assert change.current_text is None
    assert change.diff == ""
    conn.close()
