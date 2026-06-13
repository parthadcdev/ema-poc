from ema_poc.audit import list_events, record_event
from ema_poc.db import connect, init_schema


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def test_record_event_persists_row(tmp_path):
    conn = _conn(tmp_path)
    record_event(
        conn,
        event_type="LLM_CALL",
        role="TARGET",
        question_id="Q1",
        llm_target="GPT-4o",
        http_status=200,
        detail="ok",
        timestamp="2026-06-13T02:00:00+00:00",
    )
    events = list_events(conn)
    assert len(events) == 1
    assert events[0]["event_type"] == "LLM_CALL"
    assert events[0]["role"] == "TARGET"
    assert events[0]["http_status"] == 200


def test_events_accumulate_append_only(tmp_path):
    conn = _conn(tmp_path)
    record_event(conn, event_type="A", timestamp="2026-06-13T02:00:00+00:00")
    record_event(conn, event_type="B", timestamp="2026-06-13T02:00:01+00:00")
    events = list_events(conn)
    assert [e["event_type"] for e in events] == ["A", "B"]


def test_module_exposes_no_mutation_helpers():
    import ema_poc.audit as audit

    # Audit log is insert-only by design (SE-003): no update/delete helpers.
    assert not hasattr(audit, "update_event")
    assert not hasattr(audit, "delete_event")
